"""Tests for the compatibility engine."""

from __future__ import annotations

import pytest

from core.loader import load_build, load_all_components_by_id
from core.models import Build, Component, Severity, ValidationResult
from engines.compatibility import ValidationReport, validate_build, check_pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_good_5inch_build() -> Build:
    """Assemble a known-good 5-inch freestyle build from real component IDs."""
    return load_build(
        {
            "name": "Good 5-inch Freestyle",
            "drone_class": "5inch_freestyle",
            "motor": "motor_tmotor_velox_v2_2306_1950kv",
            "esc": "esc_speedybee_bls_50a_4in1",
            "fc": "fc_speedybee_f405_v4",
            "frame": "frame_impulserc_apex_5",
            "battery": "battery_cnhl_ministar_1300_6s_100c",
            "propeller": "prop_gemfan_51466_hurricane",
            "vtx": "vtx_dji_o3_air_unit",
            "receiver": "rx_betafpv_elrs_lite_2_4ghz",
        }
    )


def _get_component(component_id: str) -> Component:
    """Look up a single component by ID from the database."""
    by_id = load_all_components_by_id()
    comp = by_id.get(component_id)
    assert comp is not None, f"Component {component_id!r} not found in database"
    return comp


# ---------------------------------------------------------------------------
# Test: known-good 5-inch build passes all critical checks
# ---------------------------------------------------------------------------

class TestGoodBuild:
    """A standard, well-matched 5-inch freestyle build should have zero
    critical failures in electrical, mechanical, and protocol categories.

    Note: The sub-250g weight constraint (wt_001) fires as critical for
    any build over 250g.  This is by design -- it is a regulatory weight
    class check, not a component-compatibility check.  A 5-inch freestyle
    build at ~550g AUW will always trip wt_001.  The tests below verify
    that the *only* critical failure is this weight-class constraint, and
    that all electrical / mechanical / protocol checks pass.
    """

    # Constraints that are weight-class checks rather than component-
    # compatibility checks.  A 5-inch build is expected to exceed the
    # sub-250g threshold.
    _WEIGHT_CLASS_IDS = {"wt_001"}

    def test_no_electrical_critical_failures(self):
        build = _make_good_5inch_build()
        report = validate_build(build)

        elec_criticals = [
            r for r in report.critical_failures
            if r.constraint_id.startswith("elec_")
        ]
        assert elec_criticals == [], (
            "Expected no electrical critical failures, got:\n"
            + "\n".join(f"  {r.constraint_id}: {r.message}" for r in elec_criticals)
        )

    def test_no_mechanical_critical_failures(self):
        build = _make_good_5inch_build()
        report = validate_build(build)

        mech_criticals = [
            r for r in report.critical_failures
            if r.constraint_id.startswith("mech_")
        ]
        assert mech_criticals == [], (
            "Expected no mechanical critical failures, got:\n"
            + "\n".join(f"  {r.constraint_id}: {r.message}" for r in mech_criticals)
        )

    def test_no_protocol_critical_failures(self):
        build = _make_good_5inch_build()
        report = validate_build(build)

        proto_criticals = [
            r for r in report.critical_failures
            if r.constraint_id.startswith("proto_")
        ]
        assert proto_criticals == [], (
            "Expected no protocol critical failures, got:\n"
            + "\n".join(f"  {r.constraint_id}: {r.message}" for r in proto_criticals)
        )

    def test_only_weight_class_critical_failure(self):
        """The only critical failure for a well-matched 5-inch build should
        be the sub-250g weight class check (wt_001)."""
        build = _make_good_5inch_build()
        report = validate_build(build)

        non_weight_class_criticals = [
            r for r in report.critical_failures
            if r.constraint_id not in self._WEIGHT_CLASS_IDS
        ]
        assert non_weight_class_criticals == [], (
            "Expected only weight-class critical failures, but also got:\n"
            + "\n".join(
                f"  {r.constraint_id}: {r.message}"
                for r in non_weight_class_criticals
            )
        )

    def test_results_are_not_empty(self):
        """The engine should actually run constraints, not return an empty
        list."""
        build = _make_good_5inch_build()
        report = validate_build(build)

        assert len(report.results) > 0

    def test_summary_contains_build_name(self):
        build = _make_good_5inch_build()
        report = validate_build(build)
        summary = report.summary()

        assert isinstance(summary, str)
        assert "Good 5-inch Freestyle" in summary


