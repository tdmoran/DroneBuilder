"""CLI diagnostic commands for DroneBuilder.

Commands:
    diagnose scan       Full diagnostic scan (FC config vs fleet record)
    diagnose check      Targeted diagnosis for a specific symptom
    diagnose list-symptoms  Show all available symptom keywords
    diagnose history    Show saved FC config history for a drone
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import click

from core.config_store import list_configs, load_config, save_config
from core.fleet import load_fleet, load_fleet_drone, name_to_filename, FLEET_DIR
from core.models import Build, Discrepancy, Severity, ValidationResult
from engines.compatibility import ValidationReport
from engines.diagnose import DiagnosticReport, run_diagnostics, run_quick_health_check
from engines.symptom_map import (
    FIX_SUGGESTIONS,
    RESOLUTION_GUIDES,
    SYMPTOMS,
    SYMPTOM_CHECKS,
    SYMPTOM_DESCRIPTIONS,
    get_fix_suggestion,
    get_resolution_guide,
    match_symptom,
    prioritize_results,
)
from fc_serial.config_parser import parse_diff_all


# ---------------------------------------------------------------------------
# Formatting constants
# ---------------------------------------------------------------------------

_BOX_WIDTH = 58


# ---------------------------------------------------------------------------
# Helpers — FC connection (lazy import to handle missing pyserial)
# ---------------------------------------------------------------------------


def _try_import_serial():
    """Import fc_serial modules, returning None if pyserial is missing."""
    try:
        from fc_serial.connection import detect_fc_ports, open_connection
        from fc_serial.cli_mode import enter_cli_mode, exit_cli_mode, get_diff_all
        return detect_fc_ports, open_connection, enter_cli_mode, exit_cli_mode, get_diff_all
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Helpers — fleet drone lookup
# ---------------------------------------------------------------------------


def _find_drone_by_name(name: str) -> tuple[Build, dict]:
    """Find a fleet drone by name (case-insensitive). Returns (Build, data_dict) or exits."""
    fleet = load_fleet()
    name_lower = name.lower()
    for drone in fleet:
        if drone.name.lower() == name_lower:
            if drone.source_file:
                with open(drone.source_file) as f:
                    data = json.load(f)
                return drone, data
    click.echo(click.style(f"  Error: no fleet drone named '{name}'", fg="red"))
    sys.exit(1)


def _prompt_drone_selection() -> tuple[Build, dict, str]:
    """List fleet drones and prompt the user to select one.

    Returns (Build, raw_data_dict, drone_slug).
    """
    fleet = load_fleet()
    if not fleet:
        click.echo(click.style("  Error: no drones in fleet. Add one with 'dronebuilder fleet add'.", fg="red"))
        sys.exit(1)

    click.echo()
    click.echo(click.style("  Select a drone from your fleet:", bold=True))
    click.echo()
    for i, drone in enumerate(fleet, 1):
        status_color = "green" if drone.status == "active" else "yellow"
        click.echo(
            f"    {click.style(str(i), bold=True)}) {drone.name}"
            f"  {click.style(f'[{drone.status}]', fg=status_color)}"
            f"  ({drone.drone_class})"
        )
    click.echo()

    choice = click.prompt("  Enter number", type=int)
    if choice < 1 or choice > len(fleet):
        click.echo(click.style(f"  Error: invalid choice {choice}", fg="red"))
        sys.exit(1)

    drone = fleet[choice - 1]
    if drone.source_file:
        with open(drone.source_file) as f:
            data = json.load(f)
        slug = Path(drone.source_file).stem
        return drone, data, slug
    else:
        slug = name_to_filename(drone.name)
        return drone, {}, slug


def _auto_match_drone(config) -> tuple[Build, dict, str] | None:
    """Try to auto-match an FC config to a fleet drone by board_name or craft_name."""
    fleet = load_fleet()
    if not fleet:
        return None

    craft_name = config.get_setting("name", "") or config.get_setting("craft_name", "")
    board_name = config.board_name

    for drone in fleet:
        # Match by craft name
        if craft_name:
            craft_lower = craft_name.lower().strip()
            if craft_lower == drone.name.lower() or craft_lower == drone.nickname.lower():
                if drone.source_file:
                    with open(drone.source_file) as f:
                        data = json.load(f)
                    slug = Path(drone.source_file).stem
                    return drone, data, slug

        # Match by board name vs FC MCU
        if board_name:
            fc = drone.get_component("fc")
            if fc:
                mcu = fc.get("mcu", "")
                if mcu:
                    mcu_short = mcu.upper().replace("STM32", "").replace("AT32", "")
                    if mcu_short and mcu_short in board_name.upper():
                        if drone.source_file:
                            with open(drone.source_file) as f:
                                data = json.load(f)
                            slug = Path(drone.source_file).stem
                            return drone, data, slug

    return None


# ---------------------------------------------------------------------------
# Helpers — output formatting
# ---------------------------------------------------------------------------


def _severity_tag(
    severity: Severity,
    passed: bool,
    skipped: bool = False,
    confidence: float | None = None,
) -> str:
    """Return a styled [PASS]/[FAIL]/[WARN]/[SKIP]/[INFO] tag with optional confidence %."""
    if skipped:
        return click.style("[SKIP]", fg="bright_black")
    if passed:
        return click.style("[PASS]", fg="green", bold=True)

    conf_str = ""
    if confidence is not None:
        conf_pct = int(confidence * 100)
        conf_str = f" {conf_pct}%"

    if severity == Severity.CRITICAL:
        return click.style(f"[FAIL{conf_str}]", fg="red", bold=True)
    if severity == Severity.WARNING:
        return click.style(f"[WARN{conf_str}]", fg="yellow", bold=True)
    return click.style(f"[INFO{conf_str}]", fg="cyan")


def _print_header_box(build_name: str, fc_info: str, port: str | None = None):
    """Print the top diagnostic header box."""
    click.echo()
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", fg="bright_white", bold=True))
    click.echo(click.style(f"  ||  DRONE DIAGNOSTICS -- {build_name}", fg="bright_white", bold=True))
    click.echo(click.style(f"  ||{'=' * (_BOX_WIDTH - 3)}", fg="bright_white", bold=True))
    click.echo(click.style(f"  ||  FC: {fc_info}", fg="bright_white"))
    if port:
        click.echo(click.style(f"  ||  Port: {port}", fg="bright_white"))
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", fg="bright_white", bold=True))
    click.echo()


def _print_section_header(title: str):
    """Print a section separator line."""
    padding = _BOX_WIDTH - len(title) - 4
    if padding < 2:
        padding = 2
    click.echo(click.style(f"  -- {title} {'-' * padding}", dim=True))
    click.echo()


def _print_discrepancy(
    disc: Discrepancy,
    delay: float = 0.03,
    confidence: float | None = None,
):
    """Print a single discrepancy check result."""
    tag = _severity_tag(disc.severity, False, confidence=confidence)
    click.echo(f"  {tag} {click.style(disc.id, bold=True)}  {disc.message}")
    # Details on failure/warning
    click.echo(click.style(f"                   Fleet: {disc.fleet_value}", dim=True))
    click.echo(click.style(f"                   FC:    {disc.detected_value}", dim=True))

    # Show resolution guide if available, otherwise fall back to fix_suggestion
    guide = get_resolution_guide(disc.id)
    if guide:
        _print_resolution_guide(guide)
    elif disc.fix_suggestion:
        click.echo(click.style(f"                   Fix: {disc.fix_suggestion}", fg="cyan"))
    click.echo()
    time.sleep(delay)


def _print_resolution_guide(guide: dict):
    """Print a structured resolution guide inline."""
    click.echo(click.style(f"                   Resolution: {guide['summary']}", fg="cyan", bold=True))
    for step in guide["steps"]:
        click.echo(click.style(f"                     {step}", fg="cyan"))
    if guide.get("severity_note"):
        click.echo(click.style(f"                     Note: {guide['severity_note']}", fg="yellow"))
    if guide.get("reference"):
        click.echo(click.style(f"                     Ref: {guide['reference']}", dim=True))


def _print_validation_result(
    result: ValidationResult,
    delay: float = 0.03,
    confidence: float | None = None,
):
    """Print a single validation result."""
    skipped = result.details.get("skipped", False)
    tag = _severity_tag(
        result.severity, result.passed, skipped=skipped,
        confidence=confidence if not result.passed and not skipped else None,
    )
    check_id = click.style(result.constraint_id, bold=True)

    if skipped:
        skip_reason = result.details.get("skip_reason", "component not in build")
        click.echo(f"  {tag} {check_id}  {result.constraint_name}")
        click.echo(click.style(f"                   Skipped: {skip_reason}", dim=True))
        time.sleep(delay)
        return

    if result.passed:
        click.echo(f"  {tag} {check_id}  {result.constraint_name}")
        time.sleep(delay)
        return

    # Failed or warning — expanded output
    click.echo(f"  {tag} {check_id}  {result.constraint_name}")
    click.echo(click.style(f"                   {result.message}", dim=True))

    # Show resolution guide if available, otherwise fall back to fix suggestion
    guide = get_resolution_guide(result.constraint_id)
    if guide:
        _print_resolution_guide(guide)
    else:
        fix = get_fix_suggestion(result.constraint_id)
        if fix:
            click.echo(click.style(f"                   Fix: {fix}", fg="cyan"))

    click.echo()
    time.sleep(delay)


def _print_summary(report: DiagnosticReport):
    """Print the summary box at the bottom of diagnostics."""
    # Count results
    total = 0
    critical = 0
    warnings = 0
    passed = 0
    skipped = 0
    info = 0

    # Count discrepancies
    total += len(report.discrepancies)
    for d in report.discrepancies:
        if d.severity == Severity.CRITICAL:
            critical += 1
        elif d.severity == Severity.WARNING:
            warnings += 1
        elif d.severity == Severity.INFO:
            info += 1

    # Count compatibility results
    if report.compatibility_report:
        for r in report.compatibility_report.results:
            total += 1
            if r.details.get("skipped"):
                skipped += 1
            elif r.passed:
                passed += 1
            elif r.severity == Severity.CRITICAL:
                critical += 1
            elif r.severity == Severity.WARNING:
                warnings += 1
            elif r.severity == Severity.INFO:
                info += 1

    # Count firmware results
    if report.firmware_report:
        for r in report.firmware_report.results:
            total += 1
            if r.details.get("skipped"):
                skipped += 1
            elif r.passed:
                passed += 1
            elif r.severity == Severity.CRITICAL:
                critical += 1
            elif r.severity == Severity.WARNING:
                warnings += 1
            elif r.severity == Severity.INFO:
                info += 1

    click.echo()
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))
    click.echo(click.style(f"    SUMMARY", bold=True))
    click.echo(click.style(f"  {'-' * _BOX_WIDTH}", dim=True))
    click.echo(f"    Total checks:  {total}")
    click.echo(
        f"    {click.style('x', fg='red')} Critical:     "
        f"{click.style(str(critical), fg='red', bold=True)}"
        + ("  -- Immediate attention needed" if critical else "")
    )
    click.echo(
        f"    {click.style('!', fg='yellow')} Warning:      "
        f"{click.style(str(warnings), fg='yellow', bold=True)}"
        + ("  -- Should be addressed" if warnings else "")
    )
    click.echo(
        f"    {click.style('v', fg='green')} Passed:      "
        f"{click.style(str(passed), fg='green', bold=True)}"
    )
    click.echo(
        f"    {click.style('o', dim=True)} Skipped:      "
        f"{click.style(str(skipped), dim=True)}"
    )
    click.echo(
        f"    {click.style('i', fg='cyan')} Info:         "
        f"{click.style(str(info), fg='cyan')}"
    )
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))

    if critical > 0:
        click.echo()
        click.echo(click.style(
            f"  {critical} critical issue(s) found. Resolve before flying.",
            fg="red", bold=True,
        ))
    elif warnings > 0:
        click.echo()
        click.echo(click.style(
            f"  No critical issues, but {warnings} warning(s) to review.",
            fg="yellow",
        ))
    else:
        click.echo()
        click.echo(click.style(
            "  All clear -- no critical issues or warnings detected.",
            fg="green", bold=True,
        ))
    click.echo()


def _print_check_results_section(
    title: str,
    results: list[ValidationResult],
    delay: float = 0.03,
):
    """Print a section of validation results with a header."""
    _print_section_header(title)
    for result in results:
        _print_validation_result(result, delay=delay)
    click.echo()


def _print_check_results_section_with_confidence(
    title: str,
    results: list[ValidationResult],
    report: DiagnosticReport,
    delay: float = 0.03,
):
    """Print a section of validation results with confidence scores from the report."""
    _print_section_header(title)
    for result in results:
        conf = report.get_confidence(result.constraint_id)
        _print_validation_result(result, delay=delay, confidence=conf)
    click.echo()


def _print_quick_summary(report: DiagnosticReport):
    """Print a simplified pass/fail summary for quick health check mode."""
    click.echo()
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))
    click.echo(click.style(f"    QUICK HEALTH CHECK RESULT", bold=True))
    click.echo(click.style(f"  {'-' * _BOX_WIDTH}", dim=True))

    if report.safe_to_fly:
        click.echo()
        click.echo(click.style(
            "    SAFE TO FLY -- No critical issues detected.",
            fg="green", bold=True,
        ))
    else:
        # Count critical issues
        critical_count = 0
        for d in report.discrepancies:
            if d.severity == Severity.CRITICAL:
                critical_count += 1
        if report.compatibility_report:
            critical_count += len(report.compatibility_report.critical_failures)
        if report.firmware_report:
            critical_count += len(report.firmware_report.critical_failures)

        click.echo()
        click.echo(click.style(
            f"    DO NOT FLY -- {critical_count} critical issue(s) found.",
            fg="red", bold=True,
        ))
        click.echo(click.style(
            "    Resolve critical issues before flying. Run a full scan for details.",
            fg="red",
        ))

    click.echo()
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))
    click.echo(click.style(
        "  Run without --quick for a full diagnostic scan.",
        dim=True,
    ))
    click.echo()


# ---------------------------------------------------------------------------
# Helpers — config reading
# ---------------------------------------------------------------------------


def _read_config_from_file(config_file: str) -> str:
    """Read diff-all text from a file path."""
    path = Path(config_file)
    if not path.exists():
        click.echo(click.style(f"  Error: config file not found: {config_file}", fg="red"))
        sys.exit(1)
    return path.read_text(encoding="utf-8")


def _read_config_from_serial(port: str | None) -> tuple[str, str]:
    """Connect to FC, read diff-all, return (raw_text, port_path).

    If port is None, auto-detects.
    """
    serial_funcs = _try_import_serial()
    if serial_funcs is None:
        click.echo(click.style(
            "  Error: pyserial is not installed. Install with: pip install pyserial",
            fg="red",
        ))
        click.echo(click.style(
            "  Alternatively, use --config-file to load a saved diff-all text file.",
            fg="yellow",
        ))
        sys.exit(1)

    detect_fc_ports, open_connection, enter_cli_mode, exit_cli_mode, get_diff_all = serial_funcs

    # Auto-detect port if not given
    if not port:
        click.echo(click.style("  Scanning for FC serial ports...", dim=True))
        ports = detect_fc_ports()
        if not ports:
            click.echo(click.style(
                "  Error: no FC serial ports detected. Is the FC connected via USB?",
                fg="red",
            ))
            click.echo(click.style(
                "  Use --port to specify manually, or --config-file to load from file.",
                fg="yellow",
            ))
            sys.exit(1)

        if len(ports) == 1:
            port = ports[0].device
            click.echo(f"  Found FC on {click.style(port, bold=True)} ({ports[0].description})")
        else:
            click.echo(click.style("  Multiple FC ports detected:", bold=True))
            for i, p in enumerate(ports, 1):
                click.echo(f"    {i}) {p.device}  ({p.description})")
            choice = click.prompt("  Select port number", type=int)
            if choice < 1 or choice > len(ports):
                click.echo(click.style(f"  Error: invalid choice {choice}", fg="red"))
                sys.exit(1)
            port = ports[choice - 1].device

    # Connect and read config
    click.echo(click.style(f"  Connecting to {port}...", dim=True))
    try:
        conn = open_connection(port)
    except Exception as exc:
        click.echo(click.style(f"  Error: could not open {port}: {exc}", fg="red"))
        sys.exit(1)

    try:
        click.echo(click.style("  Entering CLI mode...", dim=True))
        enter_cli_mode(conn)

        click.echo(click.style("  Reading FC config (diff all)...", dim=True))
        raw_text = get_diff_all(conn)

        click.echo(click.style("  Exiting CLI mode...", dim=True))
        exit_cli_mode(conn)
    except Exception as exc:
        click.echo(click.style(f"  Error during FC communication: {exc}", fg="red"))
        sys.exit(1)
    finally:
        conn.close()

    return raw_text, port


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------


@click.group("diagnose")
def diagnose():
    """Run diagnostics on a fleet drone's FC configuration."""


