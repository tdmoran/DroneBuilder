"""Load and normalize component databases, constraints, and builds."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from core.models import Build, Component, Constraint, Severity

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPONENTS_DIR = PROJECT_ROOT / "components"
CONSTRAINTS_DIR = PROJECT_ROOT / "constraints"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"

# Map JSON filenames to component types
_FILE_TO_TYPE = {
    "motors.json": "motor",
    "escs.json": "esc",
    "flight_controllers.json": "fc",
    "frames.json": "frame",
    "propellers.json": "propeller",
    "batteries.json": "battery",
    "vtx.json": "vtx",
    "receivers.json": "receiver",
}


def _parse_voltage_range(value: str) -> tuple[int, int]:
    """Parse voltage strings like '3S-6S' or '1S' into (min_cells, max_cells)."""
    value = value.strip().upper()
    m = re.match(r"(\d+)S(?:\s*-\s*(\d+)S)?", value)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        return lo, hi
    raise ValueError(f"Cannot parse voltage range: {value!r}")


def _parse_mounting_pattern(value: str) -> str:
    """Normalize mounting patterns like '30.5x30.5' or numeric 16 -> '16x16'."""
    if isinstance(value, (int, float)):
        v = int(value)
        return f"{v}x{v}"
    return str(value).strip()


def _flatten_component(raw: dict[str, Any], component_type: str) -> Component:
    """Flatten a raw JSON component entry into a Component with normalized specs."""
    specs = dict(raw.get("specs", {}))

    # Parse voltage ranges into numeric min/max
    for key in ("voltage_range", "voltage_input"):
        if key in specs and isinstance(specs[key], str):
            try:
                lo, hi = _parse_voltage_range(specs[key])
                specs["voltage_min_s"] = lo
                specs["voltage_max_s"] = hi
            except ValueError:
                pass

    # Normalize mounting patterns
    for key in ("mounting_pattern_mm", "fc_mounting_pattern_mm", "secondary_mounting_mm"):
        if key in specs:
            specs[key] = _parse_mounting_pattern(specs[key])

    # Parse BEC ratings like "2.5A" -> 2500 mA
    for key in ("bec_5v", "bec_9v"):
        if key in specs and isinstance(specs[key], str):
            m = re.match(r"([\d.]+)\s*A", specs[key], re.IGNORECASE)
            if m:
                specs[f"{key}_current_ma"] = int(float(m.group(1)) * 1000)

    return Component(
        id=raw["id"],
        component_type=component_type,
        manufacturer=raw.get("manufacturer", ""),
        model=raw.get("model", ""),
        weight_g=raw.get("weight_g", 0.0),
        price_usd=raw.get("price_usd", 0.0),
        category=raw.get("category", ""),
        specs=specs,
    )


def load_components(
    component_type: str | None = None,
) -> dict[str, list[Component]]:
    """Load component databases. Returns {type: [Component, ...]}."""
    result: dict[str, list[Component]] = {}
    for filename, ctype in _FILE_TO_TYPE.items():
        if component_type and ctype != component_type:
            continue
        filepath = COMPONENTS_DIR / filename
        if not filepath.exists():
            continue
        with open(filepath) as f:
            raw_list = json.load(f)
        result[ctype] = [_flatten_component(r, ctype) for r in raw_list]
    return result


def load_all_components_by_id() -> dict[str, Component]:
    """Load all components indexed by their id."""
    all_comps = load_components()
    by_id: dict[str, Component] = {}
    for comp_list in all_comps.values():
        for comp in comp_list:
            by_id[comp.id] = comp
    return by_id


def load_constraints(category: str | None = None) -> list[Constraint]:
    """Load constraint rules from YAML files."""
    constraints: list[Constraint] = []
    for filepath in CONSTRAINTS_DIR.glob("*.yaml"):
        if filepath.name == "constraint-schema.yaml":
            continue
        with open(filepath) as f:
            data = yaml.safe_load(f)
        if not data or "rules" not in data:
            continue
        file_category = data.get("category", "")
        if category and file_category != category:
            continue
        for rule in data["rules"]:
            constraints.append(
                Constraint(
                    id=rule["id"],
                    category=rule.get("category", file_category),
                    name=rule["name"],
                    description=rule.get("description", ""),
                    severity=Severity(rule.get("severity", "info")),
                    components=rule.get("components", []),
                    check=rule.get("check", {}),
                    message_template=rule.get("message_template", ""),
                )
            )
    return constraints


def load_build(build_data: dict[str, Any]) -> Build:
    """Create a Build from a dict of component IDs.

    Expected format:
    {
        "name": "My 5inch Build",
        "drone_class": "5inch_freestyle",
        "motor": "motor_tmotor_velox_v2_2306_1950kv",  # or list of 4 IDs
        "esc": "esc_speedybee_bls_50a_4in1",
        "fc": "fc_speedybee_f405_v4",
        ...
    }
    """
    all_comps = load_all_components_by_id()
    build_components: dict[str, Component | list[Component]] = {}

    for key, value in build_data.items():
        if key in ("name", "drone_class", "notes"):
            continue
        if key == "motor":
            if isinstance(value, str):
                comp = all_comps.get(value)
                if comp:
                    build_components["motor"] = [comp] * 4
            elif isinstance(value, list):
                motors = [all_comps[mid] for mid in value if mid in all_comps]
                build_components["motor"] = motors
        else:
            if isinstance(value, str) and value in all_comps:
                build_components[key] = all_comps[value]

    return Build(
        name=build_data.get("name", "Unnamed Build"),
        drone_class=build_data.get("drone_class", "unknown"),
        components=build_components,
    )
