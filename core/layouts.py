"""Component layout definitions for different drone classes.

Each drone class maps to a layout that defines the expected component slots,
their quantities, and whether they are required.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComponentSlot:
    """A single expected component slot in a drone layout."""

    component_type: str  # motor, esc, fc, frame, airframe, propeller, battery, vtx, receiver, servo
    key: str  # dict key in Build.components (e.g., "motor", "hover_motor", "pusher_motor")
    quantity: int  # how many of this component
    required: bool  # whether the slot must be filled for a valid build


# ---------------------------------------------------------------------------
# Quad layouts — standard multirotor configurations
# ---------------------------------------------------------------------------

QUAD_LAYOUT: list[ComponentSlot] = [
    ComponentSlot("motor", "motor", 4, required=True),
    ComponentSlot("esc", "esc", 1, required=True),
    ComponentSlot("fc", "fc", 1, required=True),
    ComponentSlot("frame", "frame", 1, required=True),
    ComponentSlot("propeller", "propeller", 1, required=True),
    ComponentSlot("battery", "battery", 1, required=True),
    ComponentSlot("vtx", "vtx", 1, required=False),
    ComponentSlot("receiver", "receiver", 1, required=False),
]

# ---------------------------------------------------------------------------
# Flying wing layout — 1 pusher motor, 2 servos, wing airframe
# ---------------------------------------------------------------------------

FLYING_WING_LAYOUT: list[ComponentSlot] = [
    ComponentSlot("motor", "motor", 1, required=True),
    ComponentSlot("esc", "esc", 1, required=True),
    ComponentSlot("fc", "fc", 1, required=True),
    ComponentSlot("airframe", "airframe", 1, required=True),
    ComponentSlot("propeller", "propeller", 1, required=True),
    ComponentSlot("battery", "battery", 1, required=True),
    ComponentSlot("servo", "servo", 2, required=True),
    ComponentSlot("vtx", "vtx", 1, required=False),
    ComponentSlot("receiver", "receiver", 1, required=False),
]

# ---------------------------------------------------------------------------
# VTOL layout — 4 hover motors + 1 pusher, 2 servos, wing airframe
# ---------------------------------------------------------------------------

VTOL_LAYOUT: list[ComponentSlot] = [
    ComponentSlot("motor", "motor", 5, required=True),  # 4 hover + 1 pusher
    ComponentSlot("esc", "esc", 2, required=True),  # quad ESC + wing ESC
    ComponentSlot("fc", "fc", 1, required=True),
    ComponentSlot("airframe", "airframe", 1, required=True),
    ComponentSlot("propeller", "propeller", 2, required=True),  # hover props + pusher prop
    ComponentSlot("battery", "battery", 1, required=True),
    ComponentSlot("servo", "servo", 2, required=True),
    ComponentSlot("vtx", "vtx", 1, required=False),
    ComponentSlot("receiver", "receiver", 1, required=False),
]

# ---------------------------------------------------------------------------
# Class-to-layout mapping
# ---------------------------------------------------------------------------

CLASS_TO_LAYOUT: dict[str, list[ComponentSlot]] = {
    # Quad classes
    "5inch_freestyle": QUAD_LAYOUT,
    "5inch_race": QUAD_LAYOUT,
    "3inch": QUAD_LAYOUT,
    "whoop": QUAD_LAYOUT,
    "7inch_lr": QUAD_LAYOUT,
    "sub250": QUAD_LAYOUT,
    "5inch": QUAD_LAYOUT,
    # Fixed-wing classes
    "flying_wing": FLYING_WING_LAYOUT,
    # Hybrid classes
    "vtol": VTOL_LAYOUT,
}


def get_layout(drone_class: str) -> list[ComponentSlot]:
    """Return the component layout for a drone class.

    Falls back to QUAD_LAYOUT for unknown classes.
    """
    return CLASS_TO_LAYOUT.get(drone_class, QUAD_LAYOUT)


def get_motor_count(drone_class: str) -> int:
    """Return the expected motor count for a drone class."""
    layout = get_layout(drone_class)
    for slot in layout:
        if slot.component_type == "motor":
            return slot.quantity
    return 4  # safe default
