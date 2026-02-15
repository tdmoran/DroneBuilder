"""Build validation routes — htmx partials."""

from __future__ import annotations

import json

from flask import Blueprint, render_template, abort

from core.fleet import FLEET_DIR, load_fleet_drone
from engines.compatibility import validate_build

validation_bp = Blueprint("validation", __name__)


@validation_bp.route("/<filename>")
def validate(filename: str):
    """Run validation and return styled report partial (htmx-swapped)."""
    filepath = FLEET_DIR / f"{filename}.json"
    if not filepath.exists():
        abort(404)

    with open(filepath) as f:
        data = json.load(f)

    drone = load_fleet_drone(data, source_file=str(filepath))
    report = validate_build(drone)

    return render_template(
        "partials/_validation_report.html",
        report=report,
    )
