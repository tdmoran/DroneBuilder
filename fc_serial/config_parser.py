"""Parse Betaflight/iNav `diff all` output into structured FCConfig."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fc_serial.firmware_detect import detect_firmware
from fc_serial.models import FCConfig, ParsedProfile, SerialPortConfig


# ---------------------------------------------------------------------------
# Serial port function bitmasks
# ---------------------------------------------------------------------------

# Betaflight serial function bits
BTFL_SERIAL_FUNCTIONS: dict[int, str] = {
    0: "UNUSED",
    1: "MSP",
    2: "GPS",
    4: "TELEMETRY_FRSKY",
    8: "TELEMETRY_HOTT",
    16: "TELEMETRY_MSP",
    32: "TELEMETRY_SMARTPORT",
    64: "SERIAL_RX",
    128: "BLACKBOX",
    256: "TELEMETRY_MAVLINK",
    512: "ESC_SENSOR",
    1024: "VTX_SMARTAUDIO",
    2048: "TELEMETRY_IBUS",
    4096: "VTX_TRAMP",
    8192: "RCDEVICE",
    16384: "LIDAR_TF",
    32768: "FRSKY_OSD",
    65536: "VTX_MSP",
}

# iNav serial function bits (differs from Betaflight)
INAV_SERIAL_FUNCTIONS: dict[int, str] = {
    0: "UNUSED",
    1: "MSP",
    2: "GPS",
    4: "TELEMETRY_FRSKY",
    8: "TELEMETRY_HOTT",
    16: "TELEMETRY_MSP",
    32: "TELEMETRY_SMARTPORT",
    64: "SERIAL_RX",
    128: "BLACKBOX",
    256: "TELEMETRY_MAVLINK",
    512: "ESC_SENSOR",
    1024: "VTX_SMARTAUDIO",
    2048: "TELEMETRY_IBUS",
    4096: "VTX_TRAMP",
    8192: "TELEMETRY_LTM",
    16384: "MSP_DISPLAYPORT",
    32768: "UNUSED_32768",
    65536: "VTX_MSP",
}


def _decode_function_mask(mask: int, firmware: str) -> list[str]:
    """Decode a serial port function bitmask to human-readable names."""
    lookup = INAV_SERIAL_FUNCTIONS if firmware == "INAV" else BTFL_SERIAL_FUNCTIONS
    functions = []
    for bit, name in sorted(lookup.items()):
        if bit == 0:
            continue
        if mask & bit:
            functions.append(name)
    return functions if functions else ["UNUSED"]


def _parse_serial_line(line: str, firmware: str) -> SerialPortConfig | None:
    """Parse a 'serial <id> <mask> <baud1> <baud2> <baud3> <baud4>' line."""
    match = re.match(
        r"serial\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        line.strip(),
    )
    if not match:
        return None

    port_id = int(match.group(1))
    function_mask = int(match.group(2))
    functions = _decode_function_mask(function_mask, firmware)

    return SerialPortConfig(
        port_id=port_id,
        function_mask=function_mask,
        functions=functions,
        baud_msp=int(match.group(3)),
        baud_gps=int(match.group(4)),
        baud_telemetry=int(match.group(5)),
        baud_peripheral=int(match.group(6)),
    )


def parse_diff_all(text: str) -> FCConfig:
    """Parse `diff all` output text into a structured FCConfig.

    Lenient: unknown lines are ignored, partial results returned
    for malformed input.
    """
    firmware, version, board_name = detect_firmware(text)

    config = FCConfig(
        firmware=firmware,
        firmware_version=version,
        board_name=board_name,
        raw_text=text,
        parsed_at=datetime.now(timezone.utc).isoformat(),
    )

    # Track which profile section we're in
    current_section = "master"  # master, profile, rateprofile
    current_profile_idx = 0
    current_rate_idx = 0

    for line in text.splitlines():
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith("#"):
            # But check for board_name in comments
            board_match = re.match(r"#\s*board_name\s+(\S+)", stripped)
            if board_match and not config.board_name:
                config.board_name = board_match.group(1)
            continue

        # Section headers
        profile_match = re.match(r"profile\s+(\d+)", stripped)
        if profile_match:
            current_section = "profile"
            current_profile_idx = int(profile_match.group(1))
            # Ensure profile list is long enough
            while len(config.pid_profiles) <= current_profile_idx:
                config.pid_profiles.append(
                    ParsedProfile(index=len(config.pid_profiles))
                )
            continue

        rateprofile_match = re.match(r"rateprofile\s+(\d+)", stripped)
        if rateprofile_match:
            current_section = "rateprofile"
            current_rate_idx = int(rateprofile_match.group(1))
            while len(config.rate_profiles) <= current_rate_idx:
                config.rate_profiles.append(
                    ParsedProfile(index=len(config.rate_profiles))
                )
            continue

        # Feature lines: "feature OSD" or "feature -TELEMETRY"
        feature_match = re.match(r"feature\s+(-?)(\S+)", stripped)
        if feature_match:
            sign = feature_match.group(1)
            feat_name = feature_match.group(2).upper()
            if sign == "-":
                config.features.discard(feat_name)
            else:
                config.features.add(feat_name)
            continue

        # Serial port lines
        if stripped.startswith("serial "):
            port = _parse_serial_line(stripped, firmware)
            if port:
                config.serial_ports.append(port)
            continue

        # Resource mappings: "resource MOTOR 1 B06"
        resource_match = re.match(r"resource\s+(\S+)\s+(\S+)\s+(\S+)", stripped)
        if resource_match:
            key = f"{resource_match.group(1)} {resource_match.group(2)}"
            config.resource_mappings[key] = resource_match.group(3)
            continue

        # Aux mode lines: "aux 0 0 1 1700 2100 0 0"
        aux_match = re.match(
            r"aux\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
            stripped,
        )
        if aux_match:
            config.aux_modes.append({
                "index": aux_match.group(1),
                "mode_id": aux_match.group(2),
                "channel": aux_match.group(3),
                "range_low": aux_match.group(4),
                "range_high": aux_match.group(5),
                "logic": aux_match.group(6),
                "linked_to": aux_match.group(7),
            })
            continue

        # Set lines: "set motor_pwm_protocol = DSHOT600"
        set_match = re.match(r"set\s+(\S+)\s*=\s*(.*)", stripped)
        if set_match:
            key = set_match.group(1)
            value = set_match.group(2).strip()

            if current_section == "profile" and current_profile_idx < len(config.pid_profiles):
                config.pid_profiles[current_profile_idx].settings[key] = value
            elif current_section == "rateprofile" and current_rate_idx < len(config.rate_profiles):
                config.rate_profiles[current_rate_idx].settings[key] = value
            else:
                config.master_settings[key] = value
            continue

    return config
