"""FC Diagnostic workflow routes — htmx-driven progressive disclosure."""

from __future__ import annotations

import json
import time
import threading

from flask import Blueprint, abort, jsonify, render_template, request

from core.config_store import list_configs, load_config, save_config
from core.fleet import FLEET_DIR, load_fleet, load_fleet_drone, name_to_filename, save_fleet_drone
from engines.diagnose import run_diagnostics
from engines.discrepancy import detect_discrepancies
from engines.fc_importer import suggest_fleet_drone_from_config
from engines.symptom_map import (
    FIX_SUGGESTIONS,
    SYMPTOMS,
    SYMPTOM_DESCRIPTIONS,
    match_symptom,
)
from fc_serial.config_parser import parse_diff_all

diagnose_bp = Blueprint("diagnose", __name__)

# SocketIO instance — set by init_diagnose_socketio() from app.py
_socketio = None


def init_diagnose_socketio(socketio) -> None:
    """Register SocketIO event handlers for real-time diagnostic progress."""
    global _socketio
    _socketio = socketio

    @socketio.on("connect", namespace="/diagnose")
    def handle_connect():
        socketio.emit(
            "diag_status",
            {"status": "connected"},
            namespace="/diagnose",
        )

    @socketio.on("start_scan", namespace="/diagnose")
    def handle_start_scan(data):
        """Run diagnostics with real-time progress events via SocketIO."""
        drone_filename = data.get("drone_filename", "")
        raw_text = data.get("raw_text", "")
        symptoms = data.get("symptoms", [])
        sid = request.sid

        if not drone_filename or not raw_text.strip():
            socketio.emit(
                "scan_error",
                {"error": "Missing drone selection or FC config."},
                namespace="/diagnose",
                to=sid,
            )
            return

        # Run in a background thread so we can emit progress events
        def run_scan():
            try:
                _run_scan_with_progress(
                    socketio, sid, drone_filename, raw_text, symptoms
                )
            except Exception as exc:
                socketio.emit(
                    "scan_error",
                    {"error": str(exc)},
                    namespace="/diagnose",
                    to=sid,
                )

        thread = threading.Thread(target=run_scan, daemon=True)
        thread.start()


