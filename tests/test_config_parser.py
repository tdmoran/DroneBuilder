"""Tests for serial/config_parser.py — parsing diff all output."""

import pytest

from fc_serial.config_parser import parse_diff_all, _decode_function_mask


# ---------------------------------------------------------------------------
# Sample diff all snippets
# ---------------------------------------------------------------------------

BETAFLIGHT_DIFF = """\
# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024 / 10:00:00
# config rev: abc123

board_name SPEEDYBEEF405V4

# feature
feature OSD
feature -TELEMETRY
feature AIRMODE

# serial
serial 0 64 115200 57600 0 115200
serial 1 0 115200 57600 0 115200
serial 2 1024 115200 57600 0 115200
serial 3 2 115200 57600 0 115200

# aux
aux 0 0 1 1700 2100 0 0
aux 1 27 0 1700 2100 0 0

# resource
resource MOTOR 1 B06
resource MOTOR 2 B07

set motor_pwm_protocol = DSHOT600
set serialrx_provider = CRSF
set dshot_bidir = ON
set vbat_min_cell_voltage = 330
set vbat_max_cell_voltage = 430
set gyro_lpf1_static_hz = 200
set pid_process_denom = 2

profile 0
set p_pitch = 52
set d_pitch = 36

profile 1
set p_pitch = 45

rateprofile 0
set roll_rc_rate = 200
set pitch_rc_rate = 200

rateprofile 1
set roll_rc_rate = 150
"""

INAV_DIFF = """\
# INAV / STM32F405 (S405) 7.1.0 Dec 5 2024 / 12:00:00

feature OSD
feature TELEMETRY
feature GPS

serial 0 1 115200 57600 0 115200
serial 1 64 115200 57600 0 115200
serial 2 2 115200 57600 0 115200

set motor_pwm_protocol = DSHOT300
set serialrx_provider = CRSF
set platform_type = MULTIROTOR
set nav_mc_vel_xy_max = 1000
"""


class TestParseDiffAll:
    """Parse complete diff all output."""

    def test_betaflight_firmware_detected(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.firmware == "BTFL"
        assert config.firmware_version == "4.5.1"

    def test_betaflight_board_name(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.board_name == "STM32F405"

    def test_betaflight_features(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert "OSD" in config.features
        assert "AIRMODE" in config.features
        # TELEMETRY was disabled with -TELEMETRY
        assert "TELEMETRY" not in config.features

    def test_betaflight_serial_ports(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert len(config.serial_ports) == 4

        # Port 0 has SERIAL_RX (bit 64)
        port0 = config.serial_ports[0]
        assert port0.port_id == 0
        assert port0.function_mask == 64
        assert "SERIAL_RX" in port0.functions

        # Port 2 has VTX_SMARTAUDIO (bit 1024)
        port2 = config.serial_ports[2]
        assert port2.function_mask == 1024
        assert "VTX_SMARTAUDIO" in port2.functions

    def test_betaflight_master_settings(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.master_settings["motor_pwm_protocol"] == "DSHOT600"
        assert config.master_settings["serialrx_provider"] == "CRSF"
        assert config.master_settings["dshot_bidir"] == "ON"
        assert config.master_settings["vbat_min_cell_voltage"] == "330"
        assert config.master_settings["pid_process_denom"] == "2"

    def test_betaflight_pid_profiles(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert len(config.pid_profiles) == 2
        assert config.pid_profiles[0].settings["p_pitch"] == "52"
        assert config.pid_profiles[0].settings["d_pitch"] == "36"
        assert config.pid_profiles[1].settings["p_pitch"] == "45"

    def test_betaflight_rate_profiles(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert len(config.rate_profiles) == 2
        assert config.rate_profiles[0].settings["roll_rc_rate"] == "200"
        assert config.rate_profiles[1].settings["roll_rc_rate"] == "150"

    def test_betaflight_aux_modes(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert len(config.aux_modes) == 2
        assert config.aux_modes[0]["mode_id"] == "0"
        assert config.aux_modes[0]["channel"] == "1"

    def test_betaflight_resource_mappings(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.resource_mappings["MOTOR 1"] == "B06"
        assert config.resource_mappings["MOTOR 2"] == "B07"

    def test_inav_firmware_detected(self):
        config = parse_diff_all(INAV_DIFF)
        assert config.firmware == "INAV"
        assert config.firmware_version == "7.1.0"

    def test_inav_features(self):
        config = parse_diff_all(INAV_DIFF)
        assert "OSD" in config.features
        assert "TELEMETRY" in config.features
        assert "GPS" in config.features

    def test_inav_settings(self):
        config = parse_diff_all(INAV_DIFF)
        assert config.master_settings["platform_type"] == "MULTIROTOR"
        assert config.master_settings["nav_mc_vel_xy_max"] == "1000"

    def test_raw_text_stored(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.raw_text == BETAFLIGHT_DIFF

    def test_parsed_at_set(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.parsed_at != ""

    def test_empty_input(self):
        config = parse_diff_all("")
        assert config.firmware == "UNKNOWN"
        assert len(config.serial_ports) == 0
        assert len(config.master_settings) == 0

    def test_partial_input(self):
        config = parse_diff_all("set motor_pwm_protocol = DSHOT300\n")
        assert config.master_settings["motor_pwm_protocol"] == "DSHOT300"

    def test_get_setting(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.get_setting("motor_pwm_protocol") == "DSHOT600"
        assert config.get_setting("nonexistent") is None
        assert config.get_setting("nonexistent", "default") == "default"

    def test_has_feature(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        assert config.has_feature("OSD")
        assert config.has_feature("osd")  # Case insensitive
        assert not config.has_feature("GPS")

    def test_get_serial_port_with_function(self):
        config = parse_diff_all(BETAFLIGHT_DIFF)
        port = config.get_serial_port_with_function("SERIAL_RX")
        assert port is not None
        assert port.port_id == 0

        port = config.get_serial_port_with_function("GPS")
        assert port is not None
        assert port.port_id == 3


class TestDecodeFunctionMask:
    """Test bitmask decoding."""

    def test_unused(self):
        result = _decode_function_mask(0, "BTFL")
        assert result == ["UNUSED"]

    def test_serial_rx(self):
        result = _decode_function_mask(64, "BTFL")
        assert "SERIAL_RX" in result

    def test_combined_mask(self):
        # MSP (1) + SERIAL_RX (64) = 65
        result = _decode_function_mask(65, "BTFL")
        assert "MSP" in result
        assert "SERIAL_RX" in result

    def test_vtx_smartaudio(self):
        result = _decode_function_mask(1024, "BTFL")
        assert "VTX_SMARTAUDIO" in result

    def test_inav_differences(self):
        # Bit 8192 is RCDEVICE in BTFL, but TELEMETRY_LTM in INAV
        btfl = _decode_function_mask(8192, "BTFL")
        inav = _decode_function_mask(8192, "INAV")
        assert "RCDEVICE" in btfl
        assert "TELEMETRY_LTM" in inav
