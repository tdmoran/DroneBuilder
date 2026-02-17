"""Symptom-to-check mapping — connects user-reported problems to diagnostic checks."""

from __future__ import annotations

from core.models import Discrepancy, Severity, ValidationResult


# ---------------------------------------------------------------------------
# Symptom labels (ID → human-readable description)
# ---------------------------------------------------------------------------

SYMPTOMS: dict[str, str] = {
    "cant_arm": "Will not arm",
    "motors_wont_spin": "Motors won't spin / ESC not initializing",
    "flips_on_takeoff": "Flips on takeoff",
    "no_video": "No video / OSD not showing",
    "no_receiver": "No receiver signal",
    "low_range": "Low range / signal drops",
    "gps_not_working": "GPS not working",
    "rth_not_working": "Return to home not working",
    "bad_vibrations": "Bad vibrations / oscillations",
    "short_flight_time": "Short flight time",
    "failsafe_issues": "Failsafe not working correctly",
    "vtx_not_changing": "VTX not changing channels/power",
    "compass_drift": "Compass / heading drift",
    "altitude_hold_issues": "Altitude hold not working",
}


# ---------------------------------------------------------------------------
# Symptom descriptions — detailed human-readable explanation for each symptom
# ---------------------------------------------------------------------------

SYMPTOM_DESCRIPTIONS: dict[str, str] = {
    "cant_arm": (
        "Motors do not arm when the arm switch is activated. The drone stays "
        "disarmed with no motor response. Common causes include receiver issues, "
        "arming switch misconfiguration, or pre-arm safety checks failing."
    ),
    "motors_wont_spin": (
        "Motors do not spin when armed, or spin briefly then stop. ESCs may "
        "fail to initialize (no startup tones). Usually caused by motor protocol "
        "mismatch, ESC wiring issues, or voltage incompatibility."
    ),
    "flips_on_takeoff": (
        "Drone flips violently immediately on takeoff, crashing within the "
        "first second. Caused by reversed motor direction, wrong motor order, "
        "or incorrect motor protocol settings."
    ),
    "no_video": (
        "No video feed in goggles or monitor. Screen is black, shows static, "
        "or OSD elements are missing. Can be caused by VTX UART misconfiguration, "
        "wrong video system settings, or MSP DisplayPort issues."
    ),
    "no_receiver": (
        "Flight controller shows no receiver connection. RC channels show zero "
        "or no movement in Betaflight receiver tab. Caused by wrong UART assignment, "
        "incorrect serial RX protocol, or SBUS inversion issues on F4 boards."
    ),
    "low_range": (
        "Radio control range is significantly shorter than expected. Signal "
        "drops or failsafes occur at close range. Often caused by receiver "
        "protocol mismatch, antenna issues, or telemetry configuration problems."
    ),
    "gps_not_working": (
        "GPS module shows no satellites or no position fix. GPS features like "
        "rescue mode are unavailable. Caused by missing GPS UART assignment, "
        "GPS feature not enabled, or serial port conflicts."
    ),
    "rth_not_working": (
        "Return-to-home or GPS rescue does not activate or flies erratically. "
        "May be caused by GPS issues, navigation settings misconfiguration, "
        "or missing feature flags in firmware."
    ),
    "bad_vibrations": (
        "Drone vibrates excessively, video shows jello effect, or flight is "
        "unstable with oscillations. Caused by PID tuning issues, inadequate "
        "gyro filtering, or RPM filtering not enabled."
    ),
    "short_flight_time": (
        "Flight time is much shorter than expected for the battery capacity. "
        "Battery lands warning triggers too early or too late. Can be caused "
        "by incorrect voltage thresholds, battery mismatch, or excessive current draw."
    ),
    "failsafe_issues": (
        "Failsafe does not trigger when signal is lost, or triggers unexpectedly "
        "during normal flight. Often caused by receiver protocol mismatch, "
        "telemetry configuration, or UART assignment issues."
    ),
    "vtx_not_changing": (
        "VTX channel, power, or band cannot be changed from the OSD or radio. "
        "SmartAudio or Tramp controls do not respond. Usually caused by missing "
        "VTX UART assignment or wrong VTX table settings."
    ),
    "compass_drift": (
        "Compass heading drifts or is inaccurate. The drone rotates slowly "
        "in position hold or heading is wrong on the map. Caused by GPS/compass "
        "configuration issues or serial port conflicts."
    ),
    "altitude_hold_issues": (
        "Altitude hold mode does not maintain height, drifts up or down, "
        "or is unavailable. Caused by barometer/GPS configuration issues "
        "or incorrect navigation settings for the drone class."
    ),
}


