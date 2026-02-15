"""Flask application factory for DroneBuilder web UI."""

from __future__ import annotations

from pathlib import Path

from flask import Flask


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.secret_key = "dronebuilder-dev-key"

    # Register blueprints
    from web.routes.components import components_bp
    from web.routes.diagnose import diagnose_bp
    from web.routes.fleet import fleet_bp
    from web.routes.serial import serial_bp
    from web.routes.validation import validation_bp

    app.register_blueprint(components_bp, url_prefix="/components")
    app.register_blueprint(diagnose_bp, url_prefix="/diagnose")
    app.register_blueprint(fleet_bp, url_prefix="/fleet")
    app.register_blueprint(validation_bp, url_prefix="/validate")
    app.register_blueprint(serial_bp, url_prefix="/serial")

    # Dashboard route
    @app.route("/")
    def index():
        from flask import render_template

        from core.fleet import load_fleet
        from core.loader import load_components

        fleet = load_fleet()
        all_components = load_components()

        # Fleet stats by status
        status_counts: dict[str, int] = {}
        for drone in fleet:
            status_counts[drone.status] = status_counts.get(drone.status, 0) + 1

        # Component counts by type
        component_counts = {ctype: len(comps) for ctype, comps in all_components.items()}

        return render_template(
            "index.html",
            fleet=fleet,
            fleet_count=len(fleet),
            status_counts=status_counts,
            component_counts=component_counts,
            total_components=sum(component_counts.values()),
        )

    # Custom 404 handler
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template

        return render_template("base.html", title="Not Found", content_block="not_found"), 404

    return app


def create_socketio_app():
    """Create Flask app with SocketIO for serial terminal support."""
    from flask_socketio import SocketIO

    from web.routes.serial import init_serial_socketio

    app = create_app()
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
    init_serial_socketio(socketio)

    return app, socketio
