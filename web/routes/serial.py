"""Serial / FC connectivity routes — REST endpoints + SocketIO bridge."""

from __future__ import annotations

import json
import threading

from flask import Blueprint, abort, jsonify, render_template, request

serial_bp = Blueprint("serial", __name__)

# SocketIO instance — set by init_serial_socketio() from app.py
_socketio = None
_reader_threads: dict[str, threading.Thread] = {}


def init_serial_socketio(socketio) -> None:
    """Register SocketIO event handlers for serial terminal bridge."""
    global _socketio
    _socketio = socketio

    @socketio.on("serial_input", namespace="/serial")
    def handle_serial_input(data):
        """Forward keyboard input from browser terminal to serial port."""
        from fc_serial.connection import get_active_port, get_connection

        port = get_active_port()
        if not port:
            return

        conn = get_connection(port)
        if conn and conn.is_open:
            conn.write(data.encode("utf-8") if isinstance(data, str) else data)

    @socketio.on("connect", namespace="/serial")
    def handle_ws_connect():
        from fc_serial.connection import get_active_port

        port = get_active_port()
        socketio.emit(
            "connection_status",
            {"connected": port is not None, "port": port or ""},
            namespace="/serial",
        )


def _start_reader_thread(port: str) -> None:
    """Start a background thread that reads serial and emits to SocketIO."""
    if port in _reader_threads and _reader_threads[port].is_alive():
        return

    def reader_loop():
        from fc_serial.connection import get_connection

        while True:
            conn = get_connection(port)
            if not conn or not conn.is_open:
                break

            try:
                if conn.in_waiting > 0:
                    data = conn.read_all()
                    if data and _socketio:
                        _socketio.emit(
                            "serial_output",
                            data.decode("utf-8", errors="replace"),
                            namespace="/serial",
                        )
                else:
                    import time
                    time.sleep(0.02)
            except Exception:
                break

        if _socketio:
            _socketio.emit(
                "connection_status",
                {"connected": False, "port": ""},
                namespace="/serial",
            )

    thread = threading.Thread(target=reader_loop, daemon=True, name=f"serial-reader-{port}")
    thread.start()
    _reader_threads[port] = thread


# ---------------------------------------------------------------------------
# REST routes
# ---------------------------------------------------------------------------


@serial_bp.route("/terminal")
def terminal():
    """Render the xterm.js terminal page."""
    drone = request.args.get("drone", "")
    return render_template("serial/terminal.html", drone=drone)


@serial_bp.route("/ports")
def list_ports():
    """JSON list of detected FC USB serial ports."""
    from fc_serial.connection import detect_fc_ports, get_active_port

    ports = detect_fc_ports()
    active = get_active_port()

    return jsonify({
        "ports": [
            {
                "device": p.device,
                "description": p.description,
                "vid": p.vid,
                "pid": p.pid,
                "manufacturer": p.manufacturer,
            }
            for p in ports
        ],
        "active_port": active,
    })


@serial_bp.route("/connect", methods=["POST"])
def connect():
    """Open serial connection to a port."""
    from fc_serial.connection import open_connection

    data = request.get_json(silent=True) or {}
    port = data.get("port", "")
    baudrate = int(data.get("baudrate", 115200))

    if not port:
        return jsonify({"error": "No port specified"}), 400

    try:
        conn = open_connection(port, baudrate)
        _start_reader_thread(port)
        return jsonify({"connected": True, "port": port})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@serial_bp.route("/disconnect", methods=["POST"])
def disconnect():
    """Close the active serial connection."""
    from fc_serial.connection import close_connection, get_active_port

    port = get_active_port()
    if port:
        close_connection(port)

    return jsonify({"connected": False})


@serial_bp.route("/status")
def connection_status():
    """Return current connection status as JSON."""
    from fc_serial.connection import get_active_port

    port = get_active_port()
    return jsonify({"connected": port is not None, "port": port or ""})


