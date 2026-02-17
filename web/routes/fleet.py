"""Fleet management routes — CRUD for fleet drones."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

from core.fleet import (
    FLEET_DIR,
    load_fleet,
    load_fleet_drone,
    name_to_filename,
    remove_fleet_drone,
    save_fleet_drone,
)
from core.layouts import CLASS_TO_LAYOUT, get_layout
from core.loader import load_components

fleet_bp = Blueprint("fleet", __name__)

VALID_STATUSES = ["active", "building", "retired", "crashed", "sold"]

# Component slots that may appear as query params in new-from-config
_COMPONENT_KEYS = {"fc", "esc", "receiver", "vtx", "motor", "frame", "propeller", "battery", "camera", "gps"}


def _load_drone_by_filename(filename: str):
    """Load a fleet drone by its JSON filename (without extension).

    Returns (Build, raw_data_dict) or aborts 404.
    """
    filepath = FLEET_DIR / f"{filename}.json"
    if not filepath.exists():
        abort(404)
    with open(filepath) as f:
        data = json.load(f)
    drone = load_fleet_drone(data, source_file=str(filepath))
    return drone, data


# -----------------------------------------------------------------------
# List
# -----------------------------------------------------------------------

@fleet_bp.route("/")
def fleet_list():
    """List all drones with optional status/class filters."""
    fleet = load_fleet()

    status_filter = request.args.get("status", "")
    class_filter = request.args.get("drone_class", "")

    if status_filter:
        fleet = [d for d in fleet if d.status == status_filter]
    if class_filter:
        fleet = [d for d in fleet if d.drone_class == class_filter]

    # Gather filter options from full fleet (before filtering)
    all_fleet = load_fleet()
    statuses = sorted({d.status for d in all_fleet})
    classes = sorted({d.drone_class for d in all_fleet})

    return render_template(
        "fleet/list.html",
        fleet=fleet,
        statuses=statuses,
        classes=classes,
        current_status=status_filter,
        current_class=class_filter,
    )


# -----------------------------------------------------------------------
# Detail
# -----------------------------------------------------------------------

@fleet_bp.route("/<filename>")
def fleet_detail(filename: str):
    """Single drone view with components and stats."""
    drone, data = _load_drone_by_filename(filename)
    layout = get_layout(drone.drone_class)
    return render_template(
        "fleet/detail.html",
        drone=drone,
        data=data,
        filename=filename,
        layout=layout,
    )


# -----------------------------------------------------------------------
# Add
# -----------------------------------------------------------------------

@fleet_bp.route("/new-from-config")
def fleet_new_from_config():
    """Show add drone form pre-populated with FC config detection results."""
    data: dict = {}
    for key in ("name", "drone_class", "status", "notes", "nickname"):
        val = request.args.get(key, "")
        if val:
            data[key] = val
    for key in _COMPONENT_KEYS:
        val = request.args.get(key, "")
        if val:
            data[key] = val

    # Tags come as comma-separated
    tags_raw = request.args.get("tags", "")
    if tags_raw:
        data["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    if not data.get("status"):
        data["status"] = "building"

    all_components = load_components()
    drone_classes = sorted(CLASS_TO_LAYOUT.keys())
    return render_template(
        "fleet/form.html",
        action="new",
        drone_classes=drone_classes,
        all_components=all_components,
        statuses=VALID_STATUSES,
        drone=None,
        data=data,
    )


@fleet_bp.route("/new", methods=["GET"])
def fleet_new():
    """Show add drone form."""
    all_components = load_components()
    drone_classes = sorted(CLASS_TO_LAYOUT.keys())
    return render_template(
        "fleet/form.html",
        action="new",
        drone_classes=drone_classes,
        all_components=all_components,
        statuses=VALID_STATUSES,
        drone=None,
        data={},
    )


@fleet_bp.route("/new", methods=["POST"])
def fleet_new_post():
    """Save a new drone and redirect to detail."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Drone name is required.", "error")
        return redirect(url_for("fleet.fleet_new"))

    drone_class = request.form.get("drone_class", "5inch_freestyle")
    drone_data = {
        "name": name,
        "drone_class": drone_class,
        "status": request.form.get("status", "active"),
        "nickname": request.form.get("nickname", ""),
        "notes": request.form.get("notes", ""),
    }

    # Collect component selections
    layout = get_layout(drone_class)
    for slot in layout:
        value = request.form.get(f"comp_{slot.key}", "")
        if value:
            if slot.key in ("motor", "servo"):
                drone_data[slot.key] = value
            else:
                drone_data[slot.key] = value

    filename = name_to_filename(name)
    save_fleet_drone(drone_data, filename)
    flash(f"Added '{name}' to fleet.", "success")
    return redirect(url_for("fleet.fleet_detail", filename=filename))


