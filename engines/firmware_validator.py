"""Firmware cross-validation — validate FC config against component build."""

from __future__ import annotations

from typing import Callable

from core.models import Build, Severity, ValidationResult
from engines.compatibility import ValidationReport
from fc_serial.models import FCConfig


# ---------------------------------------------------------------------------
# Protocol mapping helpers
# ---------------------------------------------------------------------------

# Map FC motor_pwm_protocol setting values to ESC protocol spec values
_MOTOR_PROTOCOL_MAP: dict[str, set[str]] = {
    "DSHOT600": {"DShot600", "DShot1200"},
    "DSHOT300": {"DShot300", "DShot600", "DShot1200"},
    "DSHOT150": {"DShot150", "DShot300", "DShot600", "DShot1200"},
    "DSHOT1200": {"DShot1200"},
    "MULTISHOT": {"Multishot", "DShot150", "DShot300", "DShot600", "DShot1200"},
    "ONESHOT125": {"Oneshot125", "Oneshot42", "Multishot", "DShot150", "DShot300", "DShot600", "DShot1200"},
    "ONESHOT42": {"Oneshot42", "Multishot", "DShot150", "DShot300", "DShot600", "DShot1200"},
    "PWM": {"PWM", "Oneshot125", "Oneshot42", "Multishot", "DShot150", "DShot300", "DShot600", "DShot1200"},
}

# Map FC serialrx_provider values to receiver output_protocol spec values
_SERIALRX_MAP: dict[str, set[str]] = {
    "CRSF": {"CRSF"},
    "SBUS": {"SBUS"},
    "IBUS": {"IBUS"},
    "SPEKTRUM1024": {"DSMX", "DSM2"},
    "SPEKTRUM2048": {"DSMX", "DSM2"},
    "SUMD": {"SUMD"},
    "SUMH": {"SUMH"},
    "FPORT": {"FPORT"},
    "GHST": {"GHST"},
}


def _result(
    check_id: str,
    name: str,
    severity: Severity,
    passed: bool,
    message: str,
) -> ValidationResult:
    return ValidationResult(
        constraint_id=check_id,
        constraint_name=name,
        severity=severity,
        passed=passed,
        message=message,
    )


# ---------------------------------------------------------------------------
# Individual checks (fw_001 .. fw_020)
# ---------------------------------------------------------------------------