# ---------------------------------------------------------------------------
# diagnose scan
# ---------------------------------------------------------------------------


@diagnose.command("scan")
@click.option("--drone", "-d", "drone_name", default=None,
              help="Fleet drone name. If omitted, prompts for selection.")
@click.option("--port", "-p", "serial_port", default=None,
              help="Serial port path (e.g. /dev/cu.usbmodem14201). Auto-detects if omitted.")
@click.option("--config-file", "-f", "config_file", default=None,
              type=click.Path(), help="Path to a saved diff-all text file (instead of serial).")
@click.option("--symptom", "-s", "symptoms", multiple=True,
              help="Reported symptom keyword (can repeat). See 'diagnose list-symptoms'.")
@click.option("--save/--no-save", default=True,
              help="Save config backup to fleet history (default: yes).")
@click.option("--quick", "-q", is_flag=True, default=False,
              help="Quick health check — runs only critical safety checks.")
def scan_cmd(
    drone_name: str | None,
    serial_port: str | None,
    config_file: str | None,
    symptoms: tuple[str, ...],
    save: bool,
    quick: bool,
):
    """Run a full diagnostic scan against a fleet drone.

    Reads the FC config (via serial or file), compares against the fleet
    record, runs compatibility checks, and validates firmware settings.

    Use --quick for a fast "safe to fly" assessment that runs only
    the most critical checks.
    """
    # Validate symptoms
    symptom_list = list(symptoms)
    for s in symptom_list:
        if s not in SYMPTOMS:
            click.echo(click.style(f"  Error: unknown symptom '{s}'", fg="red"))
            click.echo(click.style("  Run 'dronebuilder diagnose list-symptoms' for valid keywords.", fg="yellow"))
            sys.exit(1)

    # Step 1: Read FC config
    port_used = None
    if config_file:
        raw_text = _read_config_from_file(config_file)
        click.echo(click.style(f"  Loaded config from: {config_file}", dim=True))
    else:
        raw_text, port_used = _read_config_from_serial(serial_port)

    config = parse_diff_all(raw_text)
    click.echo(click.style(
        f"  Parsed: {config.firmware} {config.firmware_version}"
        + (f" on {config.board_name}" if config.board_name else ""),
        dim=True,
    ))

    # Step 2: Resolve drone
    drone_slug = None
    if drone_name:
        drone, drone_data = _find_drone_by_name(drone_name)
        drone_slug = name_to_filename(drone_name)
    else:
        # Try auto-match first
        match = _auto_match_drone(config)
        if match:
            drone, drone_data, drone_slug = match
            click.echo(
                f"  Auto-matched to fleet drone: "
                f"{click.style(drone.name, fg='green', bold=True)}"
            )
            if not click.confirm("  Use this drone?", default=True):
                drone, drone_data, drone_slug = _prompt_drone_selection()
        else:
            drone, drone_data, drone_slug = _prompt_drone_selection()

    # Step 3: Save config backup
    if save and drone_slug:
        try:
            stored = save_config(drone_slug, raw_text, config)
            click.echo(click.style(f"  Config saved: {stored.raw_path}", dim=True))
        except Exception as exc:
            click.echo(click.style(f"  Warning: could not save config backup: {exc}", fg="yellow"))

    # Step 4: Load previous config for diff (if available)
    previous_config = None
    if drone_slug:
        configs = list_configs(drone_slug)
        if len(configs) >= 2:
            prev_result = load_config(drone_slug, configs[1].timestamp)
            if prev_result:
                _, previous_config = prev_result

    # Step 5: Run diagnostics (quick or full)
    click.echo()
    if quick:
        click.echo(click.style("  Running quick health check...", dim=True))
        report = run_quick_health_check(drone, fc_config=config)
        # Set symptoms on the quick report if any were provided
        report.symptoms = symptom_list
    else:
        click.echo(click.style("  Running diagnostics...", dim=True))
        report = run_diagnostics(
            config, drone,
            symptoms=symptom_list,
            previous_config=previous_config,
        )

    # Step 6: Display results
    fc_info = report.fc_info
    if quick:
        _print_header_box(report.build_name + " [QUICK CHECK]", fc_info, port=port_used)
    else:
        _print_header_box(report.build_name, fc_info, port=port_used)

    # Section 1: Discrepancies
    _print_section_header("Discrepancy Checks (FC Config vs Fleet Record)")
    if report.discrepancies:
        for disc in report.discrepancies:
            conf = report.get_confidence(disc.id)
            _print_discrepancy(disc, confidence=conf)
    else:
        click.echo(click.style("    No discrepancies detected.", fg="green"))
        click.echo()

    # Section 2: Compatibility checks
    if report.compatibility_report:
        _print_check_results_section_with_confidence(
            "Compatibility Checks (Build Rules)",
            report.compatibility_report.results,
            report,
        )

    # Section 3: Firmware validation
    if report.firmware_report:
        _print_check_results_section_with_confidence(
            "Firmware Validation (Config vs Component Specs)",
            report.firmware_report.results,
            report,
        )

    # Section 4: Config changes (if previous config exists, full mode only)
    if not quick and report.config_changes:
        _print_section_header("Config Changes (Since Last Backup)")
        for change in report.config_changes:
            click.echo(f"    {click.style('~', fg='yellow')} {change}")
        click.echo()

    # Summary
    if quick:
        _print_quick_summary(report)
    else:
        _print_summary(report)

    # Exit with non-zero if critical issues
    if report.has_critical_issues:
        sys.exit(1)


