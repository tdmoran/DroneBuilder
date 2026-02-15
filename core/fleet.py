"""Fleet management — load, save, and remove fleet drones.

Fleet drones are stored as individual JSON files in the fleet/ directory.
Components can be database IDs (strings) or inline custom component dicts
with ``_custom: true``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.layouts import get_motor_count
from core.loader import (
    COMPONENTS_DIR,
    PROJECT_ROOT,
    _flatten_component,
    load_all_components_by_id,
)
from core.models import Build, Component

FLEET_DIR = PROJECT_ROOT / "fleet"

# Keys that are metadata, not component references.
_METADATA_KEYS = frozenset({
    "name",
    "drone_class",
    "status",
    "nickname",
    "notes",
    "acquired_date",
    "tags",
    "component_status",
})


def _resolve_component(value: Any, all_comps: dict[str, Component]) -> Component | None:
    """Resolve a single component value — either a DB ID string or a custom inline dict."""
    if isinstance(value, str):
        return all_comps.get(value)
    if isinstance(value, dict) and value.get("_custom"):
        comp_type = value.get("component_type", "unknown")
        raw = {
            "id": value.get("id", "custom_unknown"),
            "manufacturer": value.get("manufacturer", ""),
            "model": value.get("model", ""),
            "weight_g": value.get("weight_g", 0.0),
            "price_usd": value.get("price_usd", 0.0),
            "category": value.get("category", "custom"),
            "specs": value.get("specs", {}),
        }
        return _flatten_component(raw, comp_type)
    return None


def _resolve_list(value: Any, all_comps: dict[str, Component]) -> list[Component]:
    """Resolve a value that may be a single item or a list of items."""
    if isinstance(value, list):
        resolved = []
        for item in value:
            comp = _resolve_component(item, all_comps)
            if comp:
                resolved.append(comp)
        return resolved
    comp = _resolve_component(value, all_comps)
    return [comp] if comp else []


def load_fleet_drone(data: dict[str, Any], source_file: str = "") -> Build:
    """Create a Build from a fleet drone JSON dict.

    Handles both ID-string references and inline custom components.
    """
    all_comps = load_all_components_by_id()
    drone_class = data.get("drone_class", "unknown")
    motor_count = get_motor_count(drone_class)
    build_components: dict[str, Component | list[Component]] = {}

    for key, value in data.items():
        if key in _METADATA_KEYS:
            continue

        if key == "motor":
            resolved = _resolve_list(value, all_comps)
            if resolved:
                if len(resolved) == 1:
                    # Single motor ID → replicate to motor_count
                    build_components["motor"] = resolved * motor_count
                else:
                    build_components["motor"] = resolved
        elif key == "servo":
            resolved = _resolve_list(value, all_comps)
            if resolved:
                build_components["servo"] = resolved
        else:
            comp = _resolve_component(value, all_comps)
            if comp:
                build_components[key] = comp

    return Build(
        name=data.get("name", "Unnamed Drone"),
        drone_class=drone_class,
        components=build_components,
        status=data.get("status", "active"),
        nickname=data.get("nickname", ""),
        notes=data.get("notes", ""),
        tags=data.get("tags", []),
        acquired_date=data.get("acquired_date", ""),
        component_status=data.get("component_status", {}),
        source_file=source_file,
    )


def load_fleet() -> list[Build]:
    """Load all fleet drones from fleet/*.json files."""
    if not FLEET_DIR.exists():
        return []

    drones: list[Build] = []
    for filepath in sorted(FLEET_DIR.glob("*.json")):
        try:
            with open(filepath) as f:
                data = json.load(f)
            drone = load_fleet_drone(data, source_file=str(filepath))
            drones.append(drone)
        except (json.JSONDecodeError, KeyError, TypeError):
            # Skip malformed files silently
            continue
    return drones


def save_fleet_drone(drone_data: dict[str, Any], filename: str) -> Path:
    """Save a fleet drone dict as JSON to fleet/<filename>.

    Returns the path to the saved file.
    """
    FLEET_DIR.mkdir(parents=True, exist_ok=True)
    if not filename.endswith(".json"):
        filename += ".json"
    filepath = FLEET_DIR / filename
    with open(filepath, "w") as f:
        json.dump(drone_data, f, indent=2)
        f.write("\n")
    return filepath


def remove_fleet_drone(filename: str) -> bool:
    """Delete a fleet drone JSON file. Returns True if deleted, False if not found."""
    if not filename.endswith(".json"):
        filename += ".json"
    filepath = FLEET_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return True
    return False