def _run_scan_with_progress(socketio, sid, drone_filename, raw_text, symptoms):
    """Execute the diagnostic pipeline, emitting progress events at each step."""
    from engines.compatibility import validate_build
    from engines.firmware_validator import validate_firmware_config

    ns = "/diagnose"

    def emit(event, data):
        socketio.emit(event, data, namespace=ns, to=sid)

    # Load drone
    filepath = FLEET_DIR / f"{drone_filename}.json"
    if not filepath.exists():
        emit("scan_error", {"error": f"Drone '{drone_filename}' not found."})
        return

    with open(filepath) as f:
        drone_data = json.load(f)
    drone = load_fleet_drone(drone_data, source_file=str(filepath))
    config = parse_diff_all(raw_text)

    fc_info = f"{config.firmware} {config.firmware_version}"
    if config.board_name:
        fc_info += f" on {config.board_name}"

    emit("scan_started", {
        "build_name": drone.name,
        "fc_info": fc_info,
        "symptoms": symptoms,
    })

    # --- Phase 1: Discrepancy Detection ---
    emit("section_started", {"section": "discrepancy", "label": "Hardware Discrepancy Check"})
    time.sleep(0.1)

    emit("check_started", {"id": "disc_scan", "name": "Scanning for hardware mismatches"})
    discrepancies = detect_discrepancies(config, drone)
    time.sleep(0.1)

    for disc in discrepancies:
        emit("check_complete", {
            "id": disc.id,
            "name": f"{disc.component_type.capitalize()} check",
            "passed": False,
            "severity": disc.severity.value,
            "message": disc.message,
            "fix": disc.fix_suggestion,
            "category": "discrepancy",
            "fleet_value": disc.fleet_value,
            "detected_value": disc.detected_value,
        })
        time.sleep(0.05)

    if not discrepancies:
        emit("check_complete", {
            "id": "disc_scan",
            "name": "Hardware discrepancy scan",
            "passed": True,
            "severity": "info",
            "message": "FC config matches fleet record",
            "category": "discrepancy",
        })

    emit("section_complete", {
        "section": "discrepancy",
        "total": len(discrepancies),
        "issues": len(discrepancies),
    })

    # --- Phase 2: Compatibility Validation ---
    emit("section_started", {"section": "compatibility", "label": "Component Compatibility"})
    time.sleep(0.1)

    emit("check_started", {"id": "compat_scan", "name": "Running compatibility rules"})
    compatibility_report = validate_build(drone)
    time.sleep(0.1)

    compat_failures = [r for r in compatibility_report.results if not r.passed]
    compat_passes = [r for r in compatibility_report.results if r.passed]

    for result in compat_failures:
        emit("check_complete", {
            "id": result.constraint_id,
            "name": result.constraint_name,
            "passed": False,
            "severity": result.severity.value,
            "message": result.message,
            "fix": FIX_SUGGESTIONS.get(result.constraint_id, ""),
            "category": "compatibility",
        })
        time.sleep(0.05)

    # Report passed checks as a batch
    if compat_passes:
        emit("checks_passed_batch", {
            "category": "compatibility",
            "count": len(compat_passes),
            "ids": [r.constraint_id for r in compat_passes[:5]],
        })

    emit("section_complete", {
        "section": "compatibility",
        "total": len(compatibility_report.results),
        "issues": len(compat_failures),
    })

    # --- Phase 3: Firmware Validation ---
    emit("section_started", {"section": "firmware", "label": "Firmware Configuration"})
    time.sleep(0.1)

    emit("check_started", {"id": "fw_scan", "name": "Validating firmware settings"})
    firmware_report = validate_firmware_config(config, drone)
    time.sleep(0.1)

    fw_failures = [r for r in firmware_report.results if not r.passed]
    fw_passes = [r for r in firmware_report.results if r.passed]

    for result in fw_failures:
        emit("check_complete", {
            "id": result.constraint_id,
            "name": result.constraint_name,
            "passed": False,
            "severity": result.severity.value,
            "message": result.message,
            "fix": FIX_SUGGESTIONS.get(result.constraint_id, ""),
            "category": "firmware",
        })
        time.sleep(0.05)

    if fw_passes:
        emit("checks_passed_batch", {
            "category": "firmware",
            "count": len(fw_passes),
            "ids": [r.constraint_id for r in fw_passes[:5]],
        })

    emit("section_complete", {
        "section": "firmware",
        "total": len(firmware_report.results),
        "issues": len(fw_failures),
    })

    # --- Phase 4: Config Diff ---
    config_changes = None
    configs = list_configs(drone_filename)
    if len(configs) >= 2:
        prev_result = load_config(drone_filename, configs[1].timestamp)
        if prev_result:
            from engines.diagnose import diff_configs
            _, previous_config = prev_result
            config_changes = diff_configs(previous_config, config)

    # --- Summary ---
    total_issues = len(discrepancies) + len(compat_failures) + len(fw_failures)
    critical_count = (
        sum(1 for d in discrepancies if d.severity.value == "critical")
        + sum(1 for r in compat_failures if r.severity.value == "critical")
        + sum(1 for r in fw_failures if r.severity.value == "critical")
    )
    warning_count = (
        sum(1 for d in discrepancies if d.severity.value == "warning")
        + sum(1 for r in compat_failures if r.severity.value == "warning")
        + sum(1 for r in fw_failures if r.severity.value == "warning")
    )
    info_count = total_issues - critical_count - warning_count

    if critical_count > 0:
        health = "CRITICAL"
    elif warning_count > 0:
        health = "ATTENTION"
    else:
        health = "GOOD"

    emit("scan_complete", {
        "build_name": drone.name,
        "fc_info": fc_info,
        "health": health,
        "total_issues": total_issues,
        "critical": critical_count,
        "warnings": warning_count,
        "info": info_count,
        "config_changes": config_changes,
        "passed_checks": len(compat_passes) + len(fw_passes),
    })


def _load_drone(filename: str):
    """Load a fleet drone by filename (without .json). Aborts 404 if missing."""
    filepath = FLEET_DIR / f"{filename}.json"
    if not filepath.exists():
        abort(404)
    with open(filepath) as f:
        data = json.load(f)
    return load_fleet_drone(data, source_file=str(filepath)), data


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------


@diagnose_bp.route("/")
def index():
    """Main diagnose page with fleet picker, symptom selector, config input."""
    fleet = load_fleet()

    # Pre-select drone if passed as query param
    selected = request.args.get("drone", "")

    return render_template(
        "diagnose/diagnose.html",
        fleet=fleet,
        symptoms=SYMPTOMS,
        symptom_descriptions=SYMPTOM_DESCRIPTIONS,
        selected_drone=selected,
    )


# ---------------------------------------------------------------------------
# Symptom matching (htmx autocomplete)
# ---------------------------------------------------------------------------