# ---------------------------------------------------------------------------
# Test: 6S battery with 4S-max ESC fails electrical check
# ---------------------------------------------------------------------------

class TestElectricalMismatch:
    """A 6S battery paired with a 4S-max ESC must trigger a critical
    electrical failure (constraint elec_002)."""

    def test_6s_battery_4s_esc_fails(self):
        build = load_build(
            {
                "name": "Bad Electrical Build",
                "drone_class": "5inch_freestyle",
                "motor": "motor_tmotor_velox_v2_2306_1950kv",
                "esc": "esc_speedybee_bls_25a_4in1_20x20",  # 2S-4S max
                "fc": "fc_speedybee_f405_v4",
                "frame": "frame_impulserc_apex_5",
                "battery": "battery_cnhl_ministar_1300_6s_100c",  # 6S
                "propeller": "prop_gemfan_51466_hurricane",
                "vtx": "vtx_dji_o3_air_unit",
                "receiver": "rx_betafpv_elrs_lite_2_4ghz",
            }
        )
        report = validate_build(build)

        assert report.passed is False
        assert len(report.critical_failures) > 0

        # At least one critical failure should be elec_002 (battery exceeds
        # ESC max voltage).
        elec_002_failures = [
            r for r in report.critical_failures
            if r.constraint_id == "elec_002"
        ]
        assert len(elec_002_failures) == 1, (
            "Expected elec_002 (Battery voltage within ESC maximum S-rating) "
            "to fail critically."
        )

    def test_6s_battery_4s_esc_failure_message(self):
        build = load_build(
            {
                "name": "Bad Electrical Build",
                "drone_class": "5inch_freestyle",
                "motor": "motor_tmotor_velox_v2_2306_1950kv",
                "esc": "esc_speedybee_bls_25a_4in1_20x20",  # 2S-4S max
                "fc": "fc_speedybee_f405_v4",
                "frame": "frame_impulserc_apex_5",
                "battery": "battery_cnhl_ministar_1300_6s_100c",  # 6S
                "propeller": "prop_gemfan_51466_hurricane",
            }
        )
        report = validate_build(build)
        elec_002 = [
            r for r in report.critical_failures
            if r.constraint_id == "elec_002"
        ]
        assert len(elec_002) == 1
        # The message should mention both the battery S-count and the ESC limit.
        msg = elec_002[0].message
        assert "6" in msg
        assert "4" in msg

    def test_summary_shows_failed(self):
        build = load_build(
            {
                "name": "Bad Electrical Build",
                "drone_class": "5inch_freestyle",
                "motor": "motor_emax_eco2_2306_1900kv",
                "esc": "esc_speedybee_bls_25a_4in1_20x20",
                "fc": "fc_speedybee_f405_v4",
                "frame": "frame_tbs_source_one_v5",
                "battery": "battery_cnhl_ministar_1300_6s_100c",
                "propeller": "prop_gemfan_51466_hurricane",
            }
        )
        report = validate_build(build)
        summary = report.summary()

        assert "FAILED" in summary
        assert "critical" in summary.lower()


# ---------------------------------------------------------------------------
# Test: mismatched mounting patterns fail mechanical check
# ---------------------------------------------------------------------------

