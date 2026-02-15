"""Tests for serial/connection.py — port detection and connection management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fc_serial.connection import (
    FCConnection,
    close_connection,
    detect_fc_ports,
    get_active_port,
    get_connection,
    open_connection,
    _connections,
    _registry_lock,
)
from fc_serial.models import DetectedPort


class TestDetectFCPorts:
    """USB port detection."""

    @patch("serial.tools.list_ports.comports")
    def test_finds_stm32_port(self, mock_comports):
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyACM0"
        mock_port.description = "STM32 Virtual COM Port"
        mock_port.vid = 0x0483
        mock_port.pid = 0x5740
        mock_port.serial_number = "ABC123"
        mock_port.manufacturer = "STMicroelectronics"
        mock_comports.return_value = [mock_port]

        ports = detect_fc_ports()
        assert len(ports) == 1
        assert ports[0].device == "/dev/ttyACM0"
        assert ports[0].vid == 0x0483

    @patch("serial.tools.list_ports.comports")
    def test_unknown_usb_device_included(self, mock_comports):
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.description = "USB Serial"
        mock_port.vid = 0x1234
        mock_port.pid = 0x5678
        mock_port.serial_number = ""
        mock_port.manufacturer = ""
        mock_comports.return_value = [mock_port]

        ports = detect_fc_ports()
        assert len(ports) == 1
        assert ports[0].device == "/dev/ttyUSB0"

    @patch("serial.tools.list_ports.comports")
    def test_known_ports_listed_before_unknown(self, mock_comports):
        stm32 = MagicMock()
        stm32.device = "/dev/ttyACM0"
        stm32.description = "STM32 VCP"
        stm32.vid = 0x0483
        stm32.pid = 0x5740
        stm32.serial_number = ""
        stm32.manufacturer = ""

        unknown = MagicMock()
        unknown.device = "/dev/ttyUSB0"
        unknown.description = "Unknown USB"
        unknown.vid = 0x9999
        unknown.pid = 0x0001
        unknown.serial_number = ""
        unknown.manufacturer = ""

        mock_comports.return_value = [unknown, stm32]

        ports = detect_fc_ports()
        assert len(ports) == 2
        assert ports[0].device == "/dev/ttyACM0"  # Known FC first
        assert ports[1].device == "/dev/ttyUSB0"   # Unknown USB second

    @patch("serial.tools.list_ports.comports")
    def test_skips_macos_builtin_ports(self, mock_comports):
        bt = MagicMock()
        bt.device = "/dev/cu.Bluetooth-Incoming-Port"
        bt.vid = None
        bt.pid = None

        debug = MagicMock()
        debug.device = "/dev/cu.debug-console"
        debug.vid = None
        debug.pid = None

        mock_comports.return_value = [bt, debug]

        ports = detect_fc_ports()
        assert len(ports) == 0

    @patch("serial.tools.list_ports.comports")
    def test_usb_path_without_vid_pid(self, mock_comports):
        mock_port = MagicMock()
        mock_port.device = "/dev/ttyUSB0"
        mock_port.description = "USB Serial"
        mock_port.vid = None
        mock_port.pid = None
        mock_port.serial_number = ""
        mock_port.manufacturer = ""
        mock_comports.return_value = [mock_port]

        ports = detect_fc_ports()
        assert len(ports) == 1
        assert ports[0].vid == 0


class TestFCConnection:
    """FCConnection wrapper."""

    def test_initial_state(self):
        conn = FCConnection("/dev/ttyACM0", baudrate=115200)
        assert conn.port == "/dev/ttyACM0"
        assert conn.baudrate == 115200
        assert not conn.is_open

    @patch("serial.Serial")
    def test_open_close(self, mock_serial_class):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_class.return_value = mock_serial

        conn = FCConnection("/dev/ttyACM0")
        conn.open()
        assert conn.is_open

        conn.close()
        mock_serial.close.assert_called_once()

    @patch("serial.Serial")
    def test_context_manager(self, mock_serial_class):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_class.return_value = mock_serial

        with FCConnection("/dev/ttyACM0") as conn:
            assert conn.is_open
        mock_serial.close.assert_called()

    def test_read_when_closed_raises(self):
        conn = FCConnection("/dev/ttyACM0")
        with pytest.raises(ConnectionError):
            conn.read()

    def test_write_when_closed_raises(self):
        conn = FCConnection("/dev/ttyACM0")
        with pytest.raises(ConnectionError):
            conn.write(b"test")


class TestConnectionRegistry:
    """Module-level connection registry."""

    def setup_method(self):
        """Clear the registry before each test."""
        with _registry_lock:
            for port, conn in list(_connections.items()):
                try:
                    conn.close()
                except Exception:
                    pass
            _connections.clear()

    def test_get_connection_returns_none_when_empty(self):
        assert get_connection("/dev/ttyACM0") is None

    def test_get_active_port_returns_none_when_empty(self):
        assert get_active_port() is None

    @patch("serial.Serial")
    def test_open_and_get_connection(self, mock_serial_class):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_class.return_value = mock_serial

        conn = open_connection("/dev/ttyACM0")
        assert conn.is_open

        retrieved = get_connection("/dev/ttyACM0")
        assert retrieved is conn

        assert get_active_port() == "/dev/ttyACM0"

    @patch("serial.Serial")
    def test_close_connection(self, mock_serial_class):
        mock_serial = MagicMock()
        mock_serial.is_open = True
        mock_serial_class.return_value = mock_serial

        open_connection("/dev/ttyACM0")
        assert close_connection("/dev/ttyACM0") is True
        assert close_connection("/dev/ttyACM0") is False
        assert get_active_port() is None
