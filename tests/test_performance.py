"""Tests for the performance calculator engine."""

from __future__ import annotations

import math

import pytest

from core.loader import load_build
from engines.performance import calculate_performance, PerformanceReport


# ---------------------------------------------------------------------------
# Fixture: standard 5-inch 6S freestyle build
# ---------------------------------------------------------------------------

BUILD_5INCH_6S = {
    "name": "Standard 5-inch 6S Freestyle",
    "drone_class": "5inch_freestyle",
    "motor": "motor_tmotor_velox_v2_2306_1950kv",
    "battery": "battery_cnhl_ministar_1300_6s_100c",
    "propeller": "prop_gemfan_51466_hurricane",
    "frame": "frame_impulserc_apex_5",
    "esc": "esc_speedybee_bls_50a_4in1",
    "fc": "fc_speedybee_f405_v4",
}


@pytest.fixture
def build_5inch():
    """Load a standard 5-inch 6S build from the component database."""
    return load_build(BUILD_5INCH_6S)


@pytest.fixture
def report_5inch(build_5inch):
    """Compute performance for the standard 5-inch build."""
    return calculate_performance(build_5inch)


# ---------------------------------------------------------------------------
# Test: Thrust-to-weight ratio for a standard 5" 6S build (4:1 – 12:1)
# ---------------------------------------------------------------------------

class TestThrustToWeightRatio:
    def test_twr_in_range(self, report_5inch: PerformanceReport):
        """A standard 5-inch 6S build should have a TWR between 4:1 and 12:1."""
        assert 4.0 <= report_5inch.thrust_to_weight_ratio <= 12.0, (
            f"TWR {report_5inch.thrust_to_weight_ratio:.2f} is outside the "
            f"expected 4:1 - 12:1 range for a 5-inch 6S build"
        )

    def test_twr_positive(self, report_5inch: PerformanceReport):
        """TWR must always be a positive number."""
        assert report_5inch.thrust_to_weight_ratio > 0

    def test_total_thrust_greater_than_auw(self, build_5inch, report_5inch):
        """Total thrust must exceed all-up weight for the drone to fly."""
        assert report_5inch.total_thrust_g > build_5inch.all_up_weight_g


# ---------------------------------------------------------------------------
# Test: Hover throttle (10–30% for a typical build)
# ---------------------------------------------------------------------------

class TestHoverThrottle:
    def test_hover_throttle_range(self, report_5inch: PerformanceReport):
        """Hover throttle should be 10-30% for a high-performance 5-inch quad."""
        assert 10.0 <= report_5inch.hover_throttle_pct <= 30.0, (
            f"Hover throttle {report_5inch.hover_throttle_pct:.1f}% is outside "
            f"the expected 10-30% range"
        )

    def test_hover_throttle_consistent_with_twr(self, report_5inch: PerformanceReport):
        """hover_throttle_pct should equal sqrt(1/TWR) * 100."""
        expected = math.sqrt(1.0 / report_5inch.thrust_to_weight_ratio) * 100.0
        assert abs(report_5inch.hover_throttle_pct - expected) < 0.01


# ---------------------------------------------------------------------------
# Test: Flight time (2–8 minutes for 1300mAh 6S)
# ---------------------------------------------------------------------------

class TestFlightTime:
    def test_hover_flight_time_range(self, report_5inch: PerformanceReport):
        """A 1300mAh 6S build should hover for roughly 2-8 minutes."""
        assert 2.0 <= report_5inch.estimated_flight_time_min <= 8.0, (
            f"Hover flight time {report_5inch.estimated_flight_time_min:.1f} min "
            f"is outside the expected 2-8 minute range"
        )

    def test_cruise_time_less_than_hover(self, report_5inch: PerformanceReport):
        """Cruise time at higher speed should be less than hover time."""
        assert report_5inch.estimated_cruise_time_min < report_5inch.estimated_flight_time_min

    def test_cruise_time_positive(self, report_5inch: PerformanceReport):
        """Cruise time must be positive."""
        assert report_5inch.estimated_cruise_time_min > 0

    def test_battery_energy_calculation(self, report_5inch: PerformanceReport):
        """Battery energy = capacity_mah * voltage_nominal / 1000."""
        expected_wh = 1300 * 22.2 / 1000.0  # 28.86 Wh
        assert abs(report_5inch.battery_energy_wh - expected_wh) < 0.01


# ---------------------------------------------------------------------------
# Test: Prop tip speed calculation
# ---------------------------------------------------------------------------