# ---------------------------------------------------------------------------
# Fuzzy symptom matching — keyword index
# ---------------------------------------------------------------------------

_SYMPTOM_KEYWORDS: dict[str, list[str]] = {
    "cant_arm": [
        "arm", "wont arm", "won't arm", "not arming", "cant arm", "can't arm",
        "arming", "disarmed", "failsafe arming", "arm switch", "wont disarm",
        "refuses to arm", "unable to arm", "arming disabled", "arming prevention",
    ],
    "motors_wont_spin": [
        "motor", "spin", "not spinning", "wont spin", "won't spin",
        "motors dead", "no motor", "props not turning", "propellers not spinning",
        "esc not initializing", "esc beeping", "esc no tones", "motor not responding",
        "props wont spin", "motors stopped", "motors not working",
    ],
    "flips_on_takeoff": [
        "flip", "flips", "flips on takeoff", "flip on arm", "flip on takeoff",
        "crashes immediately", "death roll", "tumble", "rolls over",
        "yaw spin", "flips over", "instant crash", "takes off sideways",
    ],
    "no_video": [
        "video", "no video", "black screen", "no image", "vtx", "osd",
        "blank goggles", "no feed", "static", "no osd", "no display",
        "video black", "goggles black", "no picture", "video lost",
        "screen blank", "no fpv", "fpv black",
    ],
    "no_receiver": [
        "receiver", "no receiver", "rx not working", "no rc", "no signal",
        "rc input", "no channels", "receiver not detected", "rx dead",
        "no rx", "rc not connected", "receiver disconnected", "sbus",
        "crsf not working", "elrs not binding", "no rc input",
    ],
    "low_range": [
        "range", "low range", "signal drop", "signal loss", "failsafe range",
        "short range", "rssi low", "rssi drops", "link quality", "lq drops",
        "connection drops", "drops out", "radio range", "antenna range",
    ],
    "gps_not_working": [
        "gps", "no gps", "gps fix", "no satellites", "satellite",
        "gps not found", "position", "no position", "gps module",
        "ublox", "gps lock", "gps search", "no gps signal",
    ],
    "rth_not_working": [
        "rth", "return to home", "return home", "gps rescue", "rescue mode",
        "rth not working", "home point", "failsafe rth", "return to launch",
        "go home", "navigation", "nav not working",
    ],
    "bad_vibrations": [
        "vibration", "jello", "shaking", "oscillation", "wobble",
        "pid", "noisy", "gyro", "propwash", "prop wash",
        "unstable", "shaky video", "motor noise", "desync",
        "oscillating", "bouncing", "flutter",
    ],
    "short_flight_time": [
        "flight time", "short flight", "battery life", "battery drain",
        "voltage", "low battery", "sag", "battery sag", "lands early",
        "not enough flight time", "battery dies fast", "quick discharge",
        "battery warning", "capacity",
    ],
    "failsafe_issues": [
        "failsafe", "fail safe", "failsafe not working", "failsafe trigger",
        "unexpected failsafe", "failsafe land", "failsafe drop",
        "signal lost", "rx loss", "link lost", "failsafe activates",
    ],
    "vtx_not_changing": [
        "vtx channel", "vtx power", "smartaudio", "smart audio",
        "tramp", "vtx control", "vtx settings", "change channel",
        "change power", "vtx band", "pit mode", "vtx table",
        "vtx not responding", "vtx stuck",
    ],
    "compass_drift": [
        "compass", "heading", "drift", "compass drift", "heading wrong",
        "mag", "magnetometer", "compass calibration", "yaw drift",
        "heading offset", "compass error",
    ],
    "altitude_hold_issues": [
        "altitude", "altitude hold", "alt hold", "height", "baro",
        "barometer", "climbing", "sinking", "altitude drift",
        "position hold altitude", "vario", "alt not holding",
    ],
}


