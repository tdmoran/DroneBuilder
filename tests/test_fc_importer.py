"""Tests for engines/fc_importer.py — FC config to fleet drone extraction."""

from __future__ import annotations

from fc_serial.models import FCConfig, SerialPortConfig
from engines.fc_importer import (
    suggest_fleet_drone_from_config,
    _detect_vtx_type,
    _extract_craft_name,
    _build_tags,
    _detect_motor_count,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    board_name: str = "SPEEDYBEEF405V4",
    firmware: str = "BTFL",
    firmware_version: str = "4.4.2",
    settings: dict | None = None,
    features: set | None = None,
    serial_ports: list | None = None,
    resource_mappings: dict | None = None,
) -> FCConfig:
    """Build a minimal FCConfig for testing."""
    return FCConfig(
        firmware=firmware,
        firmware_version=firmware_version,
        board_name=board_name,
        master_settings=settings or {},
        features=features or set(),
        serial_ports=serial_ports or [],
        resource_mappings=resource_mappings or {},
    )


def _serial_port(port_id: int, functions: list[str]) -> SerialPortConfig:
    return SerialPortConfig(port_id=port_id, function_mask=0, functions=functions)


# ---------------------------------------------------------------------------
# Tests: suggest_fleet_drone_from_config
# ---------------------------------------------------------------------------


class TestSuggestFleetDrone:
    """Integration tests for the main suggest function."""

    def test_basic_suggestion_returns_dict(self):
        config = _make_config()
        result = suggest_fleet_drone_from_config(config)
        assert isinstance(result, dict)
        assert "name" in result
        assert "drone_class" in result
        assert "status" in result
        assert result["status"] == "building"

    def test_craft_name_used_when_present(self):
        config = _make_config(settings={"name": "MyRacer"})
        result = suggest_fleet_drone_from_config(config)
        assert result["name"] == "MyRacer"

    def test_craft_name_fallback_to_board_name(self):
        config = _make_config(board_name="IFLIGHT_BLITZ_F722")
        result = suggest_fleet_drone_from_config(config)
        assert "IFLIGHT_BLITZ_F722" in result["name"]

    def test_craft_name_fallback_when_no_board(self):
        config = _make_config(board_name="")
        result = suggest_fleet_drone_from_config(config)
        assert result["name"] == "New Drone from FC"

    def test_fc_match_by_mcu(self):
        """Board name containing F405 should match an FC with STM32F405 MCU."""
        config = _make_config(board_name="SPEEDYBEEF405V4")
        result = suggest_fleet_drone_from_config(config)
        # Should match the SpeedyBee F405 or at least some F405 FC
        if isinstance(result.get("fc"), str):
            assert "f405" in result["fc"].lower() or "F405" in result["fc"]

    def test_receiver_match_by_protocol(self):
        config = _make_config(settings={"serialrx_provider": "CRSF"})
        result = suggest_fleet_drone_from_config(config)
        det = result["_detection"]
        assert det["serialrx_provider"] == "CRSF"
        # If there's a CRSF receiver in the DB, it should match
        if det["rx_match"]:
            assert isinstance(result.get("receiver"), str)

    def test_esc_match_by_protocol(self):
        config = _make_config(settings={"motor_pwm_protocol": "DSHOT600"})
        result = suggest_fleet_drone_from_config(config)
        det = result["_detection"]
        assert det["motor_protocol"] == "DSHOT600"
        if det["esc_match"]:
            assert isinstance(result.get("esc"), str)

    def test_custom_fallback_when_no_fc_match(self):
        """Unknown board should produce a custom inline FC dict."""
        config = _make_config(board_name="OBSCURE_BOARD_XYZ123")
        result = suggest_fleet_drone_from_config(config)
        fc = result.get("fc")
        if isinstance(fc, dict):
            assert fc["_custom"] is True
            assert "OBSCURE_BOARD_XYZ123" in fc["model"]

    def test_custom_fallback_for_unknown_rx(self):
        config = _make_config(settings={"serialrx_provider": "SPEKTRUM_DSMX"})
        result = suggest_fleet_drone_from_config(config)
        rx = result.get("receiver")
        if isinstance(rx, dict):
            assert rx["_custom"] is True
            assert "SPEKTRUM_DSMX" in rx["model"]

    def test_notes_contain_firmware_info(self):
        config = _make_config(firmware="BTFL", firmware_version="4.4.2", board_name="TEST")
        result = suggest_fleet_drone_from_config(config)
        assert "Betaflight 4.4.2" in result["notes"]
        assert "TEST" in result["notes"]

    def test_detection_metadata_present(self):
        config = _make_config(
            settings={"serialrx_provider": "CRSF", "motor_pwm_protocol": "DSHOT600"},
        )
        result = suggest_fleet_drone_from_config(config)
        det = result["_detection"]
        assert det["serialrx_provider"] == "CRSF"
        assert det["motor_protocol"] == "DSHOT600"
        assert "firmware" in det
        assert "_matched_slots" in result

    def test_tags_include_firmware(self):
        config = _make_config(firmware="BTFL")
        result = suggest_fleet_drone_from_config(config)
        assert "betaflight" in result["tags"]

    def test_tags_include_rx_protocol(self):
        config = _make_config(settings={"serialrx_provider": "CRSF"})
        result = suggest_fleet_drone_from_config(config)
        assert "CRSF" in result["tags"]


