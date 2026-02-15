"""Tests for engines/firmware_validator.py — all 20 cross-validation checks."""

from __future__ import annotations

import pytest

from core.models import Build, Component, Severity
from engines.firmware_validator import validate_firmware_config
from fc_serial.models import FCConfig, SerialPortConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_component(comp_type: str, specs: dict | None = None, **kwargs) -> Component:
    """Create a minimal Component for testing."""
    defaults = {
        "id": f"test_{comp_type}",
        "component_type": comp_type,
        "manufacturer": "Test",
        "model": "Test",
        "weight_g": 10.0,
        "price_usd": 10.0,
        "category": "5inch",
        "specs": specs or {},
    }
    defaults.update(kwargs)
    return Component(**defaults)


def _make_build(**components) -> Build:
    """Create a minimal Build with given components."""
    comp_dict = {}
    for comp_type, comp in components.items():
        comp_dict[comp_type] = comp
    return Build(name="Test Build", drone_class="5inch_freestyle", components=comp_dict)


def _make_config(**settings) -> FCConfig:
    """Create a minimal FCConfig with given master settings."""
    master = settings.pop("master_settings", {})
    features = settings.pop("features", set())
    serial_ports = settings.pop("serial_ports", [])
    firmware = settings.pop("firmware", "BTFL")

    return FCConfig(
        firmware=firmware,
        firmware_version="4.5.1",
        master_settings=master,
        features=features,
        serial_ports=serial_ports,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMotorProtocol:
    """fw_001: Motor protocol match."""

    def test_matching_protocol(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT600"})
        build = _make_build(esc=_make_component("esc", {"protocol": "DShot600"}))
        report = validate_firmware_config(config, build)
        fw001 = [r for r in report.results if r.constraint_id == "fw_001"]
        assert len(fw001) == 1
        assert fw001[0].passed

    def test_mismatched_protocol(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT1200"})
        build = _make_build(esc=_make_component("esc", {"protocol": "DShot600"}))
        report = validate_firmware_config(config, build)
        fw001 = [r for r in report.results if r.constraint_id == "fw_001"]
        assert len(fw001) == 1
        assert not fw001[0].passed
        assert fw001[0].severity == Severity.CRITICAL


class TestBLHeliSDShot1200:
    """fw_002: BLHeli_S ESCs can't run DShot1200."""

    def test_blheli_s_with_dshot1200(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT1200"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_S", "protocol": "DShot600"}))
        report = validate_firmware_config(config, build)
        fw002 = [r for r in report.results if r.constraint_id == "fw_002"]
        assert len(fw002) == 1
        assert not fw002[0].passed

    def test_blheli_32_with_dshot1200(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT1200"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_32", "protocol": "DShot1200"}))
        report = validate_firmware_config(config, build)
        fw002 = [r for r in report.results if r.constraint_id == "fw_002"]
        assert len(fw002) == 0  # Check not triggered