def match_symptom(user_text: str) -> list[tuple[str, float]]:
    """Match free-text user input to ranked symptom keys with confidence scores.

    Returns a list of (symptom_key, confidence) tuples sorted by confidence
    descending. Only matches with confidence > 0.2 are returned.

    Scoring approach:
    - Each keyword hit contributes a base score of 1.0
    - Multi-word phrase hits get a bonus (word_count - 1) * 0.5
    - The total is normalized against the keyword count, then scaled so
      that a single keyword hit gives ~0.25 and 3+ hits approach 1.0
    """
    text_lower = user_text.lower().strip()
    if not text_lower:
        return []

    scores: list[tuple[str, float]] = []

    for symptom_key, keywords in _SYMPTOM_KEYWORDS.items():
        weighted_hits = 0.0
        num_keywords = len(keywords)

        for keyword in keywords:
            if keyword in text_lower:
                # Base score per keyword hit, plus bonus for multi-word phrases
                word_count = len(keyword.split())
                weighted_hits += 1.0 + (word_count - 1) * 0.5

        if weighted_hits == 0:
            continue

        # Normalize: a single keyword hit should give ~0.25,
        # 2 hits ~0.45, 3+ hits ~0.6+, many hits approach 1.0
        # Use diminishing returns: 1 - (1 - base)^hits
        base_per_hit = 1.0 / max(num_keywords, 1)
        raw_score = min(1.0, weighted_hits * base_per_hit)

        # Scale up so a single hit is around 0.25, 2 hits around 0.45
        confidence = min(1.0, raw_score * 3.5)

        if confidence > 0.2:
            scores.append((symptom_key, round(confidence, 2)))

    # Sort by confidence descending, then alphabetically for ties
    scores.sort(key=lambda x: (-x[1], x[0]))
    return scores


# ---------------------------------------------------------------------------
# Symptom → relevant check IDs (disc_*, fw_*, YAML constraint IDs)
# ---------------------------------------------------------------------------

