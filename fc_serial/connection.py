"""USB serial port detection and FC connection management."""

from __future__ import annotations

import threading
from typing import Any

from fc_serial.models import DetectedPort

# Known FC USB VID/PID pairs
_FC_VID_PIDS: dict[tuple[int, int], str] = {
    (0x0483, 0x5740): "STM32 Virtual COM Port",  # STM32 DFU/VCP
    (0x10C4, 0xEA60): "CP2102/CP2104",           # Silicon Labs USB-UART
    (0x1A86, 0x7523): "CH340",                    # WCH CH340
    (0x2E3C, 0x5740): "AT32 VCP",                 # Artery AT32
    (0x0483, 0xDF11): "STM32 DFU",                # STM32 DFU mode
    (0x2341, 0x0043): "Arduino Mega",             # Some FC bootloaders
    (0x1EAF, 0x0004): "Maple Serial",             # Leaflabs / some FCs
    (0x0403, 0x6001): "FTDI FT232R",              # FTDI USB-UART
    (0x0403, 0x6015): "FTDI FT-X",                # FTDI FT230X/FT231X
    (0x1FC9, 0x0083): "NXP LPC",                  # NXP-based FCs
}

# macOS built-in ports to always skip
_IGNORED_PORTS: set[str] = {
    "/dev/cu.debug-console",
    "/dev/cu.Bluetooth-Incoming-Port",
    "/dev/tty.debug-console",
    "/dev/tty.Bluetooth-Incoming-Port",
}


def detect_fc_ports() -> list[DetectedPort]:
    """Scan USB serial ports and return likely FC ports.

    First returns ports matching known FC VID/PIDs, then any other
    USB serial port (has a VID/PID) that isn't a known non-FC device.
    Built-in macOS ports (Bluetooth, debug console) are always skipped.

    Requires pyserial. Returns empty list if pyserial is not installed.
    """
    try:
        from serial.tools.list_ports import comports  # type: ignore[import]
    except ImportError:
        return []

    known: list[DetectedPort] = []
    other_usb: list[DetectedPort] = []

    for port_info in comports():
        device = port_info.device

        # Skip macOS built-in ports
        if device in _IGNORED_PORTS:
            continue

        vid = port_info.vid
        pid = port_info.pid

        if vid is not None and pid is not None:
            chip_desc = _FC_VID_PIDS.get((vid, pid))
            port = DetectedPort(
                device=device,
                description=port_info.description or chip_desc or "USB Serial",
                vid=vid,
                pid=pid,
                serial_number=port_info.serial_number or "",
                manufacturer=port_info.manufacturer or "",
            )
            if chip_desc:
                known.append(port)
            else:
                other_usb.append(port)

        elif "usb" in device.lower() or "acm" in device.lower() or "ttyUSB" in device:
            # No VID/PID but device path suggests USB serial
            other_usb.append(DetectedPort(
                device=device,
                description=port_info.description or "USB Serial Device",
                vid=0,
                pid=0,
                serial_number=port_info.serial_number or "",
                manufacturer=port_info.manufacturer or "",
            ))

    # Known FC ports first, then other USB serial ports
    return known + other_usb


class FCConnection:
    """Thread-safe serial connection to a flight controller."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Any = None  # serial.Serial instance
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self) -> None:
        """Open the serial connection."""
        import serial as pyserial  # type: ignore[import]

        with self._lock:
            if self.is_open:
                return
            self._serial = pyserial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )

    def close(self) -> None:
        """Close the serial connection."""
        with self._lock:
            if self._serial and self._serial.is_open:
                self._serial.close()
            self._serial = None

    def read(self, size: int = 1) -> bytes:
        """Read up to *size* bytes from serial port."""
        with self._lock:
            if not self.is_open:
                raise ConnectionError("Serial port not open")
            return self._serial.read(size)

    def read_until(self, terminator: bytes = b"\n", size: int | None = None) -> bytes:
        """Read until terminator or size limit."""
        with self._lock:
            if not self.is_open:
                raise ConnectionError("Serial port not open")
            return self._serial.read_until(terminator, size)

    def read_all(self) -> bytes:
        """Read all available bytes."""
        with self._lock:
            if not self.is_open:
                raise ConnectionError("Serial port not open")
            return self._serial.read(self._serial.in_waiting or 1)

    def write(self, data: bytes) -> int:
        """Write bytes to serial port."""
        with self._lock:
            if not self.is_open:
                raise ConnectionError("Serial port not open")
            return self._serial.write(data)

    @property
    def in_waiting(self) -> int:
        """Number of bytes in the input buffer."""
        with self._lock:
            if not self.is_open:
                return 0
            return self._serial.in_waiting

    def __enter__(self) -> FCConnection:
        self.open()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# Module-level connection registry (one connection per port path)
_connections: dict[str, FCConnection] = {}
_registry_lock = threading.Lock()


def get_connection(port: str) -> FCConnection | None:
    """Get the active connection for a port, or None."""
    with _registry_lock:
        conn = _connections.get(port)
        if conn and conn.is_open:
            return conn
        return None


def open_connection(port: str, baudrate: int = 115200) -> FCConnection:
    """Open a connection to a port, closing any existing one first."""
    with _registry_lock:
        existing = _connections.get(port)
        if existing and existing.is_open:
            existing.close()

        conn = FCConnection(port, baudrate)
        conn.open()
        _connections[port] = conn
        return conn


def close_connection(port: str) -> bool:
    """Close the connection on a port. Returns True if was open."""
    with _registry_lock:
        conn = _connections.pop(port, None)
        if conn and conn.is_open:
            conn.close()
            return True
        return False


def get_active_port() -> str | None:
    """Return the port path of the first active connection, or None."""
    with _registry_lock:
        for port, conn in _connections.items():
            if conn.is_open:
                return port
        return None
