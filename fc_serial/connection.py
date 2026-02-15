"""USB serial port detection and FC connection management."""

from __future__ import annotations

import threading
from typing import Any

from fc_serial.models import DetectedPort

# Known FC USB VID/PID pairs
_FC_VID_PIDS: list[tuple[int, int, str]] = [
    (0x0483, 0x5740, "STM32 Virtual COM Port"),  # STM32 DFU/VCP
    (0x10C4, 0xEA60, "CP2102/CP2104"),           # Silicon Labs USB-UART
    (0x1A86, 0x7523, "CH340"),                    # WCH CH340
    (0x2E3C, 0x5740, "AT32 VCP"),                 # Artery AT32
    (0x0483, 0xDF11, "STM32 DFU"),                # STM32 DFU mode
]


def detect_fc_ports() -> list[DetectedPort]:
    """Scan USB serial ports and return those matching known FC VID/PIDs.

    Requires pyserial. Returns empty list if pyserial is not installed
    or no matching ports are found.
    """
    try:
        from serial.tools.list_ports import comports  # type: ignore[import]
    except ImportError:
        return []

    detected: list[DetectedPort] = []

    for port_info in comports():
        vid = port_info.vid
        pid = port_info.pid

        if vid is None or pid is None:
            continue

        for known_vid, known_pid, chip_desc in _FC_VID_PIDS:
            if vid == known_vid and pid == known_pid:
                detected.append(DetectedPort(
                    device=port_info.device,
                    description=port_info.description or chip_desc,
                    vid=vid,
                    pid=pid,
                    serial_number=port_info.serial_number or "",
                    manufacturer=port_info.manufacturer or "",
                ))
                break

    return detected


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