SYMPTOM_CHECKS: dict[str, list[str]] = {
    "cant_arm": ["disc_002", "fw_005", "fw_018"],
    "motors_wont_spin": ["disc_004", "disc_005", "fw_001", "fw_002", "elec_001", "elec_002"],
    "flips_on_takeoff": ["disc_010", "fw_001", "disc_004"],
    "no_video": ["disc_003", "fw_007", "fw_008", "fw_015"],
    "no_receiver": ["disc_002", "fw_004", "fw_005", "fw_006"],
    "low_range": ["disc_002", "fw_004", "fw_005", "fw_016"],
    "gps_not_working": ["disc_008", "fw_018"],
    "rth_not_working": ["disc_008", "fw_018", "fw_019"],
    "bad_vibrations": ["fw_012", "fw_013", "fw_014"],
    "short_flight_time": ["disc_006", "fw_010", "fw_011", "elec_005"],
    "failsafe_issues": ["disc_002", "fw_004", "fw_005", "fw_016"],
    "vtx_not_changing": ["disc_003", "fw_007", "fw_008", "fw_009"],
    "compass_drift": ["disc_008", "fw_018"],
    "altitude_hold_issues": ["disc_008", "fw_018", "fw_019"],
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
# Resolution guides — structured multi-step fix instructions per check ID
# ---------------------------------------------------------------------------

RESOLUTION_GUIDES: dict[str, dict] = {
    "disc_002": {
        "summary": "Receiver protocol mismatch between FC config and fleet record",
        "steps": [
            "Step 1: Open Betaflight Configurator and go to the Configuration tab.",
            "Step 2: Under 'Receiver', check the 'Serial Receiver Provider' dropdown.",
            "Step 3: Verify which receiver is physically installed on your drone.",
            "Step 4: If you swapped the receiver, set the provider to match (e.g., CRSF for ELRS/Crossfire, SBUS for FrSky).",
            "Step 5: If the fleet record is wrong, update it with the correct receiver model and protocol.",
            "Step 6: Save and reboot the FC. Verify RC input is working in the Receiver tab.",
        ],
        "severity_note": "No RC control until resolved — the drone cannot be flown safely.",
        "reference": "Betaflight wiki: Receiver Configuration",
    },
    "disc_003": {
        "summary": "VTX type mismatch — analog vs digital video system",
        "steps": [
            "Step 1: Identify which VTX is physically installed (analog SmartAudio/Tramp or digital DJI/HDZero/Walksnail).",
            "Step 2: In Betaflight Configurator, go to the Ports tab.",
            "Step 3: For analog VTX: assign 'TBS SmartAudio' or 'IRC Tramp' to the UART wired to the VTX.",
            "Step 4: For digital VTX: assign 'VTX (MSP+DisplayPort)' to the UART wired to the VTX.",
            "Step 5: Remove any conflicting VTX assignments on other UARTs.",
            "Step 6: If you replaced the VTX, update the fleet record with the new VTX model and type.",
        ],
        "severity_note": "No video feed or OSD until the correct VTX type is configured.",
        "reference": "Betaflight wiki: VTX Configuration",
    },
    "disc_004": {
        "summary": "Motor protocol mismatch between FC config and ESC",
        "steps": [
            "Step 1: Open Betaflight Configurator and go to Configuration tab.",
            "Step 2: Under 'ESC/Motor Features', check the current Motor Protocol setting.",
            "Step 3: Verify which ESC is installed and what protocols it supports (check ESC spec sheet).",
            "Step 4: Set the Motor Protocol to match: DShot600 for BLHeli_32/AM32, DShot300 for BLHeli_S.",
            "Step 5: If you swapped the ESC, update the fleet record with the new ESC model and protocol.",
            "Step 6: Save and reboot. Test motor spin in the Motors tab (remove props first!).",
        ],
        "severity_note": "Motors may not spin or may behave erratically — do not fly.",
        "reference": "Betaflight wiki: DShot and ESC Protocol",
    },
    "fw_001": {
        "summary": "FC motor protocol does not match ESC capability",
        "steps": [
            "Step 1: Open Betaflight Configurator -> Configuration -> ESC/Motor Features.",
            "Step 2: Check the 'Motor Protocol' dropdown.",
            "Step 3: Set it to match your ESC: DShot600 is the most common for modern ESCs.",
            "Step 4: BLHeli_S ESCs: use DShot300 or DShot600 (NOT DShot1200).",
            "Step 5: BLHeli_32/AM32 ESCs: DShot600 recommended, DShot1200 optional.",
            "Step 6: Save, reboot, and test motors in Motors tab with props removed.",
        ],
        "severity_note": "Motors will not spin with the wrong protocol — address before flying.",
        "reference": "Betaflight wiki: Motor Protocol",
    },
    "fw_004": {
        "summary": "Serial receiver protocol does not match the installed receiver",
        "steps": [
            "Step 1: Open Betaflight Configurator -> Configuration -> Receiver.",
            "Step 2: Check the 'Serial Receiver Provider' setting.",
            "Step 3: Set it to match your receiver: CRSF for ELRS/TBS Crossfire, SBUS for FrSky, IBUS for FlySky.",
            "Step 4: Go to the Receiver tab and verify channels respond to stick input.",
            "Step 5: If channels do not move, also check that SERIAL_RX is assigned to the correct UART in the Ports tab.",
        ],
        "severity_note": "No RC control — cannot fly until resolved.",
        "reference": "Betaflight wiki: Receiver",
    },
    "fw_005": {
        "summary": "No UART assigned for serial receiver input",
        "steps": [
            "Step 1: Open Betaflight Configurator -> Ports tab.",
            "Step 2: Find the UART that your receiver's TX/RX wire is physically connected to.",
            "Step 3: Enable 'Serial RX' on that UART row.",
            "Step 4: Make sure no other conflicting function is assigned to the same UART.",
            "Step 5: Save and reboot. Go to the Receiver tab and verify channels respond.",
            "Step 6: If unsure which UART, check your FC's pinout diagram for the RX pad.",
        ],
        "severity_note": "Receiver will not work at all without a UART assignment.",
        "reference": "Betaflight wiki: Serial Port Configuration",
    },
    "fw_006": {
        "summary": "SBUS on F4 board needs software inversion",
        "steps": [
            "Step 1: F4 boards (STM32F405, F411) lack hardware UART inversion.",
            "Step 2: SBUS uses an inverted signal — F4 boards need a software workaround.",
            "Step 3: In Betaflight CLI, type: set serialrx_inverted = ON",
            "Step 4: Type: save",
            "Step 5: Alternatively, use an uninverted SBUS pad if your FC has one (check pinout).",
            "Step 6: If using ELRS/CRSF, this issue does not apply — CRSF is not inverted.",
        ],
        "severity_note": "Receiver will not work on F4 with SBUS unless inversion is enabled.",
        "reference": "Betaflight wiki: SBUS on F4",
    },
    "fw_007": {
        "summary": "No UART assigned for analog VTX control (SmartAudio/Tramp)",
        "steps": [
            "Step 1: Open Betaflight Configurator -> Ports tab.",
            "Step 2: Find the UART that your VTX SmartAudio/Tramp wire is connected to.",
            "Step 3: Under 'Peripherals', select 'TBS SmartAudio' or 'IRC Tramp' for that UART.",
            "Step 4: Save and reboot.",
            "Step 5: Go to the Video Transmitter tab and verify VTX settings are readable.",
            "Step 6: If unsure which UART, check your FC pinout for the VTX or SA pad.",
        ],
        "severity_note": "VTX settings cannot be changed from OSD — channel/power must be set manually on the VTX.",
        "reference": "Betaflight wiki: VTX SmartAudio Setup",
    },
    "fw_008": {
        "summary": "Digital VTX needs MSP DisplayPort UART assignment",
        "steps": [
            "Step 1: Open Betaflight Configurator -> Ports tab.",
            "Step 2: Find the UART connected to your digital VTX (DJI/HDZero/Walksnail).",
            "Step 3: Under 'Peripherals', select 'VTX (MSP+DisplayPort)'.",
            "Step 4: Save and reboot.",
            "Step 5: In Configuration tab, ensure OSD feature is enabled.",
            "Step 6: Power cycle the VTX and verify OSD elements appear in your goggles.",
        ],
        "severity_note": "No OSD overlay in goggles until MSP DisplayPort is configured.",
        "reference": "Betaflight wiki: MSP DisplayPort for Digital FPV",
    },
    "fw_010": {
        "summary": "Battery minimum cell voltage is outside safe range",
        "steps": [
            "Step 1: In Betaflight CLI, check current value: get vbat_min_cell_voltage",
            "Step 2: Standard safe minimum is 330 (3.30V per cell).",
            "Step 3: For conservative flying, use 340 (3.40V).",
            "Step 4: Values below 310 (3.10V) risk permanent battery damage from over-discharge.",
            "Step 5: Values above 360 (3.60V) will trigger landing warnings too early.",
            "Step 6: Set the value: set vbat_min_cell_voltage = 330 then type: save",
        ],
        "severity_note": "Incorrect min voltage can damage batteries (too low) or cut flights short (too high).",
        "reference": "Betaflight wiki: Battery Monitoring",
    },
    "fw_011": {
        "summary": "Battery max cell voltage may cause incorrect cell count detection",
        "steps": [
            "Step 1: In Betaflight CLI, check current value: get vbat_max_cell_voltage",
            "Step 2: For standard LiPo: set to 430 (4.30V — slightly above 4.20V full charge).",
            "Step 3: For LiHV (high voltage): set to 440 (4.40V — slightly above 4.35V full charge).",
            "Step 4: Incorrect max voltage causes wrong cell count auto-detection.",
            "Step 5: Wrong cell count means all voltage thresholds are wrong (min, warning, etc.).",
            "Step 6: Set the value and save: set vbat_max_cell_voltage = 430 then type: save",
        ],
        "severity_note": "Wrong cell count detection cascades into all battery warnings being incorrect.",
        "reference": "Betaflight wiki: Battery Monitoring",
    },
    "elec_001": {
        "summary": "Battery voltage too low for ESC minimum rating",
        "steps": [
            "Step 1: Check your ESC's voltage rating (e.g., '3-6S' means 3S minimum).",
            "Step 2: Check your battery's cell count (e.g., 4S, 6S).",
            "Step 3: The battery cell count must meet or exceed the ESC's minimum S-rating.",
            "Step 4: If your battery is below the ESC's minimum, use a higher-voltage battery.",
            "Step 5: Running an ESC below its designed voltage can cause erratic behavior.",
        ],
        "severity_note": "Voltage mismatch can cause ESC failure or unpredictable motor behavior.",
        "reference": "ESC manufacturer voltage specifications",
    },
    "elec_002": {
        "summary": "Battery voltage exceeds ESC maximum rating — risk of ESC destruction",
        "steps": [
            "Step 1: CHECK IMMEDIATELY — this can destroy your ESC on first plug-in.",
            "Step 2: Verify your ESC's maximum S-rating (e.g., '3-6S' means 6S maximum).",
            "Step 3: Verify your battery cell count.",
            "Step 4: NEVER plug in a battery that exceeds the ESC's maximum voltage rating.",
            "Step 5: If you need higher voltage, replace the ESC with one rated for your battery.",
            "Step 6: A 6S battery on a 4S-max ESC will blow the MOSFETs instantly, possibly with fire.",
        ],
        "severity_note": "DANGER: Over-voltage destroys ESCs immediately. Do NOT power on until resolved.",
        "reference": "ESC manufacturer voltage specifications",
    },
    "elec_003": {
        "summary": "ESC current rating too low for motor maximum draw",
        "steps": [
            "Step 1: Check your motor's maximum current draw from the spec sheet or thrust data.",
            "Step 2: Check your ESC's continuous current rating.",
            "Step 3: The ESC should handle motor max current plus a 20% safety margin.",
            "Step 4: Example: 40A motor max draw needs at least 48A ESC (40 * 1.2 = 48).",
            "Step 5: If the ESC is undersized, replace it with a higher-rated one.",
            "Step 6: Alternatively, use softer throttle curves to limit peak current (not recommended for racing).",
        ],
        "severity_note": "Undersized ESC will overheat and can burn out during aggressive flying.",
        "reference": "Motor thrust data tables and ESC specifications",
    },
}


def get_resolution_guide(check_id: str) -> dict | None:
    """Get the structured resolution guide for a given check ID.

    Returns a dict with keys: summary, steps, severity_note, reference (optional),
    or None if no guide exists for the given check ID.
    """
    return RESOLUTION_GUIDES.get(check_id)


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