class TestMechanicalMismatch:
    """Components with incompatible mounting patterns must trigger mechanical
    constraint failures.

    Since some mechanical constraints reference fields not present in the
    component database (e.g. ``frame.stack_mounting_patterns_mm``), we
    construct components with the required fields to exercise the engine.
    """

    def _make_fc(self, mounting: str = "20x20") -> Component:
        return Component(
            id="test_fc_20x20",
            component_type="fc",
            manufacturer="Test",
            model="Test FC 20x20",
            weight_g=5.0,
            price_usd=30.0,
            category="3inch",
            specs={
                "mounting_pattern_mm": mounting,
                "voltage_min_s": 3,
                "voltage_max_s": 6,
            },
        )

    def _make_frame(self, stack_patterns: list[str] | None = None) -> Component:
        return Component(
            id="test_frame_30x30",
            component_type="frame",
            manufacturer="Test",
            model="Test Frame 30.5",
            weight_g=110.0,
            price_usd=50.0,
            category="5inch",
            specs={
                "fc_mounting_pattern_mm": "30.5x30.5",
                "stack_mounting_patterns_mm": stack_patterns or ["30.5x30.5"],
                "prop_size_max_inches": 5.1,
            },
        )

    def test_fc_mounting_mismatch_detected(self):
        """A 20x20 FC should fail mech_001 against a frame that only
        supports 30.5x30.5 stack mounting."""
        fc = self._make_fc("20x20")
        frame = self._make_frame(["30.5x30.5"])

        build = Build(
            name="Mounting Mismatch Build",
            drone_class="5inch_freestyle",
            components={"fc": fc, "frame": frame},
        )

        report = validate_build(build)
        mech_001_failures = [
            r for r in report.critical_failures
            if r.constraint_id == "mech_001"
        ]
        assert len(mech_001_failures) == 1, (
            "Expected mech_001 (FC mounting pattern matches frame stack) "
            "to fail critically."
        )

    def test_fc_mounting_match_passes(self):
        """A 30.5x30.5 FC should pass mech_001 against a 30.5x30.5 frame."""
        fc = self._make_fc("30.5x30.5")
        frame = self._make_frame(["30.5x30.5", "20x20"])

        build = Build(
            name="Mounting Match Build",
            drone_class="5inch_freestyle",
            components={"fc": fc, "frame": frame},
        )

        report = validate_build(build)
        mech_001_results = [
            r for r in report.results
            if r.constraint_id == "mech_001"
        ]
        assert len(mech_001_results) == 1
        assert mech_001_results[0].passed is True

    def test_esc_mounting_mismatch_via_check_pair(self):
        """A 20x20 ESC paired with a 30.5x30.5-only frame should fail
        mech_003 when checked as a pair."""
        esc = Component(
            id="test_esc_20x20",
            component_type="esc",
            manufacturer="Test",
            model="Test ESC 20x20",
            weight_g=5.0,
            price_usd=20.0,
            category="3inch",
            specs={
                "mounting_pattern_mm": "20x20",
                "voltage_min_s": 2,
                "voltage_max_s": 4,
                "continuous_current_a": 25,
                "burst_current_a": 35,
            },
        )
        frame = self._make_frame(["30.5x30.5"])

        results = check_pair(esc, frame)
        mech_003_results = [
            r for r in results
            if r.constraint_id == "mech_003"
        ]
        assert len(mech_003_results) == 1
        assert mech_003_results[0].passed is False
        assert mech_003_results[0].severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# Test: pair-checking function
# ---------------------------------------------------------------------------

