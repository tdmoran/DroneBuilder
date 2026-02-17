"""Extract fleet drone data from an FC config.

Parses an FCConfig and matches detected components (FC board, receiver
protocol, ESC protocol, VTX type) against the component database to
produce a dict ready for ``save_fleet_drone()``.
"""

from __future__ import annotations

from typing import Any

from core.loader import load_components
from fc_serial.models import FCConfig


# Protocol name normalization for ESC matching.
# Betaflight stores e.g. "DSHOT600", component DB stores "DShot600".
_PROTOCOL_ALIASES: dict[str, list[str]] = {
    "DSHOT600": ["DShot600", "DSHOT600", "Dshot600"],
    "DSHOT300": ["DShot300", "DSHOT300", "Dshot300"],
    "DSHOT150": ["DShot150", "DSHOT150", "Dshot150"],
    "ONESHOT125": ["OneShot125", "ONESHOT125"],
    "ONESHOT42": ["OneShot42", "ONESHOT42"],
    "MULTISHOT": ["Multishot", "MULTISHOT"],
    "PWM": ["PWM"],
}


def _match_fc(board_name: str, components: dict[str, list]) -> dict[str, Any] | None:
    """Match FC board_name against component DB by MCU substring."""
    if not board_name:
        return None

    board_upper = board_name.upper()
    for comp in components.get("fc", []):
        mcu = comp.specs.get("mcu", "")
        if not mcu:
            continue
        mcu_short = mcu.upper().replace("STM32", "").replace("AT32", "")
        if mcu_short and mcu_short in board_upper:
            return {"id": comp.id, "manufacturer": comp.manufacturer, "model": comp.model}
    return None


def _match_receiver(serialrx_provider: str, components: dict[str, list]) -> dict[str, Any] | None:
    """Match RX protocol (e.g. CRSF) against receiver output_protocol."""
    if not serialrx_provider:
        return None

    provider_upper = serialrx_provider.strip().upper()
    for comp in components.get("receiver", []):
        output_proto = comp.specs.get("output_protocol", "")
        if output_proto and output_proto.upper() == provider_upper:
            return {"id": comp.id, "manufacturer": comp.manufacturer, "model": comp.model}
    return None


def _match_esc(motor_protocol: str, components: dict[str, list]) -> dict[str, Any] | None:
    """Match ESC by motor PWM protocol (e.g. DSHOT600)."""
    if not motor_protocol:
        return None

    proto_upper = motor_protocol.strip().upper()
    # Build list of acceptable protocol strings
    acceptable = {proto_upper}
    for key, aliases in _PROTOCOL_ALIASES.items():
        if key == proto_upper:
            acceptable.update(a.upper() for a in aliases)

    for comp in components.get("esc", []):
        esc_proto = comp.specs.get("protocol", "")
        if esc_proto and esc_proto.upper() in acceptable:
            return {"id": comp.id, "manufacturer": comp.manufacturer, "model": comp.model}
    return None


def _detect_vtx_type(config: FCConfig) -> dict[str, str]:
    """Detect VTX type from serial port functions.

    Returns a dict with 'type' ('digital'/'analog'/'none') and 'detail'.
    """
    if config.get_serial_port_with_function("VTX_MSP"):
        return {"type": "digital", "detail": "MSP DisplayPort"}

    if config.get_serial_port_with_function("VTX_SMARTAUDIO"):
        return {"type": "analog", "detail": "SmartAudio"}

    if config.get_serial_port_with_function("VTX_TRAMP"):
        return {"type": "analog", "detail": "IRC Tramp"}

    return {"type": "none", "detail": ""}


def _match_vtx(vtx_info: dict[str, str], components: dict[str, list]) -> dict[str, Any] | None:
    """Match VTX from detected type against component DB."""
    if vtx_info["type"] == "none":
        return None

    for comp in components.get("vtx", []):
        comp_type = comp.specs.get("type", "").lower()
        if vtx_info["type"] == "digital" and "digital" in comp_type:
            return {"id": comp.id, "manufacturer": comp.manufacturer, "model": comp.model}
        if vtx_info["type"] == "analog" and "analog" in comp_type:
            return {"id": comp.id, "manufacturer": comp.manufacturer, "model": comp.model}

    return None


def _custom_component(component_type: str, detected_id: str, **extra) -> dict[str, Any]:
    """Build an inline custom component dict when no DB match is found."""
    result: dict[str, Any] = {
        "_custom": True,
        "component_type": component_type,
        "id": detected_id,
        "manufacturer": "Unknown",
        "model": detected_id,
        "specs": {},
    }
    result.update(extra)
    return result


def _extract_craft_name(config: FCConfig) -> str:
    """Get the craft name from config settings."""
    name = config.get_setting("name", "") or config.get_setting("craft_name", "")
    return name.strip() if name else ""


