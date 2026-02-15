"""FC Diagnostic workflow routes — htmx-driven progressive disclosure."""

from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, render_template, request

from core.config_store import list_configs, load_config, save_config
from core.fleet import FLEET_DIR, load_fleet, load_fleet_drone, name_to_filename
from engines.diagnose import run_diagnostics
from engines.discrepancy import detect_discrepancies
from engines.symptom_map import FIX_SUGGESTIONS, SYMPTOMS
from fc_serial.config_parser import parse_diff_all

diagnose_bp = Blueprint("diagnose", __name__)


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
        selected_drone=selected,
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

    if not drone_filename or not raw_text.strip():
        abort(400)

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

    if not drone_filename or not raw_text.strip():
        abort(400)

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

    from core.fleet import save_fleet_drone
    save_fleet_drone(fleet_data, filename)

    return jsonify({"updated": True, "filename": filename})