# ---------------------------------------------------------------------------
# diagnose check
# ---------------------------------------------------------------------------


@diagnose.command("check")
@click.argument("symptom")
@click.option("--drone", "-d", "drone_name", default=None,
              help="Fleet drone name. If omitted, prompts for selection.")
@click.option("--config-file", "-f", "config_file", default=None,
              type=click.Path(), help="Path to a saved diff-all text file.")
def check_cmd(
    symptom: str,
    drone_name: str | None,
    config_file: str | None,
):
    """Targeted diagnosis for a specific symptom.

    Pass a symptom keyword to run only the checks relevant to that problem.
    You can also pass a free-text description and fuzzy matching will find
    the closest symptom. Use 'diagnose list-symptoms' to see available keywords.
    """
    if symptom not in SYMPTOMS:
        # Try fuzzy matching
        matches = match_symptom(symptom)
        if matches:
            click.echo()
            click.echo(click.style(f"  '{symptom}' is not an exact symptom key.", fg="yellow"))
            click.echo(click.style("  Did you mean one of these?", bold=True))
            click.echo()
            for i, (key, score) in enumerate(matches[:5], 1):
                conf_pct = int(score * 100)
                desc = SYMPTOMS[key]
                click.echo(
                    f"    {click.style(str(i), bold=True)}) "
                    f"{click.style(key, fg='cyan', bold=True):<38}"
                    f" {desc}"
                    f"  {click.style(f'({conf_pct}% match)', dim=True)}"
                )
            click.echo()

            if len(matches) == 1:
                # Single strong match — auto-confirm
                best_key, best_score = matches[0]
                if best_score >= 0.5:
                    if click.confirm(f"  Use '{best_key}'?", default=True):
                        symptom = best_key
                    else:
                        sys.exit(0)
                else:
                    choice = click.prompt("  Enter number (or 0 to cancel)", type=int)
                    if choice < 1 or choice > len(matches):
                        sys.exit(0)
                    symptom = matches[choice - 1][0]
            else:
                choice = click.prompt("  Enter number (or 0 to cancel)", type=int)
                if choice < 1 or choice > min(5, len(matches)):
                    sys.exit(0)
                symptom = matches[choice - 1][0]
        else:
            click.echo(click.style(f"  Error: unknown symptom '{symptom}'", fg="red"))
            click.echo(click.style("  No fuzzy matches found.", dim=True))
            click.echo()
            click.echo(click.style("  Available symptoms:", bold=True))
            for key, desc in SYMPTOMS.items():
                click.echo(f"    {click.style(key, fg='cyan'):<28} {desc}")
            click.echo()
            sys.exit(1)

    # Read config
    if config_file:
        raw_text = _read_config_from_file(config_file)
    else:
        raw_text, _ = _read_config_from_serial(None)

    config = parse_diff_all(raw_text)

    # Resolve drone
    if drone_name:
        drone, _ = _find_drone_by_name(drone_name)
    else:
        drone, _, _ = _prompt_drone_selection()

    # Run full diagnostics but only display symptom-relevant checks
    report = run_diagnostics(config, drone, symptoms=[symptom])

    # Header
    click.echo()
    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))
    click.echo(
        click.style("  TARGETED DIAGNOSIS: ", bold=True)
        + click.style(SYMPTOMS[symptom], fg="yellow", bold=True)
    )
    click.echo(click.style(f"  Drone: {drone.name}  |  {report.fc_info}", dim=True))

    # Show symptom description if available
    desc = SYMPTOM_DESCRIPTIONS.get(symptom)
    if desc:
        click.echo(click.style(f"  {desc}", dim=True))

    click.echo(click.style(f"  {'=' * _BOX_WIDTH}", bold=True))
    click.echo()

    # Relevant check IDs for this symptom
    relevant_ids = set(SYMPTOM_CHECKS.get(symptom, []))

    # Collect and display relevant findings
    relevant_discs = [d for d in report.discrepancies if d.id in relevant_ids]
    relevant_compat = []
    relevant_firmware = []

    if report.compatibility_report:
        relevant_compat = [
            r for r in report.compatibility_report.results
            if r.constraint_id in relevant_ids
        ]
    if report.firmware_report:
        relevant_firmware = [
            r for r in report.firmware_report.results
            if r.constraint_id in relevant_ids
        ]

    total_relevant = len(relevant_discs) + len(relevant_compat) + len(relevant_firmware)

    if total_relevant == 0:
        click.echo(click.style(
            "    No checks mapped to this symptom produced findings for your build.",
            fg="yellow",
        ))
        click.echo(click.style(
            "    This may mean the issue is not detectable from config alone.",
            dim=True,
        ))
        click.echo()
        return

    click.echo(click.style(
        f"  Checks relevant to '{symptom}' ({total_relevant} checks):",
        bold=True,
    ))
    click.echo()

    if relevant_discs:
        _print_section_header("Discrepancy Checks")
        for disc in relevant_discs:
            conf = report.get_confidence(disc.id)
            _print_discrepancy(disc, confidence=conf)

    if relevant_compat:
        _print_section_header("Compatibility Checks")
        for r in relevant_compat:
            conf = report.get_confidence(r.constraint_id)
            _print_validation_result(r, confidence=conf)

    if relevant_firmware:
        _print_section_header("Firmware Validation")
        for r in relevant_firmware:
            conf = report.get_confidence(r.constraint_id)
            _print_validation_result(r, confidence=conf)

    # Mini summary
    failed_count = (
        len(relevant_discs)
        + sum(1 for r in relevant_compat if not r.passed)
        + sum(1 for r in relevant_firmware if not r.passed)
    )
    passed_count = (
        sum(1 for r in relevant_compat if r.passed)
        + sum(1 for r in relevant_firmware if r.passed)
    )

    click.echo(click.style(f"  {'-' * _BOX_WIDTH}", dim=True))
    if failed_count > 0:
        click.echo(
            f"  {click.style(str(failed_count), fg='red', bold=True)} issue(s) found"
            f"  |  {click.style(str(passed_count), fg='green')} passed"
            f"  |  Symptom: {click.style(SYMPTOMS[symptom], fg='yellow')}"
        )
    else:
        click.echo(click.style(
            f"  All {passed_count} relevant checks passed. "
            "Issue may not be detectable from config.",
            fg="green",
        ))
    click.echo()