# -----------------------------------------------------------------------
# Edit
# -----------------------------------------------------------------------

@fleet_bp.route("/<filename>/edit", methods=["GET"])
def fleet_edit(filename: str):
    """Show edit form pre-populated with existing data."""
    drone, data = _load_drone_by_filename(filename)
    all_components = load_components()
    drone_classes = sorted(CLASS_TO_LAYOUT.keys())
    return render_template(
        "fleet/form.html",
        action="edit",
        filename=filename,
        drone_classes=drone_classes,
        all_components=all_components,
        statuses=VALID_STATUSES,
        drone=drone,
        data=data,
    )


@fleet_bp.route("/<filename>/edit", methods=["POST"])
def fleet_edit_post(filename: str):
    """Save changes and redirect to detail."""
    # Load existing data to preserve fields not in the form
    filepath = FLEET_DIR / f"{filename}.json"
    if not filepath.exists():
        abort(404)
    with open(filepath) as f:
        existing = json.load(f)

    name = request.form.get("name", "").strip() or existing.get("name", "")
    drone_class = request.form.get("drone_class", existing.get("drone_class", "5inch_freestyle"))

    existing["name"] = name
    existing["drone_class"] = drone_class
    existing["status"] = request.form.get("status", existing.get("status", "active"))
    existing["nickname"] = request.form.get("nickname", "")
    existing["notes"] = request.form.get("notes", "")

    # Update component selections
    layout = get_layout(drone_class)
    for slot in layout:
        value = request.form.get(f"comp_{slot.key}", "")
        if value:
            existing[slot.key] = value
        elif slot.key in existing and not value:
            # Clear if user deselected
            del existing[slot.key]

    save_fleet_drone(existing, filename)
    flash(f"Updated '{name}'.", "success")
    return redirect(url_for("fleet.fleet_detail", filename=filename))


# -----------------------------------------------------------------------
# Delete
# -----------------------------------------------------------------------

@fleet_bp.route("/<filename>/delete", methods=["POST"])
def fleet_delete(filename: str):
    """Remove drone and redirect to list."""
    drone, _ = _load_drone_by_filename(filename)
    removed = remove_fleet_drone(filename)
    if removed:
        flash(f"Removed '{drone.name}' from fleet.", "success")
    else:
        flash(f"Could not remove '{drone.name}'.", "error")
    return redirect(url_for("fleet.fleet_list"))


# -----------------------------------------------------------------------
# htmx: layout slots for drone class
# -----------------------------------------------------------------------

@fleet_bp.route("/layout-slots")
def layout_slots():
    """Return component form fields for the selected drone class (htmx partial)."""
    drone_class = request.args.get("drone_class", "5inch_freestyle")
    layout = get_layout(drone_class)
    all_components = load_components()

    # Current selections (for edit mode)
    data = {}
    filename = request.args.get("filename", "")
    if filename:
        filepath = FLEET_DIR / f"{filename}.json"
        if filepath.exists():
            with open(filepath) as f:
                data = json.load(f)

    return render_template(
        "partials/_component_slots.html",
        layout=layout,
        all_components=all_components,
        data=data,
    )