# ---------------------------------------------------------------------------
# Tests: VTX detection
# ---------------------------------------------------------------------------


class TestDetectVtxType:

    def test_digital_vtx_from_msp(self):
        config = _make_config(serial_ports=[_serial_port(3, ["VTX_MSP"])])
        info = _detect_vtx_type(config)
        assert info["type"] == "digital"
        assert "MSP" in info["detail"]

    def test_analog_vtx_from_smartaudio(self):
        config = _make_config(serial_ports=[_serial_port(5, ["VTX_SMARTAUDIO"])])
        info = _detect_vtx_type(config)
        assert info["type"] == "analog"
        assert "SmartAudio" in info["detail"]

    def test_analog_vtx_from_tramp(self):
        config = _make_config(serial_ports=[_serial_port(2, ["VTX_TRAMP"])])
        info = _detect_vtx_type(config)
        assert info["type"] == "analog"
        assert "Tramp" in info["detail"]

    def test_no_vtx_detected(self):
        config = _make_config(serial_ports=[_serial_port(0, ["MSP"])])
        info = _detect_vtx_type(config)
        assert info["type"] == "none"


# ---------------------------------------------------------------------------
# Tests: craft name extraction
# ---------------------------------------------------------------------------


class TestExtractCraftName:

    def test_name_setting(self):
        config = _make_config(settings={"name": "My Racer"})
        assert _extract_craft_name(config) == "My Racer"

    def test_craft_name_setting(self):
        config = _make_config(settings={"craft_name": "CineLift"})
        assert _extract_craft_name(config) == "CineLift"

    def test_name_preferred_over_craft_name(self):
        config = _make_config(settings={"name": "Primary", "craft_name": "Secondary"})
        assert _extract_craft_name(config) == "Primary"

    def test_empty_when_no_setting(self):
        config = _make_config(settings={})
        assert _extract_craft_name(config) == ""

    def test_whitespace_stripped(self):
        config = _make_config(settings={"name": "  Padded  "})
        assert _extract_craft_name(config) == "Padded"


# ---------------------------------------------------------------------------
# Tests: motor count detection
# ---------------------------------------------------------------------------


class TestDetectMotorCount:

    def test_quad_from_resources(self):
        config = _make_config(resource_mappings={
            "MOTOR 1": "B06",
            "MOTOR 2": "B07",
            "MOTOR 3": "A00",
            "MOTOR 4": "A01",
        })
        assert _detect_motor_count(config) == 4

    def test_hex_from_resources(self):
        config = _make_config(resource_mappings={
            "MOTOR 1": "B06", "MOTOR 2": "B07",
            "MOTOR 3": "A00", "MOTOR 4": "A01",
            "MOTOR 5": "C08", "MOTOR 6": "C09",
        })
        assert _detect_motor_count(config) == 6

    def test_default_four_when_no_resources(self):
        config = _make_config(resource_mappings={})
        assert _detect_motor_count(config) == 4


# ---------------------------------------------------------------------------
# Tests: tag building
# ---------------------------------------------------------------------------


class TestBuildTags:

    def test_betaflight_tag(self):
        config = _make_config(firmware="BTFL")
        tags = _build_tags(config, {"type": "none", "detail": ""}, "")
        assert "betaflight" in tags

    def test_inav_tag(self):
        config = _make_config(firmware="INAV")
        tags = _build_tags(config, {"type": "none", "detail": ""}, "")
        assert "inav" in tags

    def test_digital_tag(self):
        config = _make_config()
        tags = _build_tags(config, {"type": "digital", "detail": "MSP"}, "")
        assert "digital" in tags

    def test_rx_protocol_tag(self):
        config = _make_config()
        tags = _build_tags(config, {"type": "none", "detail": ""}, "CRSF")
        assert "CRSF" in tags

    def test_gps_tag_from_feature(self):
        config = _make_config(features={"GPS"})
        tags = _build_tags(config, {"type": "none", "detail": ""}, "")
        assert "GPS" in tags

    def test_gps_tag_from_serial_port(self):
        config = _make_config(serial_ports=[_serial_port(2, ["GPS"])])
        tags = _build_tags(config, {"type": "none", "detail": ""}, "")
        assert "GPS" in tags
