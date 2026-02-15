"""Performance calculator engine for DroneBuilder.

Computes thrust-to-weight ratios, flight times, power draw, and other
performance metrics from a Build object.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.models import Build


# ---------------------------------------------------------------------------
# Estimation helpers
# ---------------------------------------------------------------------------

def _estimate_max_thrust_g(motor_specs: dict, prop_specs: dict | None = None) -> float:
    """Estimate max thrust per motor from available specs.

    If ``max_thrust_g`` is already in the motor specs we use it directly.
    Otherwise we fall back to an estimation derived from ``max_power_w``
    using a realistic thrust-per-watt figure at *full throttle*.

    At full throttle, brushless motors are quite inefficient.  Typical
    real-world figures for a 2306 motor on a 5-inch triblade prop are
    around 1.5-1.8 g/W at max power.  We scale slightly for prop size
    (larger props are more efficient, more blades produce a bit more
    thrust per watt).
    """
    if "max_thrust_g" in motor_specs:
        return float(motor_specs["max_thrust_g"])

    # Fallback: estimate from max power and a prop-size efficiency factor
    max_power_w = float(motor_specs.get("max_power_w", 0))
    if max_power_w <= 0:
        # Last resort: estimate from max_current * rough voltage
        max_current = float(motor_specs.get("max_current_a", 0))
        kv = float(motor_specs.get("kv", 0))
        if kv > 5000:
            # Tiny whoop / micro -- very rough guess
            max_power_w = max_current * 4.2  # 1S
        elif kv > 2500:
            max_power_w = max_current * 14.8  # 4S
        else:
            max_power_w = max_current * 22.2  # 6S

    # Grams-per-watt at *full throttle* (NOT hover efficiency).
    # A 2306 on a 5" triblade: ~1400-1500g at ~890W -> ~1.6 g/W.
    # Larger props improve this slightly; more blades add a small boost.
    g_per_w = 1.5  # conservative baseline at max throttle
    if prop_specs:
        diameter = float(prop_specs.get("diameter_inches", 5.0))
        blades = int(prop_specs.get("blades", 3))
        # Scale: bigger diameter and more blades slightly raise g/W
        g_per_w = 1.1 + 0.07 * diameter + 0.05 * blades
    return max_power_w * g_per_w


# ---------------------------------------------------------------------------
# PerformanceReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class PerformanceReport:
    """All computed performance metrics for a drone build."""

    thrust_to_weight_ratio: float
    total_thrust_g: float
    hover_throttle_pct: float
    max_current_draw_a: float
    hover_current_a: float
    hover_power_w: float
    max_power_w: float
    estimated_flight_time_min: float
    estimated_cruise_time_min: float
    battery_energy_wh: float
    max_speed_estimate_kmh: float
    prop_tip_speed_ms: float
    efficiency_grams_per_watt: float

    def summary(self) -> str:
        """Return a human-readable multi-line summary of the report."""
        lines = [
            "=== Performance Report ===",
            "",
            f"  Thrust-to-weight ratio : {self.thrust_to_weight_ratio:.2f} : 1",
            f"  Total thrust (4 motors): {self.total_thrust_g:.0f} g",
            f"  Hover throttle         : {self.hover_throttle_pct:.1f} %",
            "",
            f"  Max current draw       : {self.max_current_draw_a:.1f} A",
            f"  Hover current          : {self.hover_current_a:.1f} A",
            f"  Max power              : {self.max_power_w:.0f} W",
            f"  Hover power            : {self.hover_power_w:.1f} W",
            "",
            f"  Battery energy         : {self.battery_energy_wh:.2f} Wh",
            f"  Flight time (hover)    : {self.estimated_flight_time_min:.1f} min",
            f"  Cruise time (~60% thr) : {self.estimated_cruise_time_min:.1f} min",
            "",
            f"  Max speed estimate     : {self.max_speed_estimate_kmh:.0f} km/h",
            f"  Prop tip speed         : {self.prop_tip_speed_ms:.0f} m/s",
            f"  Efficiency at hover    : {self.efficiency_grams_per_watt:.2f} g/W",
            "",
            "===========================",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------------

def calculate_performance(build: Build) -> PerformanceReport:
    """Compute performance metrics for a drone *build*.

    Parameters
    ----------
    build : Build
        A fully-loaded Build object with motor, battery, propeller, and
        frame components populated.

    Returns
    -------
    PerformanceReport
        Dataclass containing all calculated performance metrics.

    Raises
    ------
    ValueError
        If critical components (motor, battery) are missing from the build.
    """

    motor = build.get_component("motor")
    battery = build.get_component("battery")
    propeller = build.get_component("propeller")

    if motor is None:
        raise ValueError("Build is missing a motor component")
    if battery is None:
        raise ValueError("Build is missing a battery component")

    motor_count = build.motor_count

    # --- Motor specs ---
    kv = float(motor.specs.get("kv", 0))
    max_current_per_motor = float(motor.specs.get("max_current_a", 0))

    # --- Battery specs ---
    capacity_mah = float(battery.specs.get("capacity_mah", 0))
    cell_count = int(battery.specs.get("cell_count", 0))
    voltage_nominal = float(battery.specs.get("voltage_nominal_v", cell_count * 3.7))
    voltage_max = float(battery.specs.get("voltage_max_v", cell_count * 4.2))

    # --- Propeller specs (optional but strongly recommended) ---
    prop_specs: dict = propeller.specs if propeller else {}
    diameter_inches = float(prop_specs.get("diameter_inches", 5.0))
    pitch_inches = float(prop_specs.get("pitch_inches", 4.0))

    # --- Thrust ---
    max_thrust_per_motor = _estimate_max_thrust_g(motor.specs, prop_specs)
    total_thrust_g = max_thrust_per_motor * motor_count

    # --- Weight ---
    auw = build.all_up_weight_g
    if auw <= 0:
        auw = 1.0  # safety guard

    # --- Thrust-to-weight ratio ---
    twr = total_thrust_g / auw

    # --- Hover throttle ---
    # Thrust scales roughly with throttle^2 for brushless motors,
    # so hover_throttle = sqrt(1 / TWR)
    if twr > 0:
        hover_throttle = math.sqrt(1.0 / twr)
    else:
        hover_throttle = 1.0
    hover_throttle_pct = hover_throttle * 100.0

    # --- Current & Power ---
    max_current_draw_a = max_current_per_motor * motor_count
    hover_current_a = max_current_draw_a * (hover_throttle ** 2)
    hover_power_w = hover_current_a * voltage_nominal
    max_power_w = max_current_draw_a * voltage_nominal

    # --- Battery energy ---
    battery_energy_wh = capacity_mah * voltage_nominal / 1000.0

    # --- Flight time ---
    if hover_power_w > 0:
        estimated_flight_time_min = (battery_energy_wh / hover_power_w) * 60.0
    else:
        estimated_flight_time_min = 0.0

    # Cruise at ~60% throttle is less efficient (drag increases with speed)
    estimated_cruise_time_min = estimated_flight_time_min * 0.7

    # --- RPM & tip speed ---
    max_rpm = kv * cell_count * 4.2
    prop_diameter_m = diameter_inches * 0.0254
    prop_tip_speed_ms = max_rpm * prop_diameter_m * math.pi / 60.0

    # --- Max speed estimate ---
    # Pitch speed derated by ~50% for real-world efficiency
    pitch_m = pitch_inches * 0.0254
    max_speed_estimate_kmh = pitch_m * max_rpm * 60.0 / 1000.0 * 0.5

    # --- Efficiency at hover ---
    if hover_power_w > 0:
        efficiency_grams_per_watt = auw / hover_power_w
    else:
        efficiency_grams_per_watt = 0.0

    return PerformanceReport(
        thrust_to_weight_ratio=twr,
        total_thrust_g=total_thrust_g,
        hover_throttle_pct=hover_throttle_pct,
        max_current_draw_a=max_current_draw_a,
        hover_current_a=hover_current_a,
        hover_power_w=hover_power_w,
        max_power_w=max_power_w,
        estimated_flight_time_min=estimated_flight_time_min,
        estimated_cruise_time_min=estimated_cruise_time_min,
        battery_energy_wh=battery_energy_wh,
        max_speed_estimate_kmh=max_speed_estimate_kmh,
        prop_tip_speed_ms=prop_tip_speed_ms,
        efficiency_grams_per_watt=efficiency_grams_per_watt,
    )
