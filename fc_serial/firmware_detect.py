"""Detect flight controller firmware type from version header text."""

from __future__ import annotations

import re


def detect_firmware(text: str) -> tuple[str, str, str]:
    """Detect firmware type, version, and board name from diff all output.

    Returns:
        (firmware, version, board_name) — e.g. ("BTFL", "4.5.1", "STM32F405")
        firmware is "BTFL" for Betaflight, "INAV" for iNav, "UNKNOWN" otherwise.
    """
    firmware = "UNKNOWN"
    version = ""
    board_name = ""

    for line in text.splitlines():
        line = line.strip()

        # Betaflight: "# Betaflight / STM32F405 (S405) 4.5.1 Nov 14 2024 / ..."
        # or: "# version / Betaflight / 4.5.1 ..."
        btfl_match = re.match(
            r"#\s*(?:version\s*/\s*)?Betaflight\s*/\s*(\S+)\s+(?:\(\S+\)\s+)?(\d+\.\d+\.\d+)",
            line,
            re.IGNORECASE,
        )
        if btfl_match:
            firmware = "BTFL"
            board_name = btfl_match.group(1)
            version = btfl_match.group(2)
            continue

        # iNav: "# INAV / STM32F405 (S405) 7.1.0 ..."
        # or: "# version / INAV / 7.1.0 ..."
        inav_match = re.match(
            r"#\s*(?:version\s*/\s*)?INAV\s*/\s*(\S+)\s+(?:\(\S+\)\s+)?(\d+\.\d+\.\d+)",
            line,
            re.IGNORECASE,
        )
        if inav_match:
            firmware = "INAV"
            board_name = inav_match.group(1)
            version = inav_match.group(2)
            continue

        # Fallback board detection from "board_name" line
        board_match = re.match(r"board_name\s+(\S+)", line)
        if board_match and not board_name:
            board_name = board_match.group(1)

    return firmware, version, board_name