class TestBidirDShot:
    """fw_003: Bidir DShot needs BLHeli_32 or AM32."""

    def test_bidir_with_blheli_32(self):
        config = _make_config(master_settings={"dshot_bidir": "ON"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_32"}))
        report = validate_firmware_config(config, build)
        fw003 = [r for r in report.results if r.constraint_id == "fw_003"]
        assert len(fw003) == 1
        assert fw003[0].passed

    def test_bidir_with_blheli_s(self):
        config = _make_config(master_settings={"dshot_bidir": "ON"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_S"}))
        report = validate_firmware_config(config, build)
        fw003 = [r for r in report.results if r.constraint_id == "fw_003"]
        assert len(fw003) == 1
        assert not fw003[0].passed


class TestReceiverProtocol:
    """fw_004: serialrx_provider matches receiver output protocol."""

    def test_crsf_match(self):
        config = _make_config(master_settings={"serialrx_provider": "CRSF"})
        build = _make_build(receiver=_make_component("receiver", {"output_protocol": "CRSF"}))
        report = validate_firmware_config(config, build)
        fw004 = [r for r in report.results if r.constraint_id == "fw_004"]
        assert len(fw004) == 1
        assert fw004[0].passed

    def test_protocol_mismatch(self):
        config = _make_config(master_settings={"serialrx_provider": "SBUS"})
        build = _make_build(receiver=_make_component("receiver", {"output_protocol": "CRSF"}))
        report = validate_firmware_config(config, build)
        fw004 = [r for r in report.results if r.constraint_id == "fw_004"]
        assert len(fw004) == 1
        assert not fw004[0].passed
        assert fw004[0].severity == Severity.CRITICAL


class TestReceiverUART:
    """fw_005: A serial port must have SERIAL_RX."""

    def test_serial_rx_assigned(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=64, functions=["SERIAL_RX"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(receiver=_make_component("receiver", {}))
        report = validate_firmware_config(config, build)
        fw005 = [r for r in report.results if r.constraint_id == "fw_005"]
        assert len(fw005) == 1
        assert fw005[0].passed

    def test_no_serial_rx(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=1, functions=["MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(receiver=_make_component("receiver", {}))
        report = validate_firmware_config(config, build)
        fw005 = [r for r in report.results if r.constraint_id == "fw_005"]
        assert len(fw005) == 1
        assert not fw005[0].passed


class TestSBUSInversion:
    """fw_006: SBUS on F4 boards needs software inversion."""

    def test_sbus_f405_no_inversion(self):
        config = _make_config(master_settings={"serialrx_provider": "SBUS", "serialrx_inverted": "OFF"})
        build = _make_build(
            receiver=_make_component("receiver", {"output_protocol": "SBUS"}),
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )
        report = validate_firmware_config(config, build)
        fw006 = [r for r in report.results if r.constraint_id == "fw_006"]
        assert len(fw006) == 1
        assert not fw006[0].passed

    def test_sbus_f405_with_inversion(self):
        config = _make_config(master_settings={"serialrx_provider": "SBUS", "serialrx_inverted": "ON"})
        build = _make_build(
            receiver=_make_component("receiver", {"output_protocol": "SBUS"}),
            fc=_make_component("fc", {"mcu": "STM32F405"}),
        )
        report = validate_firmware_config(config, build)
        fw006 = [r for r in report.results if r.constraint_id == "fw_006"]
        assert len(fw006) == 1
        assert fw006[0].passed


class TestVTXUART:
    """fw_007: Analog VTX needs SmartAudio/Tramp UART."""

    def test_analog_vtx_with_smartaudio(self):
        serial_ports = [
            SerialPortConfig(port_id=2, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Analog", "system": "SmartAudio"}))
        report = validate_firmware_config(config, build)
        fw007 = [r for r in report.results if r.constraint_id == "fw_007"]
        assert len(fw007) == 1
        assert fw007[0].passed

    def test_analog_vtx_no_uart(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=1, functions=["MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Analog", "system": "SmartAudio"}))
        report = validate_firmware_config(config, build)
        fw007 = [r for r in report.results if r.constraint_id == "fw_007"]
        assert len(fw007) == 1
        assert not fw007[0].passed


class TestDJIMSP:
    """fw_008: Digital VTX needs MSP DisplayPort."""

    def test_dji_with_vtx_msp(self):
        serial_ports = [
            SerialPortConfig(port_id=3, function_mask=65536, functions=["VTX_MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}))
        report = validate_firmware_config(config, build)
        fw008 = [r for r in report.results if r.constraint_id == "fw_008"]
        assert len(fw008) == 1
        assert fw008[0].passed

    def test_dji_without_msp(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=1, functions=["MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}))
        report = validate_firmware_config(config, build)
        fw008 = [r for r in report.results if r.constraint_id == "fw_008"]
        assert len(fw008) == 1
        assert not fw008[0].passed

    def test_hdzero_without_msp(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=1, functions=["MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD", "system": "HDZero"}))
        report = validate_firmware_config(config, build)
        fw008 = [r for r in report.results if r.constraint_id == "fw_008"]
        assert len(fw008) == 1
        assert not fw008[0].passed


class TestBatteryVoltage:
    """fw_010: vbat_min_cell_voltage range."""

    def test_reasonable_min_voltage(self):
        config = _make_config(master_settings={"vbat_min_cell_voltage": "330"})
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw010 = [r for r in report.results if r.constraint_id == "fw_010"]
        assert len(fw010) == 1
        assert fw010[0].passed

    def test_too_low_voltage(self):
        config = _make_config(master_settings={"vbat_min_cell_voltage": "280"})
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw010 = [r for r in report.results if r.constraint_id == "fw_010"]
        assert len(fw010) == 1
        assert not fw010[0].passed

    def test_too_high_voltage(self):
        config = _make_config(master_settings={"vbat_min_cell_voltage": "380"})
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw010 = [r for r in report.results if r.constraint_id == "fw_010"]
        assert len(fw010) == 1
        assert not fw010[0].passed


class TestPIDLoopRate:
    """fw_012: PID process denominator for DShot protocol."""

    def test_adequate_denom(self):
        config = _make_config(master_settings={"pid_process_denom": "2", "motor_pwm_protocol": "DSHOT600"})
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw012 = [r for r in report.results if r.constraint_id == "fw_012"]
        assert len(fw012) == 1
        assert fw012[0].passed

    def test_high_denom_dshot1200(self):
        config = _make_config(master_settings={"pid_process_denom": "4", "motor_pwm_protocol": "DSHOT1200"})
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw012 = [r for r in report.results if r.constraint_id == "fw_012"]
        assert len(fw012) == 1
        assert not fw012[0].passed


class TestOSDFeature:
    """fw_015: OSD feature enabled."""

    def test_osd_enabled(self):
        config = _make_config(features={"OSD"})
        build = _make_build(
            vtx=_make_component("vtx", {}),
            fc=_make_component("fc", {"osd": "AT7456E"}),
        )
        report = validate_firmware_config(config, build)
        fw015 = [r for r in report.results if r.constraint_id == "fw_015"]
        assert len(fw015) == 1
        assert fw015[0].passed

    def test_osd_disabled(self):
        config = _make_config(features=set())
        build = _make_build(
            vtx=_make_component("vtx", {}),
            fc=_make_component("fc", {"osd": "AT7456E"}),
        )
        report = validate_firmware_config(config, build)
        fw015 = [r for r in report.results if r.constraint_id == "fw_015"]
        assert len(fw015) == 1
        assert not fw015[0].passed


class TestTelemetryFeature:
    """fw_016: Telemetry feature with capable receiver."""

    def test_telemetry_enabled(self):
        config = _make_config(features={"TELEMETRY"})
        build = _make_build(receiver=_make_component("receiver", {"telemetry": True}))
        report = validate_firmware_config(config, build)
        fw016 = [r for r in report.results if r.constraint_id == "fw_016"]
        assert len(fw016) == 1
        assert fw016[0].passed

    def test_telemetry_disabled(self):
        config = _make_config(features=set())
        build = _make_build(receiver=_make_component("receiver", {"telemetry": True}))
        report = validate_firmware_config(config, build)
        fw016 = [r for r in report.results if r.constraint_id == "fw_016"]
        assert len(fw016) == 1
        assert not fw016[0].passed


class TestSerialConflicts:
    """fw_018: No conflicting serial assignments."""

    def test_no_conflicts(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=64, functions=["SERIAL_RX"]),
            SerialPortConfig(port_id=1, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw018 = [r for r in report.results if r.constraint_id == "fw_018"]
        assert len(fw018) == 1
        assert fw018[0].passed

    def test_gps_and_rx_conflict(self):
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=66, functions=["GPS", "SERIAL_RX"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build()
        report = validate_firmware_config(config, build)
        fw018 = [r for r in report.results if r.constraint_id == "fw_018"]
        assert len(fw018) == 1
        assert not fw018[0].passed


class TestINAVNavSettings:
    """fw_019: iNav navigation settings."""

    def test_inav_reasonable_speed(self):
        config = _make_config(
            firmware="INAV",
            master_settings={"nav_mc_vel_xy_max": "1000"},
        )
        build = Build(name="Test", drone_class="7inch_lr", components={})
        report = validate_firmware_config(config, build)
        fw019 = [r for r in report.results if r.constraint_id == "fw_019"]
        assert len(fw019) == 1
        assert fw019[0].passed

    def test_inav_low_speed_long_range(self):
        config = _make_config(
            firmware="INAV",
            master_settings={"nav_mc_vel_xy_max": "300"},
        )
        build = Build(name="Test", drone_class="7inch_lr", components={})
        report = validate_firmware_config(config, build)
        fw019 = [r for r in report.results if r.constraint_id == "fw_019"]
        assert len(fw019) == 1
        assert not fw019[0].passed

    def test_btfl_skips_check(self):
        config = _make_config(
            firmware="BTFL",
            master_settings={"nav_mc_vel_xy_max": "300"},
        )
        build = Build(name="Test", drone_class="7inch_lr", components={})
        report = validate_firmware_config(config, build)
        fw019 = [r for r in report.results if r.constraint_id == "fw_019"]
        assert len(fw019) == 0


class TestINAVFixedWing:
    """fw_020: iNav fixed-wing platform type."""

    def test_correct_platform(self):
        config = _make_config(
            firmware="INAV",
            master_settings={"platform_type": "AIRPLANE"},
        )
        build = Build(name="Test", drone_class="flying_wing", components={})
        report = validate_firmware_config(config, build)
        fw020 = [r for r in report.results if r.constraint_id == "fw_020"]
        assert len(fw020) == 1
        assert fw020[0].passed

    def test_wrong_platform(self):
        config = _make_config(
            firmware="INAV",
            master_settings={"platform_type": "MULTIROTOR"},
        )
        build = Build(name="Test", drone_class="flying_wing", components={})
        report = validate_firmware_config(config, build)
        fw020 = [r for r in report.results if r.constraint_id == "fw_020"]
        assert len(fw020) == 1
        assert not fw020[0].passed


class TestValidateReport:
    """Integration: full report structure."""

    def test_report_has_build_name(self):
        config = _make_config()
        build = _make_build()
        report = validate_firmware_config(config, build)
        assert report.build_name == "Test Build"

    def test_comprehensive_build(self):
        """A realistic build with multiple checks triggered."""
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=64, functions=["SERIAL_RX"]),
            SerialPortConfig(port_id=1, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
            SerialPortConfig(port_id=2, function_mask=65536, functions=["VTX_MSP"]),
        ]
        config = _make_config(
            master_settings={
                "motor_pwm_protocol": "DSHOT600",
                "serialrx_provider": "CRSF",
                "dshot_bidir": "ON",
                "vbat_min_cell_voltage": "330",
                "pid_process_denom": "2",
            },
            features={"OSD", "TELEMETRY"},
            serial_ports=serial_ports,
        )
        build = _make_build(
            esc=_make_component("esc", {"protocol": "DShot600", "firmware": "BLHeli_32", "current_sensor": True}),
            receiver=_make_component("receiver", {"output_protocol": "CRSF", "telemetry": True}),
            vtx=_make_component("vtx", {"type": "Analog", "system": "SmartAudio"}),
            fc=_make_component("fc", {"osd": "AT7456E", "mcu": "STM32F405"}),
            battery=_make_component("battery", {"cell_count": 6}),
        )

        report = validate_firmware_config(config, build)

        # Should have multiple results
        assert len(report.results) > 5

        # Motor protocol should pass
        fw001 = [r for r in report.results if r.constraint_id == "fw_001"]
        assert fw001[0].passed

        # RX protocol should pass
        fw004 = [r for r in report.results if r.constraint_id == "fw_004"]
        assert fw004[0].passed

        # Serial RX assigned should pass
        fw005 = [r for r in report.results if r.constraint_id == "fw_005"]
        assert fw005[0].passed