# ---------------------------------------------------------------------------
# diagnose list-symptoms
# ---------------------------------------------------------------------------


@diagnose.command("list-symptoms")
def list_symptoms_cmd():
    """Show all available symptom keywords for targeted diagnosis."""
    click.echo()
    click.echo(click.style("  Available Symptom Keywords", bold=True))
    click.echo(click.style(f"  {'=' * 56}", dim=True))
    click.echo()

    for key, desc in SYMPTOMS.items():
        check_ids = SYMPTOM_CHECKS.get(key, [])
        check_count = len(check_ids)
        click.echo(
            f"  {click.style(key, fg='cyan', bold=True):<38}"
            f" {desc}"
        )
        click.echo(
            click.style(f"    {check_count} checks: {', '.join(check_ids)}", dim=True)
        )

    click.echo()
    click.echo(click.style(
        f"  {len(SYMPTOMS)} symptoms available. "
        "Use with: dronebuilder diagnose check <symptom>",
        dim=True,
    ))
    click.echo()


# ---------------------------------------------------------------------------
# diagnose history
# ---------------------------------------------------------------------------


@diagnose.command("history")
@click.argument("drone_name")
def history_cmd(drone_name: str):
    """Show saved FC config history for a fleet drone."""
    # Verify drone exists
    _find_drone_by_name(drone_name)
    drone_slug = name_to_filename(drone_name)

    configs = list_configs(drone_slug)

    if not configs:
        click.echo(click.style(
            f"  No saved configs for '{drone_name}'.",
            fg="yellow",
        ))
        click.echo(click.style(
            "  Run 'dronebuilder diagnose scan' to read and save an FC config.",
            dim=True,
        ))
        return

    click.echo()
    click.echo(click.style(f"  Config History for {drone_name}", bold=True))
    click.echo(click.style(f"  {'=' * 56}", dim=True))
    click.echo()

    # Column header
    click.echo(click.style(
        f"  {'#':>3}  {'Timestamp':<20}  {'Firmware':<10}  {'Version':<10}  {'Board':<20}",
        bold=True,
    ))
    click.echo(click.style(f"  {'-' * 56}", dim=True))

    for i, cfg in enumerate(configs, 1):
        # Format timestamp: YYYYMMDDTHHMMSS -> YYYY-MM-DD HH:MM:SS
        ts = cfg.timestamp
        if len(ts) >= 15:
            formatted_ts = (
                f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} "
                f"{ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
            )
        else:
            formatted_ts = ts

        age_label = ""
        if i == 1:
            age_label = click.style("  (latest)", fg="green")

        click.echo(
            f"  {i:>3}  {formatted_ts:<20}  {cfg.firmware:<10}  "
            f"{cfg.firmware_version:<10}  {cfg.board_name:<20}{age_label}"
        )

    click.echo(click.style(f"  {'-' * 56}", dim=True))
    click.echo(click.style(f"  {len(configs)} config(s) stored.", dim=True))
    click.echo(click.style(f"  Files at: fleet/configs/{drone_slug}/", dim=True))
    click.echo()
