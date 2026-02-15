"""Data models for DroneBuilder."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Severity(enum.Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Component:
    """A single FPV component with flattened specs."""

    id: str
    component_type: str  # motor, esc, fc, frame, propeller, battery, vtx, receiver
    manufacturer: str
    model: str
    weight_g: float
    price_usd: float
    category: str  # 5inch, 3inch, whoop, etc.
    specs: dict[str, Any] = field(default_factory=dict)

    def get(self, path: str, default: Any = None) -> Any:
        """Resolve a dot-less field name from flattened specs or top-level attrs."""
        if hasattr(self, path):
            return getattr(self, path)
        return self.specs.get(path, default)


@dataclass
class Build:
    """A complete drone build — a set of components plus computed aggregates."""

    name: str
    drone_class: str  # sub250, 5inch_freestyle, 5inch_race, 7inch_lr, etc.
    components: dict[str, Component | list[Component]] = field(default_factory=dict)
    # motor is a list of 4, everything else is a single Component

    @property
    def motor(self) -> Component | None:
        motors = self.components.get("motor")
        if isinstance(motors, list) and motors:
            return motors[0]
        return motors if isinstance(motors, Component) else None

    @property
    def motors(self) -> list[Component]:
        m = self.components.get("motor", [])
        return m if isinstance(m, list) else [m]

    @property
    def motor_count(self) -> int:
        return len(self.motors)

    def get_component(self, comp_type: str) -> Component | None:
        c = self.components.get(comp_type)
        if isinstance(c, list):
            return c[0] if c else None
        return c

    @property
    def all_up_weight_g(self) -> float:
        total = 0.0
        for key, comp in self.components.items():
            if isinstance(comp, list):
                total += sum(c.weight_g for c in comp)
            else:
                total += comp.weight_g
        return total

    @property
    def dry_weight_g(self) -> float:
        """AUW minus battery."""
        battery = self.get_component("battery")
        batt_weight = battery.weight_g if battery else 0.0
        return self.all_up_weight_g - batt_weight

    @property
    def total_price_usd(self) -> float:
        total = 0.0
        for key, comp in self.components.items():
            if isinstance(comp, list):
                total += sum(c.price_usd for c in comp)
            else:
                total += comp.price_usd
        return total


@dataclass
class Constraint:
    """A single compatibility rule loaded from YAML."""

    id: str
    category: str
    name: str
    description: str
    severity: Severity
    components: list[str]
    check: dict[str, Any]
    message_template: str


@dataclass
class ValidationResult:
    """Result of evaluating one constraint against a build."""

    constraint_id: str
    constraint_name: str
    severity: Severity
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
