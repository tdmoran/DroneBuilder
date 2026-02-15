"""Tests for engines/discrepancy.py — all 10 discrepancy checks."""

from __future__ import annotations

import pytest

from core.models import Build, Component, Discrepancy, Severity
from engines.discrepancy import detect_discrepancies
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
    board_name: str = "",
    master_settings: dict | None = None,
    features: set | None = None,
    serial_ports: list | None = None,
    resource_mappings: dict | None = None,
) -> FCConfig:
    return FCConfig(
        firmware="BTFL",
        firmware_version="4.5.2",
        board_name=board_name,
        master_settings=master_settings or {},
        features=features or set(),
        serial_ports=serial_ports or [],
        resource_mappings=resource_mappings or {},
    )


def _get_disc(discrepancies: list[Discrepancy], disc_id: str) -> Discrepancy | None:
    for d in discrepancies:
        if d.id == disc_id:
            return d
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFCBoard:
    """disc_001: FC board mismatch."""

    def test_matching_board(self):
        config = _make_config(board_name="MATEKF405")
        build = _make_build(fc=_make_component("fc", {"mcu": "STM32F405"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_001") is None

    def test_matching_f722(self):
        config = _make_config(board_name="IFLIGHT_BLITZ_F722")
        build = _make_build(fc=_make_component("fc", {"mcu": "STM32F722"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_001") is None

    def test_mismatched_board(self):
        config = _make_config(board_name="IFLIGHT_BLITZ_F722")
        build = _make_build(fc=_make_component("fc", {"mcu": "STM32F405"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_001")
        assert disc is not None
        assert disc.severity == Severity.CRITICAL
        assert "swapped" in disc.message

    def test_no_fc_in_build(self):
        config = _make_config(board_name="MATEKF405")
        build = _make_build()
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_001") is None

    def test_h743_board(self):
        config = _make_config(board_name="SPEEDYBEEF7V3_H743")
        build = _make_build(fc=_make_component("fc", {"mcu": "STM32H743"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_001") is None


class TestReceiverProtocol:
    """disc_002: Receiver protocol mismatch."""

    def test_matching_crsf(self):
        config = _make_config(master_settings={"serialrx_provider": "CRSF"})
        build = _make_build(receiver=_make_component("receiver", {"output_protocol": "CRSF"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_002") is None

    def test_mismatched_protocol(self):
        config = _make_config(master_settings={"serialrx_provider": "SBUS"})
        build = _make_build(receiver=_make_component("receiver", {"output_protocol": "CRSF"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_002")
        assert disc is not None
        assert disc.severity == Severity.CRITICAL
        assert "SBUS" in disc.detected_value

    def test_no_receiver(self):
        config = _make_config(master_settings={"serialrx_provider": "CRSF"})
        build = _make_build()
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_002") is None


class TestVTXType:
    """disc_003: VTX type mismatch (analog vs digital)."""

    def test_matching_digital(self):
        serial_ports = [
            SerialPortConfig(port_id=3, function_mask=65536, functions=["VTX_MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_003") is None

    def test_matching_analog(self):
        serial_ports = [
            SerialPortConfig(port_id=2, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Analog", "system": "SmartAudio"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_003") is None

    def test_digital_fleet_analog_config(self):
        serial_ports = [
            SerialPortConfig(port_id=5, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_003")
        assert disc is not None
        assert disc.severity == Severity.CRITICAL
        assert "Analog VTX" in disc.detected_value

    def test_analog_fleet_digital_config(self):
        serial_ports = [
            SerialPortConfig(port_id=3, function_mask=65536, functions=["VTX_MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Analog", "system": "SmartAudio"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_003")
        assert disc is not None
        assert disc.severity == Severity.CRITICAL

    def test_no_vtx_uart(self):
        """No VTX UART configured — no discrepancy detectable."""
        serial_ports = [
            SerialPortConfig(port_id=0, function_mask=1, functions=["MSP"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(vtx=_make_component("vtx", {"type": "Digital HD"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_003") is None


class TestMotorProtocol:
    """disc_004: Motor protocol mismatch."""

    def test_matching_dshot600(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT600"})
        build = _make_build(esc=_make_component("esc", {"protocol": "DShot600"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_004") is None

    def test_mismatched_protocol(self):
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT1200"})
        build = _make_build(esc=_make_component("esc", {"protocol": "DShot600"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_004")
        assert disc is not None
        assert disc.severity == Severity.WARNING

    def test_backwards_compatible(self):
        """DSHOT300 ESC with DSHOT150 FC setting — compatible (lower is always ok)."""
        config = _make_config(master_settings={"motor_pwm_protocol": "DSHOT150"})
        build = _make_build(esc=_make_component("esc", {"protocol": "DShot300"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_004") is None


class TestBidirDShotFirmware:
    """disc_005: ESC firmware mismatch (bidir DShot)."""

    def test_bidir_with_blheli32(self):
        config = _make_config(master_settings={"dshot_bidir": "ON"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_32"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_005") is None

    def test_bidir_with_blheli_s(self):
        config = _make_config(master_settings={"dshot_bidir": "ON"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_S"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_005")
        assert disc is not None
        assert disc.severity == Severity.WARNING

    def test_no_bidir(self):
        config = _make_config(master_settings={"dshot_bidir": "OFF"})
        build = _make_build(esc=_make_component("esc", {"firmware": "BLHeli_S"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_005") is None


class TestBatteryCells:
    """disc_006: Battery cell count mismatch."""

    def test_standard_lipo_correct(self):
        config = _make_config(master_settings={"vbat_max_cell_voltage": "430"})
        build = _make_build(battery=_make_component("battery", {"cell_count": 6, "chemistry": "LiPo"}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_006") is None

    def test_hv_lipo_with_standard_setting(self):
        config = _make_config(master_settings={"vbat_max_cell_voltage": "420"})
        build = _make_build(battery=_make_component("battery", {"cell_count": 6, "chemistry": "LiHV"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_006")
        assert disc is not None
        assert disc.severity == Severity.WARNING

    def test_standard_lipo_with_hv_setting(self):
        config = _make_config(master_settings={"vbat_max_cell_voltage": "435"})
        build = _make_build(battery=_make_component("battery", {"cell_count": 6, "chemistry": "LiPo"}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_006")
        assert disc is not None
        assert disc.severity == Severity.WARNING

    def test_no_battery(self):
        config = _make_config(master_settings={"vbat_max_cell_voltage": "430"})
        build = _make_build()
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_006") is None


class TestCraftName:
    """disc_007: Craft name mismatch."""

    def test_matching_name(self):
        config = _make_config(master_settings={"name": "Nazgul"})
        build = _make_build()
        build.name = "Nazgul"
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_007") is None

    def test_matching_nickname(self):
        config = _make_config(master_settings={"name": "Screamer"})
        build = _make_build()
        build.name = "Nazgul F5 V3"
        build.nickname = "Screamer"
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_007") is None

    def test_partial_match(self):
        config = _make_config(master_settings={"name": "Nazgul"})
        build = _make_build()
        build.name = "Nazgul F5 V3"
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_007") is None

    def test_mismatched_name(self):
        config = _make_config(master_settings={"name": "Tinyhawk"})
        build = _make_build()
        build.name = "Nazgul F5 V3"
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_007")
        assert disc is not None
        assert disc.severity == Severity.INFO

    def test_no_craft_name(self):
        config = _make_config(master_settings={})
        build = _make_build()
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_007") is None


class TestGPSPresence:
    """disc_008: GPS presence mismatch."""

    def test_gps_in_both(self):
        serial_ports = [
            SerialPortConfig(port_id=1, function_mask=2, functions=["GPS"]),
        ]
        config = _make_config(features={"GPS"}, serial_ports=serial_ports)
        build = _make_build(gps=_make_component("gps", {}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_008") is None

    def test_gps_in_fleet_not_config(self):
        config = _make_config(features=set(), serial_ports=[])
        build = _make_build(gps=_make_component("gps", {}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_008")
        assert disc is not None
        assert disc.severity == Severity.INFO
        assert "removed" in disc.message

    def test_gps_in_config_not_fleet(self):
        config = _make_config(features={"GPS"})
        build = _make_build()
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_008")
        assert disc is not None
        assert disc.severity == Severity.INFO
        assert "added" in disc.message

    def test_no_gps_anywhere(self):
        config = _make_config()
        build = _make_build()
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_008") is None


class TestESCTelemetry:
    """disc_009: ESC telemetry mismatch."""

    def test_both_have_sensor(self):
        serial_ports = [
            SerialPortConfig(port_id=4, function_mask=512, functions=["ESC_SENSOR"]),
        ]
        config = _make_config(serial_ports=serial_ports)
        build = _make_build(esc=_make_component("esc", {"current_sensor": True}))
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_009") is None

    def test_fleet_has_sensor_config_doesnt(self):
        config = _make_config()
        build = _make_build(esc=_make_component("esc", {"current_sensor": True}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_009")
        assert disc is not None
        assert disc.severity == Severity.INFO

    def test_config_has_sensor_fleet_doesnt(self):
        config = _make_config(features={"ESC_SENSOR"})
        build = _make_build(esc=_make_component("esc", {"current_sensor": False}))
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_009")
        assert disc is not None
        assert disc.severity == Severity.INFO


class TestMotorCount:
    """disc_010: Motor count mismatch."""

    def test_matching_count(self):
        config = _make_config(resource_mappings={
            "MOTOR 1": "B06", "MOTOR 2": "B07",
            "MOTOR 3": "B08", "MOTOR 4": "B09",
        })
        motor = _make_component("motor", {})
        build = _make_build(motor=[motor] * 4)
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_010") is None

    def test_mismatched_count(self):
        config = _make_config(resource_mappings={
            "MOTOR 1": "B06", "MOTOR 2": "B07",
            "MOTOR 3": "B08", "MOTOR 4": "B09",
            "MOTOR 5": "B10", "MOTOR 6": "B11",
        })
        motor = _make_component("motor", {})
        build = _make_build(motor=[motor] * 4)
        result = detect_discrepancies(config, build)
        disc = _get_disc(result, "disc_010")
        assert disc is not None
        assert disc.severity == Severity.WARNING
        assert "6" in disc.detected_value

    def test_no_resource_mappings(self):
        config = _make_config(resource_mappings={})
        motor = _make_component("motor", {})
        build = _make_build(motor=[motor] * 4)
        result = detect_discrepancies(config, build)
        assert _get_disc(result, "disc_010") is None


class TestDetectDiscrepancies:
    """Integration: detect_discrepancies with a realistic scenario."""

    def test_multiple_discrepancies(self):
        """Build with several mismatches."""
        serial_ports = [
            SerialPortConfig(port_id=2, function_mask=1024, functions=["VTX_SMARTAUDIO"]),
        ]
        config = _make_config(
            board_name="IFLIGHT_BLITZ_F722",
            master_settings={
                "serialrx_provider": "SBUS",
                "motor_pwm_protocol": "DSHOT600",
                "name": "OtherDrone",
            },
            serial_ports=serial_ports,
        )
        build = Build(
            name="Nazgul F5 V3",
            drone_class="5inch_freestyle",
            components={
                "fc": _make_component("fc", {"mcu": "STM32F405"}),
                "receiver": _make_component("receiver", {"output_protocol": "CRSF"}),
                "vtx": _make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}),
                "esc": _make_component("esc", {"protocol": "DShot600"}),
            },
        )

        result = detect_discrepancies(config, build)

        # Should detect: disc_001 (FC board), disc_002 (RX), disc_003 (VTX), disc_007 (name)
        ids = {d.id for d in result}
        assert "disc_001" in ids  # F722 vs F405
        assert "disc_002" in ids  # SBUS vs CRSF
        assert "disc_003" in ids  # SmartAudio vs Digital
        assert "disc_007" in ids  # OtherDrone vs Nazgul

    def test_clean_build_no_discrepancies(self):
        """A perfectly matching build and config."""
        serial_ports = [
            SerialPortConfig(port_id=1, function_mask=64, functions=["SERIAL_RX"]),
            SerialPortConfig(port_id=3, function_mask=65536, functions=["VTX_MSP"]),
        ]
        config = _make_config(
            board_name="MATEKF405",
            master_settings={
                "serialrx_provider": "CRSF",
                "motor_pwm_protocol": "DSHOT600",
                "name": "Nazgul",
                "vbat_max_cell_voltage": "430",
            },
            serial_ports=serial_ports,
            resource_mappings={
                "MOTOR 1": "B06", "MOTOR 2": "B07",
                "MOTOR 3": "B08", "MOTOR 4": "B09",
            },
        )
        motor = _make_component("motor", {})
        build = Build(
            name="Nazgul F5 V3",
            drone_class="5inch_freestyle",
            components={
                "fc": _make_component("fc", {"mcu": "STM32F405"}),
                "receiver": _make_component("receiver", {"output_protocol": "CRSF"}),
                "vtx": _make_component("vtx", {"type": "Digital HD", "system": "DJI O3"}),
                "esc": _make_component("esc", {"protocol": "DShot600"}),
                "battery": _make_component("battery", {"cell_count": 6, "chemistry": "LiPo"}),
                "motor": [motor] * 4,
            },
        )

        result = detect_discrepancies(config, build)
        assert len(result) == 0
