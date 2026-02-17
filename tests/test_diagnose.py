"""Tests for engines/diagnose.py — diagnostic orchestrator and config diff."""

from __future__ import annotations

import pytest

from core.models import Build, Component, Discrepancy, Severity, ValidationResult
from engines.diagnose import (
    DiagnosticReport,
    assign_confidence_scores,
    compute_confidence,
    diff_configs,
    run_diagnostics,
    run_quick_health_check,
)
from fc_serial.models import FCConfig, SerialPortConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_component(comp_type: str, specs: dict | None = None, **kwargs) -> Component:
    defaults = {
        "id": f"test_{comp_type}",
        "component_type": comp_type,
        "manufacturer": "Test",
        "model": "TestModel",
        "weight_g": 10.0,
        "price_usd": 10.0,
        "category": "5inch",
        "specs": specs or {},
    }
    defaults.update(kwargs)
    return Component(**defaults)


def _make_build(**components) -> Build:
    comp_dict = {}
    for comp_type, comp in components.items():
        if comp_type == "motor" and not isinstance(comp, list):
            comp_dict["motor"] = [comp] * 4
        else:
            comp_dict[comp_type] = comp
    return Build(name="Test Drone", drone_class="5inch_freestyle", components=comp_dict)


def _make_config(
    board_name: str = "MATEKF405",
    master_settings: dict | None = None,
    features: set | None = None,
    serial_ports: list | None = None,
    resource_mappings: dict | None = None,
    firmware: str = "BTFL",
    firmware_version: str = "4.5.2",
) -> FCConfig:
    return FCConfig(
        firmware=firmware,
        firmware_version=firmware_version,
        board_name=board_name,
        master_settings=master_settings or {},
        features=features or set(),
        serial_ports=serial_ports or [],
        resource_mappings=resource_mappings or {},
    )


# ---------------------------------------------------------------------------
# diff_configs tests
# ---------------------------------------------------------------------------