class TestPropTipSpeed:
    def test_prop_tip_speed_calculation(self, report_5inch: PerformanceReport):
        """Verify prop tip speed is calculated correctly from first principles.

        Formula: RPM * prop_diameter_m * pi / 60
        where RPM = KV * cell_count * 4.2
        """
        kv = 1950
        cell_count = 6
        diameter_inches = 5.1
        max_rpm = kv * cell_count * 4.2
        prop_diameter_m = diameter_inches * 0.0254
        expected_tip_speed = max_rpm * prop_diameter_m * math.pi / 60.0
        assert abs(report_5inch.prop_tip_speed_ms - expected_tip_speed) < 0.01, (
            f"Prop tip speed {report_5inch.prop_tip_speed_ms:.2f} m/s does not "
            f"match expected {expected_tip_speed:.2f} m/s"
        )

    def test_prop_tip_speed_positive(self, report_5inch: PerformanceReport):
        """Prop tip speed must be a positive number."""
        assert report_5inch.prop_tip_speed_ms > 0

    def test_prop_tip_speed_subsonic(self, report_5inch: PerformanceReport):
        """Prop tip speed should be well below the speed of sound (343 m/s)."""
        assert report_5inch.prop_tip_speed_ms < 343.0


# ---------------------------------------------------------------------------
# Test: Power and current sanity
# ---------------------------------------------------------------------------

class TestPowerAndCurrent:
    def test_hover_power_less_than_max(self, report_5inch: PerformanceReport):
        """Hover power must be less than max power."""
        assert report_5inch.hover_power_w < report_5inch.max_power_w

    def test_hover_current_less_than_max(self, report_5inch: PerformanceReport):
        """Hover current must be less than max current draw."""
        assert report_5inch.hover_current_a < report_5inch.max_current_draw_a

    def test_max_current_is_4_motors(self, report_5inch: PerformanceReport):
        """Max current should be 4 * per-motor max current (36A for this motor)."""
        expected = 36.0 * 4
        assert abs(report_5inch.max_current_draw_a - expected) < 0.01

    def test_efficiency_positive(self, report_5inch: PerformanceReport):
        """Efficiency metric must be positive."""
        assert report_5inch.efficiency_grams_per_watt > 0


# ---------------------------------------------------------------------------
# Test: Max speed estimate
# ---------------------------------------------------------------------------

class TestMaxSpeed:
    def test_max_speed_reasonable(self, report_5inch: PerformanceReport):
        """Max speed for a 5-inch 6S quad should be in a reasonable range."""
        # Typical 5-inch freestyle quads can do 120-250+ km/h theoretical
        assert 50 < report_5inch.max_speed_estimate_kmh < 400

    def test_max_speed_calculation(self, report_5inch: PerformanceReport):
        """Verify max speed estimate from first principles."""
        kv = 1950
        cell_count = 6
        pitch_inches = 4.66
        max_rpm = kv * cell_count * 4.2
        pitch_m = pitch_inches * 0.0254
        expected = pitch_m * max_rpm * 60.0 / 1000.0 * 0.5
        assert abs(report_5inch.max_speed_estimate_kmh - expected) < 0.1


# ---------------------------------------------------------------------------
# Test: summary() output
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_returns_string(self, report_5inch: PerformanceReport):
        """summary() should return a non-empty string."""
        s = report_5inch.summary()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_summary_contains_key_metrics(self, report_5inch: PerformanceReport):
        """summary() should mention key metric labels."""
        s = report_5inch.summary()
        assert "Thrust-to-weight" in s
        assert "Hover throttle" in s
        assert "Flight time" in s
        assert "Prop tip speed" in s


# ---------------------------------------------------------------------------
# Test: missing component raises ValueError
# ---------------------------------------------------------------------------

class TestMissingComponents:
    def test_missing_motor_raises(self):
        """Build without a motor should raise ValueError."""
        build = load_build({
            "name": "No Motor Build",
            "drone_class": "5inch_freestyle",
            "battery": "battery_cnhl_ministar_1300_6s_100c",
        })
        with pytest.raises(ValueError, match="motor"):
            calculate_performance(build)

    def test_missing_battery_raises(self):
        """Build without a battery should raise ValueError."""
        build = load_build({
            "name": "No Battery Build",
            "drone_class": "5inch_freestyle",
            "motor": "motor_tmotor_velox_v2_2306_1950kv",
        })
        with pytest.raises(ValueError, match="battery"):
            calculate_performance(build)
