"""Symptom-to-check mapping — connects user-reported problems to diagnostic checks."""

from __future__ import annotations

from core.models import Discrepancy, Severity, ValidationResult


# ---------------------------------------------------------------------------
# Symptom labels (ID → human-readable description)
# ---------------------------------------------------------------------------

SYMPTOMS: dict[str, str] = {
    "motors_wont_spin": "Motors won't spin / ESC not initializing",
    "flips_on_takeoff": "Drone flips on takeoff",
    "no_video": "No video / OSD not showing",
    "cant_arm": "Can't arm",
    "no_receiver": "No receiver signal",
    "gps_not_working": "GPS not working",
    "bad_vibrations": "Bad vibrations / oscillations",
    "short_flight_time": "Short flight time",
    "failsafe_issues": "Failsafe not working correctly",
    "vtx_not_changing": "VTX not changing channels/power",
}


# ---------------------------------------------------------------------------
# Symptom → relevant check IDs (disc_*, fw_*, YAML constraint IDs)
# ---------------------------------------------------------------------------

SYMPTOM_CHECKS: dict[str, list[str]] = {
    "motors_wont_spin": ["disc_004", "disc_005", "fw_001", "fw_002", "elec_001", "elec_002"],
    "flips_on_takeoff": ["disc_010", "fw_001", "disc_004"],
    "no_video": ["disc_003", "fw_007", "fw_008", "fw_015"],
    "cant_arm": ["disc_002", "fw_005", "fw_018"],
    "no_receiver": ["disc_002", "fw_004", "fw_005", "fw_006"],
    "gps_not_working": ["disc_008", "fw_018"],
    "bad_vibrations": ["fw_012", "fw_013", "fw_014"],
    "short_flight_time": ["disc_006", "fw_010", "fw_011", "elec_005"],
    "failsafe_issues": ["disc_002", "fw_004", "fw_005", "fw_016"],
    "vtx_not_changing": ["disc_003", "fw_007", "fw_008", "fw_009"],
}


# ---------------------------------------------------------------------------
# Fix suggestions per check ID
# ---------------------------------------------------------------------------

FIX_SUGGESTIONS: dict[str, str] = {
    # Firmware validator checks
    "fw_001": "In Betaflight Configurator -> Configuration -> ESC/Motor Features -> set Motor Protocol to match your ESC.",
    "fw_002": "BLHeli_S ESCs cannot run DShot1200. Downgrade to DShot600 or lower, or upgrade ESC to BLHeli_32/AM32.",
    "fw_003": "Bidirectional DShot requires BLHeli_32 or AM32 ESC firmware. Disable bidir DShot or upgrade ESC firmware.",
    "fw_004": "In Betaflight Configurator -> Configuration -> Receiver -> set Serial Receiver Provider to match your RX (e.g. CRSF for ELRS).",
    "fw_005": "In Betaflight Configurator -> Ports tab -> find the UART your receiver is wired to -> enable Serial RX.",
    "fw_006": "SBUS on F4 boards needs inversion. In CLI: set serialrx_inverted = ON",
    "fw_007": "In Betaflight Configurator -> Ports tab -> find the UART your VTX control wire is on -> enable Peripherals: TBS SmartAudio or IRC Tramp.",
    "fw_008": "In Betaflight Configurator -> Ports tab -> find the UART connected to your digital VTX -> enable Peripherals: VTX (MSP+DisplayPort).",
    "fw_009": "Check VTX table settings match your VTX hardware. In Betaflight Configurator -> Video Transmitter tab.",
    "fw_010": "Set vbat_min_cell_voltage to a safe value (330 = 3.30V is standard). In CLI: set vbat_min_cell_voltage = 330",
    "fw_011": "Verify vbat_max_cell_voltage matches your battery. 430 (4.20V) for LiPo, 435 (4.35V) for LiHV.",
    "fw_012": "Lower pid_process_denom for faster PID loop rate. DShot600 works best with denom <= 4.",
    "fw_013": "Adjust gyro_lpf1_static_hz for your quad size. 5\" freestyle: ~150-250Hz, whoop: ~100-150Hz, 7\": ~100-150Hz.",
    "fw_014": "Enable RPM filtering for better motor noise reduction. In CLI: set rpm_filter_harmonics = 3",
    "fw_015": "Enable OSD feature to see telemetry overlay. In Betaflight Configurator -> Configuration -> Other Features -> OSD.",
    "fw_016": "Enable TELEMETRY feature for battery/RSSI on your TX. In Betaflight Configurator -> Configuration -> Other Features -> TELEMETRY.",
    "fw_017": "Assign ESC_SENSOR to a UART in Betaflight Ports tab for per-motor telemetry data.",
    "fw_018": "Fix conflicting serial port assignments. Each UART should have only one primary function. Check Betaflight Ports tab.",
    "fw_019": "Adjust iNav navigation speed settings for your drone class. Long range: 800-1200, whoop: 300-500.",
    "fw_020": "Set platform_type to AIRPLANE or FLYING_WING for fixed-wing drones in iNav.",
    # Discrepancy checks get suggestions from the Discrepancy.fix_suggestion field directly
}


# ---------------------------------------------------------------------------
# Prioritization
# ---------------------------------------------------------------------------

def _get_check_id(item: ValidationResult | Discrepancy) -> str:
    """Extract the check ID from a result or discrepancy."""
    if isinstance(item, Discrepancy):
        return item.id
    return item.constraint_id


def _severity_order(severity: Severity) -> int:
    """Lower number = higher priority."""
    return {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}[severity]


def prioritize_results(
    all_results: list[ValidationResult],
    discrepancies: list[Discrepancy],
    symptoms: list[str],
) -> tuple[list[ValidationResult | Discrepancy], list[ValidationResult | Discrepancy]]:
    """Prioritize findings based on reported symptoms.

    Returns (symptom_relevant, other) where:
    - symptom_relevant: findings whose check ID appears in any reported symptom's check list
    - other: everything else

    Both lists are sorted by severity (CRITICAL > WARNING > INFO), then by check ID.
    """
    # Collect all check IDs relevant to the reported symptoms
    relevant_ids: set[str] = set()
    for symptom in symptoms:
        relevant_ids.update(SYMPTOM_CHECKS.get(symptom, []))

    # Combine failed results and discrepancies into one pool
    all_items: list[ValidationResult | Discrepancy] = []

    for r in all_results:
        if not r.passed:
            all_items.append(r)

    all_items.extend(discrepancies)

    # Partition
    symptom_relevant: list[ValidationResult | Discrepancy] = []
    other: list[ValidationResult | Discrepancy] = []

    for item in all_items:
        check_id = _get_check_id(item)
        if check_id in relevant_ids:
            symptom_relevant.append(item)
        else:
            other.append(item)

    # Sort each group by severity, then ID
    def sort_key(item: ValidationResult | Discrepancy) -> tuple[int, str]:
        return (_severity_order(item.severity), _get_check_id(item))

    symptom_relevant.sort(key=sort_key)
    other.sort(key=sort_key)

    return symptom_relevant, other


def get_fix_suggestion(check_id: str) -> str:
    """Get the fix suggestion for a given check ID."""
    return FIX_SUGGESTIONS.get(check_id, "")