@diagnose_bp.route("/match-symptom")
def match_symptom_route():
    """Return matching symptoms as an htmx partial for autocomplete."""
    query = request.args.get("q", "").strip()

    if len(query) < 2:
        return ""

    matches = match_symptom(query)

    if not matches:
        return '<div class="symptom-suggestion-empty">No matching issues found</div>'

    html_parts = []
    for symptom_id, confidence in matches:
        label = SYMPTOMS.get(symptom_id, symptom_id)
        desc = SYMPTOM_DESCRIPTIONS.get(symptom_id, "")
        # Truncate description for the suggestion
        short_desc = desc[:80] + "..." if len(desc) > 80 else desc
        html_parts.append(
            f'<button type="button" class="symptom-suggestion" '
            f'data-symptom-id="{symptom_id}" '
            f'data-symptom-label="{label}" '
            f'onclick="selectSymptomSuggestion(this)">'
            f'<strong>{label}</strong>'
            f'<span class="suggestion-desc">{short_desc}</span>'
            f'</button>'
        )

    return '<div class="symptom-suggestions">' + "".join(html_parts) + "</div>"


# ---------------------------------------------------------------------------
# Drone info partial (htmx)
# ---------------------------------------------------------------------------


@diagnose_bp.route("/drone-info/<filename>")
def drone_info(filename: str):
    """Return a drone info card as an htmx partial."""
    drone, data = _load_drone(filename)

    comp_count = len([k for k in data.keys() if k not in (
        "name", "drone_class", "status", "nickname", "notes", "tags",
        "acquired_date", "component_status",
    )])

    return render_template(
        "diagnose/_drone_info.html",
        drone=drone,
        comp_count=comp_count,
    )


# ---------------------------------------------------------------------------
# Config input (two paths: serial read or upload/paste)
# ---------------------------------------------------------------------------


@diagnose_bp.route("/read-config", methods=["POST"])
def read_config():
    """Connect to FC, read diff all, parse, return JSON summary."""
    from fc_serial.cli_mode import enter_cli_mode, exit_cli_mode, get_diff_all
    from fc_serial.connection import get_active_port, get_connection
    from web.routes.serial import pause_reader, resume_reader

    port = get_active_port()
    if not port:
        return jsonify({"error": "No FC connected"}), 400

    conn = get_connection(port)
    if not conn:
        return jsonify({"error": "Connection lost"}), 500

    drone_filename = request.form.get("drone_filename", "")

    # Pause the terminal reader thread so we get exclusive serial access
    pause_reader()
    try:
        enter_cli_mode(conn)
        raw = get_diff_all(conn)
        exit_cli_mode(conn)

        config = parse_diff_all(raw)

        # Save to config store if a drone is selected
        stored_ts = ""
        if drone_filename:
            stored = save_config(drone_filename, raw, config)
            stored_ts = stored.timestamp

        return jsonify({
            "raw_text": raw,
            "firmware": config.firmware,
            "firmware_version": config.firmware_version,
            "board_name": config.board_name,
            "features_count": len(config.features),
            "serial_ports_count": len(config.serial_ports),
            "stored_timestamp": stored_ts,
        })
    except Exception as exc:
        return jsonify({"error": f"Failed to read config: {exc}"}), 500
    finally:
        resume_reader()


@diagnose_bp.route("/upload-config", methods=["POST"])
def upload_config():
    """Parse uploaded/pasted diff all text, return JSON summary."""
    raw_text = ""
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.files.get("diff_file")
        if f:
            raw_text = f.read().decode("utf-8", errors="replace")
        if not raw_text:
            raw_text = request.form.get("raw_text", "")
    else:
        data = request.get_json(silent=True) or {}
        raw_text = data.get("raw_text", "")

    if not raw_text.strip():
        return jsonify({"error": "No diff all text provided"}), 400

    config = parse_diff_all(raw_text)

    # Save if drone selected
    drone_filename = ""
    stored_ts = ""
    if request.content_type and "multipart/form-data" in request.content_type:
        drone_filename = request.form.get("drone_filename", "")
    else:
        drone_filename = (request.get_json(silent=True) or {}).get("drone_filename", "")

    if drone_filename:
        stored = save_config(drone_filename, raw_text, config)
        stored_ts = stored.timestamp

    return jsonify({
        "raw_text": raw_text,
        "firmware": config.firmware,
        "firmware_version": config.firmware_version,
        "board_name": config.board_name,
        "features_count": len(config.features),
        "serial_ports_count": len(config.serial_ports),
        "stored_timestamp": stored_ts,
    })


# ---------------------------------------------------------------------------
# Scan: discrepancy detection (htmx partial)
# ---------------------------------------------------------------------------


