"""Tests for serial/firmware_detect.py."""

import pytest

from fc_serial.firmware_detect import detect_firmware


class TestDetectFirmware:
    """Detect Betaflight vs iNav from version headers."""

    def test_betaflight_standard_header(self):
        text = "# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024 / 10:00:00\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "BTFL"
        assert ver == "4.5.1"
        assert board == "STM32F405"

    def test_betaflight_f722(self):
        text = "# Betaflight / STM32F7X2 (S7X2) 4.4.3 Oct  1 2024 / 08:15:00\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "BTFL"
        assert ver == "4.4.3"
        assert board == "STM32F7X2"

    def test_inav_standard_header(self):
        text = "# INAV / STM32F405 (S405) 7.1.0 Dec  5 2024 / 12:00:00\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "INAV"
        assert ver == "7.1.0"
        assert board == "STM32F405"

    def test_inav_f722(self):
        text = "# INAV / STM32F7X2 (S7X2) 6.1.1 Jan  3 2024 / 09:00:00\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "INAV"
        assert ver == "6.1.1"
        assert board == "STM32F7X2"

    def test_unknown_firmware(self):
        text = "some random text\nno version header\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "UNKNOWN"
        assert ver == ""

    def test_board_name_fallback(self):
        text = "board_name SPEEDYBEEF405V4\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "UNKNOWN"
        assert board == "SPEEDYBEEF405V4"

    def test_empty_text(self):
        fw, ver, board = detect_firmware("")
        assert fw == "UNKNOWN"
        assert ver == ""
        assert board == ""

    def test_betaflight_version_line(self):
        text = "# version / Betaflight / STM32F405 4.5.1\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "BTFL"
        assert ver == "4.5.1"

    def test_inav_version_line(self):
        text = "# version / INAV / STM32F411 6.0.0\n"
        fw, ver, board = detect_firmware(text)
        assert fw == "INAV"
        assert ver == "6.0.0"
