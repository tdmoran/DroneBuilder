"""Discrepancy detection — compare FC config signals against fleet build record."""

from __future__ import annotations

from typing import Callable

from core.models import Build, Discrepancy, Severity
from engines.firmware_validator import _MOTOR_PROTOCOL_MAP, _SERIALRX_MAP
from fc_serial.models import FCConfig


# ---------------------------------------------------------------------------
# Individual discrepancy checks (disc_001 .. disc_010)
# ---------------------------------------------------------------------------


def _check_fc_board(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_001: FC board mismatch — config board_name vs fleet FC MCU."""
    fc = build.get_component("fc")
    if not fc:
        return None

    fleet_mcu = fc.get("mcu", "")
    board_name = config.board_name
    if not fleet_mcu or not board_name:
        return None

    # Normalise for comparison: e.g. STM32F405 should appear in board_name
    # Board names like "OMNIBUSF4" contain "F4", "MATEKF722" contains "F722"
    fleet_mcu_upper = fleet_mcu.upper()
    board_upper = board_name.upper()

    # Extract the MCU family shorthand from the fleet MCU spec
    # STM32F405 → F405, STM32F722 → F722, STM32H743 → H743, AT32F435 → F435
    mcu_short = fleet_mcu_upper.replace("STM32", "").replace("AT32", "")

    if mcu_short and mcu_short in board_upper:
        return None

    # Also check broader family: F4xx should match F405/F411
    mcu_family = mcu_short[:2] if len(mcu_short) >= 2 else ""
    if mcu_family and mcu_family in board_upper:
        return None

    return Discrepancy(
        id="disc_001",
        component_type="fc",
        category="identity",
        severity=Severity.CRITICAL,
        fleet_value=f"{fc.manufacturer} {fc.model} ({fleet_mcu})",
        detected_value=f"Board: {board_name}",
        message=f"FC board '{board_name}' does not match fleet MCU '{fleet_mcu}' — the flight controller may have been swapped",
        fix_suggestion="If you replaced the FC, update the fleet record with the new FC. If this is the same FC, verify the board_name target in Betaflight Configurator.",
    )


def _check_receiver_protocol(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_002: Receiver protocol mismatch — serialrx_provider vs fleet receiver."""
    rx = build.get_component("receiver")
    if not rx:
        return None

    fc_serialrx = config.get_setting("serialrx_provider", "")
    fleet_protocol = rx.get("output_protocol", "")
    if not fc_serialrx or not fleet_protocol:
        return None

    compatible = _SERIALRX_MAP.get(fc_serialrx.upper(), set())
    if fleet_protocol in compatible:
        return None

    return Discrepancy(
        id="disc_002",
        component_type="receiver",
        category="protocol",
        severity=Severity.CRITICAL,
        fleet_value=f"{rx.manufacturer} {rx.model} ({fleet_protocol})",
        detected_value=f"serialrx_provider = {fc_serialrx}",
        message=f"FC serial RX provider '{fc_serialrx}' does not match fleet receiver protocol '{fleet_protocol}' — receiver may have been swapped",
        fix_suggestion="If you swapped the receiver, update the fleet record. If the FC is misconfigured, change serialrx_provider in Betaflight Configurator → Configuration → Receiver.",
    )


def _check_vtx_type(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_003: VTX type mismatch — analog (SmartAudio/Tramp) vs digital (MSP)."""
    vtx = build.get_component("vtx")
    if not vtx:
        return None

    fleet_type = vtx.get("type", "").lower()
    if not fleet_type:
        return None

    if not config.serial_ports:
        return None

    fleet_is_digital = "digital" in fleet_type

    # Check what the FC config implies
    has_smartaudio = config.get_serial_port_with_function("VTX_SMARTAUDIO") is not None
    has_tramp = config.get_serial_port_with_function("VTX_TRAMP") is not None
    has_vtx_msp = config.get_serial_port_with_function("VTX_MSP") is not None
    has_msp_dp = config.get_serial_port_with_function("MSP_DISPLAYPORT") is not None

    config_is_analog = has_smartaudio or has_tramp
    config_is_digital = has_vtx_msp or has_msp_dp

    # No VTX UART configured — can't determine mismatch
    if not config_is_analog and not config_is_digital:
        return None

    if fleet_is_digital and config_is_analog and not config_is_digital:
        analog_fn = "VTX_SMARTAUDIO" if has_smartaudio else "VTX_TRAMP"
        port = config.get_serial_port_with_function(analog_fn)
        port_id = port.port_id if port else "?"
        return Discrepancy(
            id="disc_003",
            component_type="vtx",
            category="identity",
            severity=Severity.CRITICAL,
            fleet_value=f"{vtx.manufacturer} {vtx.model} ({vtx.get('type', '')})",
            detected_value=f"{analog_fn} on UART {port_id} (Analog VTX)",
            message=f"Fleet says digital VTX but FC has analog VTX control ({analog_fn}) — VTX may have been swapped",
            fix_suggestion="If you swapped to an analog VTX, update the fleet record. If the FC is misconfigured, switch the UART to VTX (MSP+DisplayPort) for digital.",
        )

    if not fleet_is_digital and config_is_digital and not config_is_analog:
        return Discrepancy(
            id="disc_003",
            component_type="vtx",
            category="identity",
            severity=Severity.CRITICAL,
            fleet_value=f"{vtx.manufacturer} {vtx.model} ({vtx.get('type', '')})",
            detected_value="VTX_MSP / MSP_DISPLAYPORT (Digital VTX)",
            message="Fleet says analog VTX but FC has digital VTX control (MSP) — VTX may have been swapped",
            fix_suggestion="If you swapped to a digital VTX, update the fleet record. If the FC is misconfigured, switch the UART to SmartAudio or Tramp for analog.",
        )

    return None


def _check_motor_protocol(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_004: Motor protocol mismatch — FC motor_pwm_protocol vs ESC spec."""
    esc = build.get_component("esc")
    if not esc:
        return None

    fc_protocol = config.get_setting("motor_pwm_protocol", "").upper()
    esc_protocol = esc.get("protocol", "")
    if not fc_protocol or not esc_protocol:
        return None

    compatible = _MOTOR_PROTOCOL_MAP.get(fc_protocol, set())
    if esc_protocol in compatible:
        return None

    return Discrepancy(
        id="disc_004",
        component_type="esc",
        category="protocol",
        severity=Severity.WARNING,
        fleet_value=f"{esc.manufacturer} {esc.model} (supports {esc_protocol})",
        detected_value=f"motor_pwm_protocol = {fc_protocol}",
        message=f"FC motor protocol '{fc_protocol}' is not compatible with fleet ESC protocol '{esc_protocol}' — ESC may have been swapped or FC misconfigured",
        fix_suggestion="If you swapped the ESC, update the fleet record. Otherwise, change motor protocol in Betaflight Configurator → Configuration → ESC/Motor Features.",
    )


def _check_bidir_dshot_firmware(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_005: ESC firmware mismatch — bidir DShot implies BLHeli_32/AM32."""
    bidir = config.get_setting("dshot_bidir")
    if bidir != "ON":
        return None

    esc = build.get_component("esc")
    if not esc:
        return None

    esc_firmware = esc.get("firmware", "")
    if not esc_firmware:
        return None

    if esc_firmware in ("BLHeli_32", "AM32"):
        return None

    return Discrepancy(
        id="disc_005",
        component_type="esc",
        category="feature",
        severity=Severity.WARNING,
        fleet_value=f"{esc.manufacturer} {esc.model} ({esc_firmware})",
        detected_value="dshot_bidir = ON (requires BLHeli_32 or AM32)",
        message=f"Bidirectional DShot is enabled but fleet ESC has {esc_firmware} firmware — ESC may have been upgraded or swapped",
        fix_suggestion="If you upgraded/swapped the ESC to BLHeli_32 or AM32, update the fleet record. If the fleet record is correct, disable bidirectional DShot.",
    )


def _check_battery_cells(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_006: Battery cell count mismatch — vbat_max_cell_voltage range vs fleet battery."""
    battery = build.get_component("battery")
    if not battery:
        return None

    fleet_cells = battery.get("cell_count")
    if not fleet_cells:
        return None

    # Check if FC voltage scale suggests a different cell count
    # We look at vbat_warning_cell_voltage as a cross-check
    warn_v = config.get_setting("vbat_warning_cell_voltage")
    max_v = config.get_setting("vbat_max_cell_voltage")

    if not max_v:
        return None

    try:
        max_val = int(max_v)
    except ValueError:
        return None

    # Betaflight stores voltage in centivolt (430 = 4.30V)
    # Standard LiPo max: 4.20V (420), HV LiPo: 4.35V (435)
    # If max_cell_voltage is way off, the cell count detection may be wrong
    # but this check is specifically about cell count inference
    # We can't directly infer cell count from these settings — this is more of a
    # sanity check. The real check would be comparing actual measured voltage.
    # For now, check if the max voltage setting is unreasonable for the fleet battery type.

    # HV LiPo check
    battery_type = battery.get("chemistry", "LiPo")
    if battery_type == "LiHV" and max_val < 430:
        return Discrepancy(
            id="disc_006",
            component_type="battery",
            category="feature",
            severity=Severity.WARNING,
            fleet_value=f"{fleet_cells}S {battery_type} (max 4.35V/cell)",
            detected_value=f"vbat_max_cell_voltage = {max_val / 100:.2f}V",
            message=f"Fleet battery is {battery_type} (4.35V/cell max) but FC max cell voltage is {max_val / 100:.2f}V — battery type may have changed",
            fix_suggestion="If you switched to HV LiPo, set vbat_max_cell_voltage to 435 in CLI. If still using standard LiPo, update the fleet record.",
        )

    if battery_type != "LiHV" and max_val >= 435:
        return Discrepancy(
            id="disc_006",
            component_type="battery",
            category="feature",
            severity=Severity.WARNING,
            fleet_value=f"{fleet_cells}S {battery_type} (max 4.20V/cell)",
            detected_value=f"vbat_max_cell_voltage = {max_val / 100:.2f}V (HV LiPo setting)",
            message=f"Fleet battery is standard {battery_type} but FC is set for HV LiPo ({max_val / 100:.2f}V/cell) — battery may have been swapped",
            fix_suggestion="If you switched to HV LiPo, update the fleet battery record. Otherwise, set vbat_max_cell_voltage to 430 in CLI.",
        )

    return None


def _check_craft_name(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_007: Craft name mismatch — FC craft_name vs build name/nickname."""
    craft_name = config.get_setting("name", "")
    if not craft_name:
        # Also try craft_name setting
        craft_name = config.get_setting("craft_name", "")
    if not craft_name:
        return None

    build_name = build.name.lower().strip()
    build_nickname = build.nickname.lower().strip()
    craft_lower = craft_name.lower().strip()

    if craft_lower == build_name or craft_lower == build_nickname:
        return None

    # Partial match — craft name contained in build name or vice versa
    if craft_lower in build_name or build_name in craft_lower:
        return None
    if build_nickname and (craft_lower in build_nickname or build_nickname in craft_lower):
        return None

    return Discrepancy(
        id="disc_007",
        component_type="fc",
        category="identity",
        severity=Severity.INFO,
        fleet_value=f"'{build.name}'" + (f" / '{build.nickname}'" if build.nickname else ""),
        detected_value=f"craft_name = '{craft_name}'",
        message=f"FC craft name '{craft_name}' does not match fleet drone name — may indicate a different drone",
        fix_suggestion="Update the craft name in Betaflight CLI: set name = YOUR_DRONE_NAME",
    )


def _check_gps_presence(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_008: GPS presence mismatch — FC GPS feature/UART vs fleet GPS component."""
    fleet_has_gps = build.get_component("gps") is not None

    config_has_gps_feature = config.has_feature("GPS")
    config_has_gps_uart = config.get_serial_port_with_function("GPS") is not None

    config_has_gps = config_has_gps_feature or config_has_gps_uart

    if fleet_has_gps == config_has_gps:
        return None

    if fleet_has_gps and not config_has_gps:
        gps = build.get_component("gps")
        return Discrepancy(
            id="disc_008",
            component_type="gps",
            category="feature",
            severity=Severity.INFO,
            fleet_value=f"GPS: {gps.manufacturer} {gps.model}" if gps else "GPS present",
            detected_value="No GPS feature or UART configured",
            message="Fleet has a GPS component but FC has no GPS configured — GPS may have been removed",
            fix_suggestion="If you removed the GPS, remove it from the fleet record. If GPS should be active, enable GPS feature and assign a UART.",
        )

    return Discrepancy(
        id="disc_008",
        component_type="gps",
        category="feature",
        severity=Severity.INFO,
        fleet_value="No GPS in fleet record",
        detected_value="GPS feature/UART configured in FC",
        message="FC has GPS configured but fleet record has no GPS component — GPS may have been added",
        fix_suggestion="If you added a GPS module, add it to the fleet record.",
    )


def _check_esc_telemetry(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_009: ESC telemetry mismatch — ESC_SENSOR feature vs fleet ESC current_sensor."""
    esc = build.get_component("esc")
    if not esc:
        return None

    fleet_has_sensor = esc.get("current_sensor", False)
    config_has_esc_sensor = config.has_feature("ESC_SENSOR") or (
        config.get_serial_port_with_function("ESC_SENSOR") is not None
    )

    if fleet_has_sensor == config_has_esc_sensor:
        return None

    if fleet_has_sensor and not config_has_esc_sensor:
        return Discrepancy(
            id="disc_009",
            component_type="esc",
            category="feature",
            severity=Severity.INFO,
            fleet_value=f"{esc.manufacturer} {esc.model} (has current sensor)",
            detected_value="ESC_SENSOR not enabled",
            message="Fleet ESC has current sensor but FC doesn't have ESC_SENSOR enabled — may be intentionally unused",
            fix_suggestion="To enable per-motor telemetry, assign ESC_SENSOR to a UART in Betaflight Ports tab.",
        )

    return Discrepancy(
        id="disc_009",
        component_type="esc",
        category="feature",
        severity=Severity.INFO,
        fleet_value=f"{esc.manufacturer} {esc.model} (no current sensor listed)",
        detected_value="ESC_SENSOR is enabled",
        message="FC has ESC_SENSOR enabled but fleet ESC doesn't list a current sensor — ESC may have been upgraded",
        fix_suggestion="If you upgraded the ESC, update the fleet record with current_sensor: true.",
    )


def _check_motor_count(config: FCConfig, build: Build) -> Discrepancy | None:
    """disc_010: Motor count mismatch — MOTOR resource mappings vs build motor_count."""
    if not config.resource_mappings:
        return None

    # Count MOTOR resource entries
    motor_resources = [
        k for k in config.resource_mappings
        if k.startswith("MOTOR ")
    ]
    config_motor_count = len(motor_resources)

    if config_motor_count == 0:
        return None

    fleet_motor_count = build.motor_count

    if config_motor_count == fleet_motor_count:
        return None

    return Discrepancy(
        id="disc_010",
        component_type="motor",
        category="identity",
        severity=Severity.WARNING,
        fleet_value=f"{fleet_motor_count} motors",
        detected_value=f"{config_motor_count} MOTOR resource mappings",
        message=f"FC has {config_motor_count} motor outputs configured but fleet has {fleet_motor_count} motors — frame or motor setup may have changed",
        fix_suggestion="If the motor count changed (e.g. quad to hex), update the fleet record's drone class and motors.",
    )


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

ALL_DISCREPANCY_CHECKS: list[Callable[[FCConfig, Build], Discrepancy | None]] = [
    _check_fc_board,               # disc_001
    _check_receiver_protocol,      # disc_002
    _check_vtx_type,               # disc_003
    _check_motor_protocol,         # disc_004
    _check_bidir_dshot_firmware,   # disc_005
    _check_battery_cells,          # disc_006
    _check_craft_name,             # disc_007
    _check_gps_presence,           # disc_008
    _check_esc_telemetry,          # disc_009
    _check_motor_count,            # disc_010
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_discrepancies(config: FCConfig, build: Build) -> list[Discrepancy]:
    """Compare FC config against fleet build, return all detected discrepancies."""
    discrepancies: list[Discrepancy] = []

    for check_fn in ALL_DISCREPANCY_CHECKS:
        result = check_fn(config, build)
        if result is not None:
            discrepancies.append(result)

    return discrepancies