def _check_motor_protocol(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_001: Motor protocol in FC matches ESC protocol."""
    esc = build.get_component("esc")
    if not esc:
        return None

    fc_protocol = config.get_setting("motor_pwm_protocol", "").upper()
    esc_protocol = esc.get("protocol", "")

    if not fc_protocol or not esc_protocol:
        return None

    compatible = _MOTOR_PROTOCOL_MAP.get(fc_protocol, set())
    if esc_protocol in compatible:
        return _result("fw_001", "Motor protocol match", Severity.CRITICAL, True,
                        f"FC protocol {fc_protocol} is compatible with ESC {esc_protocol}")

    return _result("fw_001", "Motor protocol match", Severity.CRITICAL, False,
                    f"FC motor protocol {fc_protocol} does not match ESC protocol {esc_protocol} — motors may not spin")


def _check_blheli_s_dshot1200(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_002: BLHeli_S ESCs cannot run DShot1200."""
    esc = build.get_component("esc")
    if not esc:
        return None

    esc_firmware = esc.get("firmware", "")
    fc_protocol = config.get_setting("motor_pwm_protocol", "").upper()

    if esc_firmware != "BLHeli_S" or fc_protocol != "DSHOT1200":
        return None

    return _result("fw_002", "BLHeli_S DShot1200 incompatibility", Severity.CRITICAL, False,
                    f"BLHeli_S ESCs cannot run DShot1200 — use DShot600 or lower, or upgrade to BLHeli_32/AM32")


def _check_bidir_dshot(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_003: Bidirectional DShot needs BLHeli_32 or AM32."""
    bidir = config.get_setting("dshot_bidir")
    if bidir != "ON":
        return None

    esc = build.get_component("esc")
    if not esc:
        return None

    esc_firmware = esc.get("firmware", "")
    if esc_firmware in ("BLHeli_32", "AM32"):
        return _result("fw_003", "Bidirectional DShot firmware", Severity.WARNING, True,
                        f"Bidirectional DShot enabled with compatible {esc_firmware} ESC firmware")

    return _result("fw_003", "Bidirectional DShot firmware", Severity.WARNING, False,
                    f"Bidirectional DShot requires BLHeli_32 or AM32, but ESC has {esc_firmware}")


def _check_receiver_protocol(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_004: serialrx_provider matches receiver output protocol."""
    rx = build.get_component("receiver")
    if not rx:
        return None

    fc_serialrx = config.get_setting("serialrx_provider", "").upper()
    rx_protocol = rx.get("output_protocol", "")

    if not fc_serialrx or not rx_protocol:
        return None

    compatible = _SERIALRX_MAP.get(fc_serialrx, set())
    if rx_protocol in compatible:
        return _result("fw_004", "Receiver protocol match", Severity.CRITICAL, True,
                        f"FC serial RX provider {fc_serialrx} matches receiver protocol {rx_protocol}")

    return _result("fw_004", "Receiver protocol match", Severity.CRITICAL, False,
                    f"FC serial RX provider {fc_serialrx} does not match receiver protocol {rx_protocol} — no RC input")


def _check_receiver_uart(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_005: A serial port must have SERIAL_RX function assigned."""
    rx = build.get_component("receiver")
    if not rx:
        return None

    if not config.serial_ports:
        return None

    rx_port = config.get_serial_port_with_function("SERIAL_RX")
    if rx_port:
        return _result("fw_005", "Receiver UART assigned", Severity.CRITICAL, True,
                        f"SERIAL_RX assigned to UART {rx_port.port_id}")

    return _result("fw_005", "Receiver UART assigned", Severity.CRITICAL, False,
                    "No UART has SERIAL_RX function — receiver will not work. Assign serial RX in Ports tab.")


def _check_sbus_inversion(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_006: SBUS on F4 boards needs software inversion."""
    rx = build.get_component("receiver")
    fc = build.get_component("fc")
    if not rx or not fc:
        return None

    rx_protocol = rx.get("output_protocol", "")
    if rx_protocol != "SBUS":
        return None

    mcu = fc.get("mcu", "")
    if "F405" not in mcu and "F411" not in mcu:
        return None

    serialrx_inverted = config.get_setting("serialrx_inverted", "OFF")
    if serialrx_inverted == "ON":
        return _result("fw_006", "SBUS inversion on F4", Severity.WARNING, True,
                        "SBUS inversion enabled for F4 board")

    return _result("fw_006", "SBUS inversion on F4", Severity.WARNING, False,
                    f"SBUS on {mcu} needs set serialrx_inverted = ON — F4 boards lack hardware inversion")


def _check_vtx_uart(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_007: SmartAudio/Tramp VTX should have a UART for control."""
    vtx = build.get_component("vtx")
    if not vtx:
        return None

    vtx_system = vtx.get("system", "").lower()
    vtx_type = vtx.get("type", "").lower()

    # Only applies to analog VTX with SmartAudio/Tramp
    if "digital" in vtx_type:
        return None

    if not config.serial_ports:
        return None

    sa_port = config.get_serial_port_with_function("VTX_SMARTAUDIO")
    tramp_port = config.get_serial_port_with_function("VTX_TRAMP")

    if sa_port or tramp_port:
        port = sa_port or tramp_port
        return _result("fw_007", "VTX UART assigned", Severity.WARNING, True,
                        f"VTX control UART assigned to port {port.port_id}")

    return _result("fw_007", "VTX UART assigned", Severity.WARNING, False,
                    "No UART assigned for VTX control (SmartAudio/Tramp) — you won't be able to change VTX settings from OSD")


def _check_dji_msp(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_008: DJI/HDZero/Walksnail VTX needs MSP DisplayPort on a UART."""
    vtx = build.get_component("vtx")
    if not vtx:
        return None

    vtx_system = vtx.get("system", "").lower()
    vtx_type = vtx.get("type", "").lower()

    needs_msp = any(kw in vtx_system for kw in ("dji", "hdzero", "walksnail", "avatar"))
    if not needs_msp and "digital" not in vtx_type:
        return None
    if not needs_msp:
        return None

    if not config.serial_ports:
        return None

    msp_port = config.get_serial_port_with_function("VTX_MSP")
    displayport = config.get_serial_port_with_function("MSP_DISPLAYPORT")

    if msp_port or displayport:
        port = msp_port or displayport
        return _result("fw_008", "Digital VTX MSP DisplayPort", Severity.CRITICAL, True,
                        f"MSP/DisplayPort assigned to UART {port.port_id} for digital VTX")

    return _result("fw_008", "Digital VTX MSP DisplayPort", Severity.CRITICAL, False,
                    f"{vtx.get('system', 'Digital')} VTX needs MSP DisplayPort on a UART — no OSD will be displayed")


def _check_vtx_type_match(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_009: FC VTX table type should match VTX hardware."""
    vtx = build.get_component("vtx")
    if not vtx:
        return None

    vtx_type_setting = config.get_setting("vtx_table_bands")
    if not vtx_type_setting:
        return None

    vtx_system = vtx.get("system", "").lower()
    vtx_hw_type = vtx.get("type", "").lower()

    if "digital" in vtx_hw_type and int(vtx_type_setting) > 0:
        return _result("fw_009", "VTX type match", Severity.WARNING, True,
                        "VTX table configured for digital VTX")

    return None


def _check_battery_min_voltage(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_010: vbat_min_cell_voltage should be in reasonable range."""
    min_v = config.get_setting("vbat_min_cell_voltage")
    if not min_v:
        return None

    try:
        min_val = int(min_v)
    except ValueError:
        return None

    if 310 <= min_val <= 360:
        return _result("fw_010", "Battery min cell voltage", Severity.WARNING, True,
                        f"Min cell voltage {min_val / 100:.2f}V is reasonable")

    if min_val < 310:
        return _result("fw_010", "Battery min cell voltage", Severity.WARNING, False,
                        f"Min cell voltage {min_val / 100:.2f}V is dangerously low — risk of over-discharging LiPo")

    return _result("fw_010", "Battery min cell voltage", Severity.WARNING, False,
                    f"Min cell voltage {min_val / 100:.2f}V is unusually high — will land early unnecessarily")


def _check_battery_cell_count(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_011: FC cell detection should match battery cell_count."""
    battery = build.get_component("battery")
    if not battery:
        return None

    bat_cells = battery.get("cell_count")
    if not bat_cells:
        return None

    max_v = config.get_setting("vbat_max_cell_voltage")
    if not max_v:
        return None

    try:
        max_val = int(max_v)
    except ValueError:
        return None

    # Betaflight stores cell voltage in units of 0.01V
    # A value of 430 = 4.30V which is a valid max per cell
    if 410 <= max_val <= 440:
        return _result("fw_011", "Battery cell detection", Severity.WARNING, True,
                        f"Max cell voltage {max_val / 100:.2f}V is reasonable for {bat_cells}S battery")

    return _result("fw_011", "Battery cell detection", Severity.WARNING, False,
                    f"Max cell voltage {max_val / 100:.2f}V may cause incorrect cell count detection for {bat_cells}S battery")


def _check_pid_loop_rate(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_012: PID process denominator should be adequate for DShot protocol."""
    pid_denom = config.get_setting("pid_process_denom")
    fc_protocol = config.get_setting("motor_pwm_protocol", "").upper()

    if not pid_denom:
        return None

    try:
        denom = int(pid_denom)
    except ValueError:
        return None

    # DShot1200 needs low denominator (fast loop)
    if fc_protocol == "DSHOT1200" and denom > 2:
        return _result("fw_012", "PID loop rate for DShot", Severity.WARNING, False,
                        f"DShot1200 performs best with pid_process_denom <= 2, currently {denom}")

    if fc_protocol in ("DSHOT600", "DSHOT300") and denom > 4:
        return _result("fw_012", "PID loop rate for DShot", Severity.WARNING, False,
                        f"{fc_protocol} works best with pid_process_denom <= 4, currently {denom}")

    return _result("fw_012", "PID loop rate for DShot", Severity.WARNING, True,
                    f"PID loop rate (denom={denom}) adequate for {fc_protocol}")


def _check_gyro_filter(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_013: Gyro LPF1 frequency reasonable for quad size."""
    lpf1 = config.get_setting("gyro_lpf1_static_hz")
    if not lpf1:
        return None

    try:
        lpf1_hz = int(lpf1)
    except ValueError:
        return None

    drone_class = build.drone_class

    if lpf1_hz == 0:
        return _result("fw_013", "Gyro filter range", Severity.INFO, True,
                        "Gyro LPF1 disabled (using dynamic filtering)")

    if "whoop" in drone_class and lpf1_hz > 200:
        return _result("fw_013", "Gyro filter range", Severity.INFO, False,
                        f"Gyro LPF1 at {lpf1_hz}Hz is high for a whoop — consider 100-150Hz")

    if "7inch" in drone_class and lpf1_hz > 200:
        return _result("fw_013", "Gyro filter range", Severity.INFO, False,
                        f"Gyro LPF1 at {lpf1_hz}Hz may be too high for 7\" — consider 100-150Hz")

    return _result("fw_013", "Gyro filter range", Severity.INFO, True,
                    f"Gyro LPF1 at {lpf1_hz}Hz is reasonable for {drone_class}")


def _check_rpm_filtering(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_014: RPM filter recommendation when bidir DShot + BLHeli_32 available."""
    bidir = config.get_setting("dshot_bidir")
    rpm_filter = config.get_setting("rpm_filter_harmonics")

    if bidir != "ON":
        return None

    esc = build.get_component("esc")
    if not esc:
        return None

    esc_firmware = esc.get("firmware", "")
    if esc_firmware not in ("BLHeli_32", "AM32"):
        return None

    if rpm_filter and int(rpm_filter) > 0:
        return _result("fw_014", "RPM filtering", Severity.INFO, True,
                        f"RPM filtering enabled with {rpm_filter} harmonics — good for noise reduction")

    return _result("fw_014", "RPM filtering", Severity.INFO, False,
                    "Bidirectional DShot is enabled with BLHeli_32/AM32 but RPM filtering is off — enable for better filtering")


def _check_osd_feature(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_015: OSD feature should be enabled if VTX supports it."""
    vtx = build.get_component("vtx")
    fc = build.get_component("fc")
    if not vtx or not fc:
        return None

    fc_osd = fc.get("osd", "")
    if not fc_osd or fc_osd == "none":
        return None

    if config.has_feature("OSD"):
        return _result("fw_015", "OSD feature", Severity.WARNING, True,
                        "OSD feature enabled")

    return _result("fw_015", "OSD feature", Severity.WARNING, False,
                    "FC has OSD chip but OSD feature is disabled — enable it to see telemetry overlay")


def _check_telemetry_feature(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_016: TELEMETRY feature should match receiver capability."""
    rx = build.get_component("receiver")
    if not rx:
        return None

    has_telemetry = rx.get("telemetry", False)
    if not has_telemetry:
        return None

    if config.has_feature("TELEMETRY"):
        return _result("fw_016", "Telemetry feature", Severity.INFO, True,
                        "TELEMETRY feature enabled — receiver supports telemetry")

    return _result("fw_016", "Telemetry feature", Severity.INFO, False,
                    "Receiver supports telemetry but TELEMETRY feature is disabled — enable for battery/RSSI on TX")


def _check_esc_sensor(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_017: ESC_SENSOR feature when ESC has current sensor."""
    esc = build.get_component("esc")
    if not esc:
        return None

    has_sensor = esc.get("current_sensor", False)
    if not has_sensor:
        return None

    esc_sensor_port = config.get_serial_port_with_function("ESC_SENSOR")

    if esc_sensor_port:
        return _result("fw_017", "ESC sensor feature", Severity.INFO, True,
                        f"ESC sensor on UART {esc_sensor_port.port_id} — per-motor telemetry available")

    return _result("fw_017", "ESC sensor feature", Severity.INFO, False,
                    "ESC has current sensor but no UART assigned for ESC_SENSOR — per-motor telemetry unavailable")


def _check_serial_conflicts(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_018: No conflicting function assignments on same UART."""
    if not config.serial_ports:
        return None

    # Functions that conflict with each other on the same port
    conflicts = []
    for port in config.serial_ports:
        active = [f for f in port.functions if f != "UNUSED"]
        # MSP can coexist with some functions, but most pairs conflict
        conflicting_pairs = []
        for i, f1 in enumerate(active):
            for f2 in active[i + 1:]:
                # GPS + SERIAL_RX on same UART is always a conflict
                # Two RX-type functions on same UART conflict
                if {f1, f2} & {"SERIAL_RX", "GPS"} == {"SERIAL_RX", "GPS"}:
                    conflicting_pairs.append((f1, f2))
                elif f1.startswith("VTX_") and f2.startswith("VTX_"):
                    conflicting_pairs.append((f1, f2))
                elif f1.startswith("TELEMETRY_") and f2.startswith("TELEMETRY_"):
                    conflicting_pairs.append((f1, f2))

        if conflicting_pairs:
            for f1, f2 in conflicting_pairs:
                conflicts.append(f"UART{port.port_id}: {f1} + {f2}")

    if conflicts:
        return _result("fw_018", "Serial port conflicts", Severity.CRITICAL, False,
                        f"Conflicting serial assignments: {'; '.join(conflicts)}")

    return _result("fw_018", "Serial port conflicts", Severity.CRITICAL, True,
                    "No conflicting serial port assignments")


def _check_inav_nav_settings(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_019: iNav navigation settings reasonable for drone class."""
    if config.firmware != "INAV":
        return None

    nav_max_speed = config.get_setting("nav_mc_vel_xy_max")
    if not nav_max_speed:
        return None

    drone_class = build.drone_class
    try:
        speed = int(nav_max_speed)
    except ValueError:
        return None

    if "7inch" in drone_class or "lr" in drone_class:
        if speed < 500:
            return _result("fw_019", "iNav nav speed settings", Severity.WARNING, False,
                            f"nav_mc_vel_xy_max={speed} is low for long range — consider 800-1200")
        return _result("fw_019", "iNav nav speed settings", Severity.WARNING, True,
                        f"Nav speed {speed} cm/s is reasonable for {drone_class}")

    if "whoop" in drone_class and speed > 800:
        return _result("fw_019", "iNav nav speed settings", Severity.WARNING, False,
                        f"nav_mc_vel_xy_max={speed} is high for a whoop — consider 300-500")

    return None


def _check_inav_fixed_wing(config: FCConfig, build: Build) -> ValidationResult | None:
    """fw_020: iNav fixed-wing settings for flying_wing class."""
    if config.firmware != "INAV":
        return None

    if build.drone_class != "flying_wing":
        return None

    platform = config.get_setting("platform_type")
    if not platform:
        return None

    if platform.upper() in ("AIRPLANE", "FLYING_WING"):
        return _result("fw_020", "iNav fixed-wing platform", Severity.WARNING, True,
                        f"Platform type '{platform}' correct for flying wing")

    return _result("fw_020", "iNav fixed-wing platform", Severity.WARNING, False,
                    f"Platform type '{platform}' should be AIRPLANE or FLYING_WING for flying wing drone class")


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

ALL_CHECKS: list[Callable[[FCConfig, Build], ValidationResult | None]] = [
    _check_motor_protocol,       # fw_001
    _check_blheli_s_dshot1200,   # fw_002
    _check_bidir_dshot,          # fw_003
    _check_receiver_protocol,    # fw_004
    _check_receiver_uart,        # fw_005
    _check_sbus_inversion,       # fw_006
    _check_vtx_uart,             # fw_007
    _check_dji_msp,              # fw_008
    _check_vtx_type_match,       # fw_009
    _check_battery_min_voltage,  # fw_010
    _check_battery_cell_count,   # fw_011
    _check_pid_loop_rate,        # fw_012
    _check_gyro_filter,          # fw_013
    _check_rpm_filtering,        # fw_014
    _check_osd_feature,          # fw_015
    _check_telemetry_feature,    # fw_016
    _check_esc_sensor,           # fw_017
    _check_serial_conflicts,     # fw_018
    _check_inav_nav_settings,    # fw_019
    _check_inav_fixed_wing,      # fw_020
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_firmware_config(config: FCConfig, build: Build) -> ValidationReport:
    """Run all firmware cross-validation checks.

    Returns a ValidationReport (same type as the component compatibility engine)
    with constraint IDs prefixed ``fw_`` to avoid collisions.
    """
    report = ValidationReport(build_name=build.name)

    for check_fn in ALL_CHECKS:
        result = check_fn(config, build)
        if result is not None:
            report.results.append(result)

    return report