@serial_bp.route("/diff-all", methods=["POST"])
def read_diff_all():
    """Enter CLI mode, run diff all, parse config, return results."""
    from fc_serial.cli_mode import enter_cli_mode, exit_cli_mode, get_diff_all
    from fc_serial.config_parser import parse_diff_all
    from fc_serial.connection import get_active_port, get_connection

    port = get_active_port()
    if not port:
        return jsonify({"error": "No FC connected"}), 400

    conn = get_connection(port)
    if not conn:
        return jsonify({"error": "Connection lost"}), 500

    try:
        enter_cli_mode(conn)
        raw = get_diff_all(conn)
        exit_cli_mode(conn)

        config = parse_diff_all(raw)

        return jsonify({
            "raw_text": raw,
            "firmware": config.firmware,
            "firmware_version": config.firmware_version,
            "board_name": config.board_name,
            "features": sorted(config.features),
            "settings_count": len(config.master_settings),
            "serial_ports_count": len(config.serial_ports),
        })
    except Exception as exc:
        return jsonify({"error": f"Failed to read config: {exc}"}), 500


@serial_bp.route("/upload-diff", methods=["POST"])
def upload_diff():
    """Upload a diff all text file and parse it (no hardware needed)."""
    from fc_serial.config_parser import parse_diff_all

    raw_text = ""
    if request.content_type and "multipart/form-data" in request.content_type:
        f = request.files.get("diff_file")
        if f:
            raw_text = f.read().decode("utf-8", errors="replace")
    else:
        data = request.get_json(silent=True) or {}
        raw_text = data.get("raw_text", "")

    if not raw_text.strip():
        return jsonify({"error": "No diff all text provided"}), 400

    config = parse_diff_all(raw_text)

    return jsonify({
        "raw_text": raw_text,
        "firmware": config.firmware,
        "firmware_version": config.firmware_version,
        "board_name": config.board_name,
        "features": sorted(config.features),
        "settings_count": len(config.master_settings),
        "serial_ports_count": len(config.serial_ports),
    })


@serial_bp.route("/save-config/<slug>", methods=["POST"])
def save_config(slug: str):
    """Save a config backup for a fleet drone."""
    from core.config_store import save_config as store_save
    from fc_serial.config_parser import parse_diff_all

    data = request.get_json(silent=True) or {}
    raw_text = data.get("raw_text", "")

    if not raw_text.strip():
        return jsonify({"error": "No config text provided"}), 400

    config = parse_diff_all(raw_text)
    stored = store_save(slug, raw_text, config)

    return jsonify({
        "saved": True,
        "timestamp": stored.timestamp,
        "firmware": stored.firmware,
    })


@serial_bp.route("/configs/<slug>")
def config_list(slug: str):
    """htmx partial: list stored configs for a drone."""
    from core.config_store import list_configs

    configs = list_configs(slug)
    return render_template("fleet/_config_history.html", configs=configs, slug=slug)


@serial_bp.route("/configs/<slug>/<ts>")
def config_view(slug: str, ts: str):
    """htmx partial: view a specific stored config."""
    from core.config_store import load_config

    result = load_config(slug, ts)
    if not result:
        abort(404)

    raw_text, config = result
    return render_template("fleet/_config_diff.html", raw_text=raw_text, config=config, slug=slug, ts=ts)


@serial_bp.route("/configs/<slug>/<ts>/validate")
def config_validate(slug: str, ts: str):
    """htmx partial: cross-validate stored FC config against drone build."""
    import json as json_mod

    from core.config_store import load_config
    from core.fleet import FLEET_DIR, load_fleet_drone
    from engines.firmware_validator import validate_firmware_config

    result = load_config(slug, ts)
    if not result:
        abort(404)

    _, config = result

    # Load the drone build
    fleet_path = FLEET_DIR / f"{slug}.json"
    if not fleet_path.exists():
        abort(404)

    with open(fleet_path) as f:
        drone_data = json_mod.load(f)

    drone = load_fleet_drone(drone_data, source_file=str(fleet_path))
    report = validate_firmware_config(config, drone)

    return render_template("fleet/_firmware_validation.html", report=report, config=config)


@serial_bp.route("/configs/<slug>/<ts>/delete", methods=["POST"])
def config_delete(slug: str, ts: str):
    """Delete a config backup."""
    from core.config_store import delete_config

    deleted = delete_config(slug, ts)
    if not deleted:
        abort(404)

    from core.config_store import list_configs

    configs = list_configs(slug)
    return render_template("fleet/_config_history.html", configs=configs, slug=slug)
