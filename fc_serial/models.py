"""Data models for FC configuration and serial connectivity."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SerialPortConfig:
    """A single UART/serial port configuration from the FC."""

    port_id: int  # UART index (0, 1, 2, ...)
    function_mask: int  # Raw bitmask from FC
    functions: list[str] = field(default_factory=list)  # Human-readable names
    baud_msp: int = 115200
    baud_gps: int = 0
    baud_telemetry: int = 0
    baud_peripheral: int = 0


@dataclass
class ParsedProfile:
    """A PID or rate profile parsed from diff all output."""

    index: int
    settings: dict[str, str] = field(default_factory=dict)


@dataclass
class FCConfig:
    """Parsed flight controller configuration from `diff all` output."""

    firmware: str  # "BTFL" or "INAV"
    firmware_version: str  # e.g. "4.5.1"
    board_name: str = ""
    master_settings: dict[str, str] = field(default_factory=dict)
    features: set[str] = field(default_factory=set)
    serial_ports: list[SerialPortConfig] = field(default_factory=list)
    pid_profiles: list[ParsedProfile] = field(default_factory=list)
    rate_profiles: list[ParsedProfile] = field(default_factory=list)
    resource_mappings: dict[str, str] = field(default_factory=dict)
    aux_modes: list[dict[str, str]] = field(default_factory=list)
    raw_text: str = ""
    parsed_at: str = ""  # ISO timestamp

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Look up a master setting by key name."""
        return self.master_settings.get(key, default)

    def has_feature(self, feature: str) -> bool:
        """Check if a feature flag is enabled (case-insensitive)."""
        return feature.upper() in {f.upper() for f in self.features}

    def get_serial_port_with_function(self, function_name: str) -> SerialPortConfig | None:
        """Find first serial port that has a given function assigned."""
        for port in self.serial_ports:
            if function_name in port.functions:
                return port
        return None

    def serial_ports_with_function(self, function_name: str) -> list[SerialPortConfig]:
        """Find all serial ports that have a given function assigned."""
        return [p for p in self.serial_ports if function_name in p.functions]


@dataclass
class DetectedPort:
    """A USB serial port detected as a potential flight controller."""

    device: str  # e.g. /dev/ttyACM0 or COM3
    description: str
    vid: int  # USB Vendor ID
    pid: int  # USB Product ID
    serial_number: str = ""
    manufacturer: str = ""


@dataclass
class StoredConfig:
    """Metadata for a stored FC config backup."""

    drone_slug: str
    timestamp: str  # YYYYMMDDTHHMMSS
    firmware: str
    firmware_version: str
    board_name: str
    raw_path: str  # Path to .txt file
    parsed_path: str  # Path to .json file