class TestCheckPair:
    """Tests for the check_pair function using real components."""

    def test_compatible_motor_esc_pair(self):
        """A motor and ESC that are well-matched should produce no critical
        failures in pair-checking."""
        motor = _get_component("motor_tmotor_velox_v2_2306_1950kv")
        esc = _get_component("esc_speedybee_bls_50a_4in1")

        results = check_pair(motor, esc)

        assert isinstance(results, list)
        assert len(results) > 0  # At least some constraints should evaluate.

        critical_failures = [
            r for r in results
            if r.severity == Severity.CRITICAL and not r.passed
        ]
        assert critical_failures == [], (
            f"Expected no critical failures for a compatible motor/ESC pair, got:\n"
            + "\n".join(f"  {r.constraint_id}: {r.message}" for r in critical_failures)
        )

    def test_pair_returns_only_relevant_constraints(self):
        """check_pair should only run constraints whose required components
        are present in the pair. A motor+ESC pair should NOT run battery
        constraints."""
        motor = _get_component("motor_emax_eco2_2306_1900kv")
        esc = _get_component("esc_speedybee_bls_60a_4in1")

        results = check_pair(motor, esc)

        for r in results:
            # These constraints require battery; they should not appear.
            assert r.constraint_id not in ("elec_001", "elec_002", "elec_005"), (
                f"Constraint {r.constraint_id} should not run for a motor+ESC pair "
                f"(it requires a battery component)."
            )

    def test_incompatible_battery_esc_pair(self):
        """A 6S battery with a 4S-max ESC should fail when checked as a
        pair."""
        battery = _get_component("battery_cnhl_ministar_1300_6s_100c")
        esc = _get_component("esc_speedybee_bls_25a_4in1_20x20")  # 2S-4S

        results = check_pair(battery, esc)

        elec_002_results = [
            r for r in results
            if r.constraint_id == "elec_002"
        ]
        assert len(elec_002_results) == 1
        assert elec_002_results[0].passed is False
        assert elec_002_results[0].severity == Severity.CRITICAL

    def test_compatible_battery_esc_pair(self):
        """A 6S battery with a 6S ESC should pass voltage constraints."""
        battery = _get_component("battery_cnhl_ministar_1300_6s_100c")
        esc = _get_component("esc_speedybee_bls_50a_4in1")  # 3S-6S

        results = check_pair(battery, esc)

        voltage_failures = [
            r for r in results
            if r.constraint_id in ("elec_001", "elec_002") and not r.passed
        ]
        assert voltage_failures == [], (
            "6S battery with a 3S-6S ESC should pass all voltage constraints."
        )

    def test_pair_check_returns_validation_results(self):
        """Each item returned by check_pair should be a ValidationResult."""
        motor = _get_component("motor_tmotor_velox_v2_2306_1950kv")
        esc = _get_component("esc_speedybee_bls_50a_4in1")

        results = check_pair(motor, esc)

        for r in results:
            assert isinstance(r, ValidationResult)
            assert isinstance(r.severity, Severity)
            assert isinstance(r.passed, bool)
            assert isinstance(r.message, str)

    def test_pair_check_empty_when_no_constraints_apply(self):
        """Two components that share no constraints should produce an empty
        result list (e.g., receiver + propeller have no shared constraints)."""
        receiver = _get_component("rx_betafpv_elrs_lite_2_4ghz")
        propeller = _get_component("prop_gemfan_51466_hurricane")

        results = check_pair(receiver, propeller)

        # No constraint requires both receiver and propeller without other
        # components, so the result should be empty.
        assert results == []


# ---------------------------------------------------------------------------
# Test: ValidationReport dataclass behavior
# ---------------------------------------------------------------------------

class TestValidationReport:
    """Unit tests for the ValidationReport dataclass properties."""

    def _make_result(
        self,
        severity: Severity,
        passed: bool,
        cid: str = "test_001",
    ) -> ValidationResult:
        return ValidationResult(
            constraint_id=cid,
            constraint_name=f"Test {cid}",
            severity=severity,
            passed=passed,
            message=f"Test message for {cid}",
        )

    def test_passed_when_no_critical_failures(self):
        report = ValidationReport(
            build_name="Test",
            results=[
                self._make_result(Severity.CRITICAL, True, "c1"),
                self._make_result(Severity.WARNING, False, "w1"),
                self._make_result(Severity.INFO, False, "i1"),
            ],
        )
        assert report.passed is True

    def test_failed_when_critical_failure_exists(self):
        report = ValidationReport(
            build_name="Test",
            results=[
                self._make_result(Severity.CRITICAL, False, "c1"),
                self._make_result(Severity.WARNING, True, "w1"),
            ],
        )
        assert report.passed is False

    def test_critical_failures_property(self):
        report = ValidationReport(
            build_name="Test",
            results=[
                self._make_result(Severity.CRITICAL, False, "c1"),
                self._make_result(Severity.CRITICAL, True, "c2"),
                self._make_result(Severity.WARNING, False, "w1"),
            ],
        )
        assert len(report.critical_failures) == 1
        assert report.critical_failures[0].constraint_id == "c1"

    def test_warnings_property(self):
        report = ValidationReport(
            build_name="Test",
            results=[
                self._make_result(Severity.CRITICAL, True, "c1"),
                self._make_result(Severity.WARNING, False, "w1"),
                self._make_result(Severity.WARNING, False, "w2"),
                self._make_result(Severity.WARNING, True, "w3"),
            ],
        )
        assert len(report.warnings) == 2

    def test_info_property(self):
        report = ValidationReport(
            build_name="Test",
            results=[
                self._make_result(Severity.INFO, False, "i1"),
                self._make_result(Severity.INFO, True, "i2"),
            ],
        )
        assert len(report.info) == 1

    def test_summary_returns_string(self):
        report = ValidationReport(
            build_name="Summary Test",
            results=[
                self._make_result(Severity.CRITICAL, True, "c1"),
            ],
        )
        summary = report.summary()
        assert isinstance(summary, str)
        assert "Summary Test" in summary