class TestDiffConfigs:
    """Config diff produces human-readable change list."""

    def test_setting_changed(self):
        old = _make_config(master_settings={"motor_pwm_protocol": "DSHOT300"})
        new = _make_config(master_settings={"motor_pwm_protocol": "DSHOT600"})
        changes = diff_configs(old, new)
        assert any("motor_pwm_protocol" in c and "DSHOT300" in c and "DSHOT600" in c for c in changes)

    def test_setting_added(self):
        old = _make_config(master_settings={})
        new = _make_config(master_settings={"dshot_bidir": "ON"})
        changes = diff_configs(old, new)
        assert any("dshot_bidir" in c and "added" in c for c in changes)

    def test_setting_removed(self):
        old = _make_config(master_settings={"dshot_bidir": "ON"})
        new = _make_config(master_settings={})
        changes = diff_configs(old, new)
        assert any("dshot_bidir" in c and "removed" in c for c in changes)

    def test_feature_enabled(self):
        old = _make_config(features=set())
        new = _make_config(features={"TELEMETRY"})
        changes = diff_configs(old, new)
        assert any("TELEMETRY" in c and "enabled" in c for c in changes)

    def test_feature_disabled(self):
        old = _make_config(features={"TELEMETRY"})
        new = _make_config(features=set())
        changes = diff_configs(old, new)
        assert any("TELEMETRY" in c and "disabled" in c for c in changes)

    def test_serial_port_changed(self):
        old = _make_config(serial_ports=[
            SerialPortConfig(port_id=3, function_mask=2, functions=["GPS"]),
        ])
        new = _make_config(serial_ports=[
            SerialPortConfig(port_id=3, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ])
        changes = diff_configs(old, new)
        assert any("UART 3" in c for c in changes)

    def test_no_changes(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT600"})
        changes = diff_configs(config, config)
        assert len(changes) == 0


# ---------------------------------------------------------------------------
# DiagnosticReport tests
# ---------------------------------------------------------------------------


class TestDiagnosticReport:
    """DiagnosticReport properties and structure."""

    def test_has_critical_with_discrepancy(self):
        from core.models import Discrepancy
        report = DiagnosticReport(
            build_name="Test",
            fc_info="BTFL 4.5.2 on MATEKF405",
            discrepancies=[
                Discrepancy(
                    id="disc_001", component_type="fc", category="identity",
                    severity=Severity.CRITICAL, fleet_value="x", detected_value="y",
                    message="mismatch", fix_suggestion="fix",
                ),
            ],
        )
        assert report.has_critical_issues

    def test_no_critical_with_info_only(self):
        from core.models import Discrepancy
        report = DiagnosticReport(
            build_name="Test",
            fc_info="BTFL 4.5.2",
            discrepancies=[
                Discrepancy(
                    id="disc_007", component_type="fc", category="identity",
                    severity=Severity.INFO, fleet_value="x", detected_value="y",
                    message="name mismatch", fix_suggestion="fix",
                ),
            ],
        )
        assert not report.has_critical_issues

    def test_empty_report(self):
        report = DiagnosticReport(build_name="Test", fc_info="BTFL 4.5.2")
        assert not report.has_critical_issues
        assert len(report.all_findings_prioritized) == 0


# ---------------------------------------------------------------------------
# run_diagnostics integration
# ---------------------------------------------------------------------------


class TestRunDiagnostics:
    """Integration test for the full diagnostic pipeline."""

    def test_basic_run(self):
        config = _make_config(
            master_settings={
                "motor_pwm_protocol": "DSHOT600",
                "serialrx_provider": "CRSF",
            },
            serial_ports=[
                SerialPortConfig(port_id=1, function_mask=64, functions=["SERIAL_RX"]),
            ],
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
            esc=_make_component("esc", {"protocol": "DShot600"}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF"}),
        )

        report = run_diagnostics(config, build)

        assert report.build_name == "Test Drone"
        assert "BTFL 4.5.2" in report.fc_info
        assert "MATEKF405" in report.fc_info
        assert report.firmware_report is not None
        assert report.compatibility_report is not None

    def test_with_symptoms(self):
        config = _make_config(
            master_settings={
                "motor_pwm_protocol": "DSHOT1200",
            },
        )
        build = _make_build(
            esc=_make_component("esc", {"protocol": "DShot600", "firmware": "BLHeli_S"}),
        )

        report = run_diagnostics(config, build, symptoms=["motors_wont_spin"])
        assert report.symptoms == ["motors_wont_spin"]

        # Should have some symptom-relevant findings
        relevant = report.symptom_relevant
        relevant_ids = set()
        for item in relevant:
            if hasattr(item, "constraint_id"):
                relevant_ids.add(item.constraint_id)
            else:
                relevant_ids.add(item.id)

        # disc_004 (motor protocol) and fw_001 should be relevant to motors_wont_spin
        assert "disc_004" in relevant_ids or "fw_001" in relevant_ids

    def test_with_previous_config(self):
        old_config = _make_config(
            master_settings={"motor_pwm_protocol": "DSHOT300"},
        )
        new_config = _make_config(
            master_settings={"motor_pwm_protocol": "DSHOT600"},
        )
        build = _make_build()

        report = run_diagnostics(new_config, build, previous_config=old_config)

        assert report.config_changes is not None
        assert any("motor_pwm_protocol" in c for c in report.config_changes)

    def test_without_previous_config(self):
        config = _make_config()
        build = _make_build()
        report = run_diagnostics(config, build)
        assert report.config_changes is None

    def test_discrepancies_in_report(self):
        """FC board mismatch should appear as a discrepancy."""
        config = _make_config(board_name="IFLIGHT_BLITZ_F722")
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )

        report = run_diagnostics(config, build)
        disc_ids = {d.id for d in report.discrepancies}
        assert "disc_001" in disc_ids
        assert report.has_critical_issues

    def test_confidence_scores_populated(self):
        """run_diagnostics should populate confidence_scores on the report."""
        config = _make_config(
            board_name="IFLIGHT_BLITZ_F722",
            master_settings={
                "motor_pwm_protocol": "DSHOT1200",
                "serialrx_provider": "SBUS",
            },
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
            esc=_make_component("esc", {"protocol": "DShot600", "firmware": "BLHeli_S"}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF"}),
        )

        report = run_diagnostics(config, build)
        assert len(report.confidence_scores) > 0

        # disc_001 is CRITICAL discrepancy — should be 0.95
        if "disc_001" in report.confidence_scores:
            assert report.confidence_scores["disc_001"] == 0.95

    def test_get_confidence(self):
        """get_confidence should return score or None."""
        config = _make_config(board_name="IFLIGHT_BLITZ_F722")
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )

        report = run_diagnostics(config, build)
        # disc_001 should exist
        conf = report.get_confidence("disc_001")
        assert conf is not None
        assert 0.0 < conf <= 1.0

        # nonexistent check should return None
        assert report.get_confidence("nonexistent_check") is None


# ---------------------------------------------------------------------------
# Confidence scoring unit tests
# ---------------------------------------------------------------------------


class TestComputeConfidence:
    """Unit tests for compute_confidence function."""

    def test_critical_discrepancy(self):
        disc = Discrepancy(
            id="disc_001", component_type="fc", category="identity",
            severity=Severity.CRITICAL, fleet_value="x", detected_value="y",
            message="mismatch", fix_suggestion="fix",
        )
        assert compute_confidence(disc) == 0.95

    def test_warning_discrepancy(self):
        disc = Discrepancy(
            id="disc_004", component_type="esc", category="protocol",
            severity=Severity.WARNING, fleet_value="x", detected_value="y",
            message="mismatch", fix_suggestion="fix",
        )
        assert compute_confidence(disc) == 0.85

    def test_info_discrepancy(self):
        disc = Discrepancy(
            id="disc_007", component_type="fc", category="identity",
            severity=Severity.INFO, fleet_value="x", detected_value="y",
            message="name", fix_suggestion="fix",
        )
        assert compute_confidence(disc) == 0.70

    def test_critical_firmware_result(self):
        result = ValidationResult(
            constraint_id="fw_001", constraint_name="Motor protocol",
            severity=Severity.CRITICAL, passed=False,
            message="mismatch",
        )
        assert compute_confidence(result) == 0.90

    def test_warning_firmware_result(self):
        result = ValidationResult(
            constraint_id="fw_010", constraint_name="Battery min",
            severity=Severity.WARNING, passed=False,
            message="too low",
        )
        assert compute_confidence(result) == 0.80

    def test_info_firmware_result(self):
        result = ValidationResult(
            constraint_id="fw_013", constraint_name="Gyro filter",
            severity=Severity.INFO, passed=False,
            message="high for whoop",
        )
        assert compute_confidence(result) == 0.70

    def test_critical_electrical_result(self):
        result = ValidationResult(
            constraint_id="elec_001", constraint_name="Battery vs ESC",
            severity=Severity.CRITICAL, passed=False,
            message="over-voltage",
        )
        assert compute_confidence(result) == 0.90

    def test_skipped_result(self):
        result = ValidationResult(
            constraint_id="fw_001", constraint_name="Motor protocol",
            severity=Severity.CRITICAL, passed=True,
            message="skipped", details={"skipped": True},
        )
        assert compute_confidence(result) == 0.0

    def test_estimated_data_result(self):
        result = ValidationResult(
            constraint_id="fw_001", constraint_name="Motor protocol",
            severity=Severity.CRITICAL, passed=False,
            message="mismatch", details={"estimated": True},
        )
        assert compute_confidence(result) == 0.50

    def test_missing_spec_result(self):
        result = ValidationResult(
            constraint_id="elec_003", constraint_name="ESC current",
            severity=Severity.CRITICAL, passed=False,
            message="undersized", details={"missing_spec": True},
        )
        assert compute_confidence(result) == 0.50


# ---------------------------------------------------------------------------
# Quick health check
# ---------------------------------------------------------------------------


class TestRunQuickHealthCheck:
    """Tests for run_quick_health_check function."""

    def test_quick_check_returns_report(self):
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
            esc=_make_component("esc", {"protocol": "DShot600"}),
        )
        config = _make_config(
            master_settings={"motor_pwm_protocol": "DSHOT600"},
        )

        report = run_quick_health_check(build, fc_config=config)
        assert report.is_quick_check is True
        assert report.build_name == "Test Drone"

    def test_quick_check_without_config(self):
        """Quick check without FC config should still run compatibility checks."""
        build = _make_build(
            esc=_make_component("esc", {
                "protocol": "DShot600",
                "voltage_min_s": 3,
                "voltage_max_s": 6,
                "continuous_current_a": 50,
            }),
            battery=_make_component("battery", {"cell_count": 4}),
        )

        report = run_quick_health_check(build)
        assert report.is_quick_check is True
        assert report.firmware_report is None
        assert len(report.discrepancies) == 0

    def test_quick_check_detects_critical_discrepancy(self):
        """Quick check should detect disc_001 through disc_004."""
        config = _make_config(
            board_name="IFLIGHT_BLITZ_F722",
            master_settings={"serialrx_provider": "SBUS"},
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF"}),
        )

        report = run_quick_health_check(build, fc_config=config)
        disc_ids = {d.id for d in report.discrepancies}
        # Should include disc_001 (FC board mismatch) and disc_002 (RX mismatch)
        assert "disc_001" in disc_ids
        assert "disc_002" in disc_ids
        assert report.has_critical_issues

    def test_quick_check_filters_firmware_checks(self):
        """Quick check should only include the key firmware checks."""
        config = _make_config(
            master_settings={
                "motor_pwm_protocol": "DSHOT600",
                "serialrx_provider": "CRSF",
                "vbat_min_cell_voltage": "250",  # Too low, fw_010 should catch
            },
            serial_ports=[
                SerialPortConfig(port_id=1, function_mask=64, functions=["SERIAL_RX"]),
            ],
        )
        build = _make_build(
            esc=_make_component("esc", {"protocol": "DShot600"}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF"}),
        )

        report = run_quick_health_check(build, fc_config=config)

        # Should have firmware report with only quick-check IDs
        assert report.firmware_report is not None
        fw_ids = {r.constraint_id for r in report.firmware_report.results}
        # All firmware results should be in the quick set
        quick_fw_ids = {"fw_001", "fw_004", "fw_005", "fw_010", "fw_011"}
        assert fw_ids.issubset(quick_fw_ids)

    def test_quick_check_safe_to_fly_true(self):
        """Clean build should report safe_to_fly = True."""
        config = _make_config(
            master_settings={
                "motor_pwm_protocol": "DSHOT600",
                "serialrx_provider": "CRSF",
            },
            serial_ports=[
                SerialPortConfig(port_id=1, function_mask=64, functions=["SERIAL_RX"]),
            ],
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
            esc=_make_component("esc", {"protocol": "DShot600"}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF"}),
        )

        report = run_quick_health_check(build, fc_config=config)
        assert report.safe_to_fly is True

    def test_quick_check_safe_to_fly_false(self):
        """Build with critical mismatch should report safe_to_fly = False."""
        config = _make_config(
            board_name="IFLIGHT_BLITZ_F722",
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )

        report = run_quick_health_check(build, fc_config=config)
        assert report.safe_to_fly is False

    def test_quick_check_has_confidence_scores(self):
        """Quick check should populate confidence scores."""
        config = _make_config(
            board_name="IFLIGHT_BLITZ_F722",
        )
        build = _make_build(
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )

        report = run_quick_health_check(build, fc_config=config)
        assert len(report.confidence_scores) > 0
        # disc_001 should be in there
        assert "disc_001" in report.confidence_scores
