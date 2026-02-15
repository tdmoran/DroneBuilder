#!/usr/bin/env python3
"""Shortcut to launch the DroneBuilder web UI.

Usage:
    python3 runweb.py          → starts server + opens browser
    python3 dronebuilder.py web   → same thing (via CLI)
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

if __name__ == "__main__":
    import threading
    import webbrowser

    url = "http://127.0.0.1:5555"
    threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"  Starting DroneBuilder web UI at {url}")
    print("  Press Ctrl+C to stop.\n")

    try:
        from web.app import create_socketio_app

        app, socketio = create_socketio_app()
        socketio.run(app, host="127.0.0.1", port=5555, debug=True, use_reloader=True, allow_unsafe_werkzeug=True)
    except ImportError:
        # flask-socketio not installed — fall back to plain Flask
        from web.app import create_app

        app = create_app()
        app.run(host="127.0.0.1", port=5555, debug=True)