def _detect_motor_count(config: FCConfig) -> int:
    """Infer motor count from resource mappings."""
    motor_keys = [k for k in config.resource_mappings if k.startswith("MOTOR")]
    return len(motor_keys) if motor_keys else 4


def _build_tags(config: FCConfig, vtx_info: dict[str, str], serialrx: str) -> list[str]:
    """Auto-generate tags from detected config info."""
    tags: list[str] = []

    # Firmware
    if config.firmware == "BTFL":
        tags.append("betaflight")
    elif config.firmware == "INAV":
        tags.append("inav")

    # VTX type
    if vtx_info["type"] == "digital":
        tags.append("digital")
    elif vtx_info["type"] == "analog":
        tags.append("analog")

    # RX protocol
    if serialrx:
        tags.append(serialrx.upper())

    # GPS
    if config.has_feature("GPS") or config.get_serial_port_with_function("GPS"):
        tags.append("GPS")

    return tags


def suggest_fleet_drone_from_config(config: FCConfig) -> dict[str, Any]:
    """Analyze an FC config and return a fleet drone dict with matched components.

    Returns a dict with:
        - Standard fleet drone fields (name, drone_class, status, etc.)
        - Component IDs where DB matches were found
        - Custom inline dicts where no DB match exists
        - ``_detection`` key with match details for display
    """
    components = load_components()

    # Extract basic info
    craft_name = _extract_craft_name(config)
    board_name = config.board_name
    serialrx = config.get_setting("serialrx_provider", "") or ""
    motor_protocol = config.get_setting("motor_pwm_protocol", "") or ""
    vtx_info = _detect_vtx_type(config)
    motor_count = _detect_motor_count(config)

    # Drone name
    if craft_name:
        drone_name = craft_name
    elif board_name:
        drone_name = f"New Drone ({board_name})"
    else:
        drone_name = "New Drone from FC"

    # Firmware info string
    fw_str = config.firmware
    if config.firmware == "BTFL":
        fw_str = "Betaflight"
    elif config.firmware == "INAV":
        fw_str = "INAV"
    fw_info = f"{fw_str} {config.firmware_version}"
    if board_name:
        fw_info += f" on {board_name}"

    # Match components
    fc_match = _match_fc(board_name, components)
    rx_match = _match_receiver(serialrx, components)
    esc_match = _match_esc(motor_protocol, components)
    vtx_match = _match_vtx(vtx_info, components)

    # Build detection details for display
    detection: dict[str, Any] = {
        "board_name": board_name,
        "serialrx_provider": serialrx,
        "motor_protocol": motor_protocol,
        "vtx_type": vtx_info["type"],
        "vtx_detail": vtx_info["detail"],
        "firmware": fw_info,
        "motor_count": motor_count,
        "craft_name": craft_name,
        "fc_match": fc_match,
        "rx_match": rx_match,
        "esc_match": esc_match,
        "vtx_match": vtx_match,
    }

    # Count matched slots
    matched_slots = sum(1 for m in [fc_match, rx_match, esc_match, vtx_match] if m)

    # Build fleet drone dict
    drone_data: dict[str, Any] = {
        "name": drone_name,
        "drone_class": "5inch_freestyle",
        "status": "building",
        "notes": f"Auto-created from FC config: {fw_info}",
        "tags": _build_tags(config, vtx_info, serialrx),
    }

    # Assign matched component IDs (or custom fallback)
    if fc_match:
        drone_data["fc"] = fc_match["id"]
    elif board_name:
        drone_data["fc"] = _custom_component(
            "fc", f"detected_fc_{board_name.lower()}",
            model=board_name,
        )

    if rx_match:
        drone_data["receiver"] = rx_match["id"]
    elif serialrx:
        drone_data["receiver"] = _custom_component(
            "receiver", f"detected_rx_{serialrx.lower()}",
            model=f"Unknown {serialrx} Receiver",
            specs={"output_protocol": serialrx},
        )

    if esc_match:
        drone_data["esc"] = esc_match["id"]
    elif motor_protocol:
        drone_data["esc"] = _custom_component(
            "esc", f"detected_esc_{motor_protocol.lower()}",
            model=f"Unknown {motor_protocol} ESC",
            specs={"protocol": motor_protocol},
        )

    if vtx_match:
        drone_data["vtx"] = vtx_match["id"]
    elif vtx_info["type"] != "none":
        drone_data["vtx"] = _custom_component(
            "vtx", f"detected_vtx_{vtx_info['type']}",
            model=f"Unknown {vtx_info['type'].title()} VTX ({vtx_info['detail']})",
            specs={"type": f"{vtx_info['type'].title()}", "control": vtx_info["detail"]},
        )

    # Attach detection metadata (not saved to fleet JSON, used for display)
    drone_data["_detection"] = detection
    drone_data["_matched_slots"] = matched_slots

    return drone_data
