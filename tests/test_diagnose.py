"""Tests for engines/diagnose.py — diagnostic orchestrator and config diff."""

from __future__ import annotations

import pytest

from core.models import Build, Component, Severity
from engines.diagnose import DiagnosticReport, diff_configs, run_diagnostics
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