@diagnose_bp.route("/scan", methods=["POST"])
def scan():
    """Run discrepancy detection, return htmx partial."""
    drone_filename = request.form.get("drone_filename", "")
    raw_text = request.form.get("raw_text", "")

    if not drone_filename:
        return '<div class="flash flash-error">No drone selected.</div>'
    if not raw_text.strip():
        return '<div class="flash flash-error">No FC config loaded. Read from FC or paste a diff all first.</div>'

    drone, _ = _load_drone(drone_filename)
    config = parse_diff_all(raw_text)
    discrepancies = detect_discrepancies(config, drone)

    return render_template(
        "diagnose/_discrepancies.html",
        discrepancies=discrepancies,
        drone=drone,
        drone_filename=drone_filename,
        raw_text=raw_text,
    )


# ---------------------------------------------------------------------------
# Run: full diagnostic (htmx partial)
# ---------------------------------------------------------------------------


@diagnose_bp.route("/run", methods=["POST"])
def run():
    """Run full diagnostics after discrepancy resolution. Returns htmx partial."""
    drone_filename = request.form.get("drone_filename", "")
    raw_text = request.form.get("raw_text", "")
    symptoms = request.form.getlist("symptoms")

    if not drone_filename:
        return '<div class="flash flash-error">No drone selected.</div>'
    if not raw_text.strip():
        return '<div class="flash flash-error">No FC config loaded.</div>'

    drone, _ = _load_drone(drone_filename)
    config = parse_diff_all(raw_text)

    # Try to load the previous config for diff
    previous_config = None
    configs = list_configs(drone_filename)
    if len(configs) >= 2:
        # configs[0] is the current one (just saved), configs[1] is previous
        prev_result = load_config(drone_filename, configs[1].timestamp)
        if prev_result:
            _, previous_config = prev_result

    report = run_diagnostics(config, drone, symptoms=symptoms, previous_config=previous_config)

    return render_template(
        "diagnose/_diagnostic_report.html",
        report=report,
        symptoms=SYMPTOMS,
        fix_suggestions=FIX_SUGGESTIONS,
        drone_filename=drone_filename,
    )


# ---------------------------------------------------------------------------
# Update fleet record for resolved discrepancies
# ---------------------------------------------------------------------------


@diagnose_bp.route("/update-fleet/<filename>", methods=["POST"])
def update_fleet(filename: str):
    """Update fleet record to resolve discrepancies. Returns JSON confirmation."""
    filepath = FLEET_DIR / f"{filename}.json"
    if not filepath.exists():
        abort(404)

    data = request.get_json(silent=True) or {}
    updates = data.get("updates", {})

    if not updates:
        return jsonify({"error": "No updates provided"}), 400

    with open(filepath) as f:
        fleet_data = json.load(f)

    # Apply updates (key: component type, value: new component ID or spec changes)
    for key, value in updates.items():
        fleet_data[key] = value

    save_fleet_drone(fleet_data, filename)

    return jsonify({"updated": True, "filename": filename})


# ---------------------------------------------------------------------------
# Suggest fleet drone from FC config
# ---------------------------------------------------------------------------


@diagnose_bp.route("/suggest-drone", methods=["POST"])
def suggest_drone():
    """Parse config and return component match suggestions as JSON."""
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text", "")

    if not raw_text.strip():
        return jsonify({"error": "No config text provided"}), 400

    config = parse_diff_all(raw_text)
    suggestion = suggest_fleet_drone_from_config(config)

    return jsonify(suggestion)


# ---------------------------------------------------------------------------
# Create fleet drone from FC config
# ---------------------------------------------------------------------------


@diagnose_bp.route("/create-drone-from-config", methods=["POST"])
def create_drone_from_config():
    """Create a fleet drone from FC config suggestions. Returns JSON with filename."""
    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text", "")
    name_override = data.get("name", "").strip()
    class_override = data.get("drone_class", "").strip()

    if not raw_text.strip():
        return jsonify({"error": "No config text provided"}), 400

    config = parse_diff_all(raw_text)
    suggestion = suggest_fleet_drone_from_config(config)

    # Apply overrides
    if name_override:
        suggestion["name"] = name_override
    if class_override:
        suggestion["drone_class"] = class_override

    # Remove display-only metadata before saving
    suggestion.pop("_detection", None)
    matched_slots = suggestion.pop("_matched_slots", 0)

    filename = name_to_filename(suggestion["name"])
    save_fleet_drone(suggestion, filename)

    return jsonify({
        "created": True,
        "filename": filename,
        "name": suggestion["name"],
        "matched_slots": matched_slots,
    })
