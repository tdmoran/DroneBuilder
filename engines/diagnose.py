"""Diagnostic orchestrator — combines discrepancy detection, compatibility,
firmware validation, and symptom prioritization into a single report."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import Build, Discrepancy, Severity, ValidationResult
from engines.compatibility import ValidationReport, validate_build
from engines.discrepancy import detect_discrepancies
from engines.firmware_validator import validate_firmware_config
from engines.symptom_map import (
    FIX_SUGGESTIONS,
    get_fix_suggestion,
    prioritize_results,
)
from fc_serial.models import FCConfig


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

# Check IDs for quick health check mode
_QUICK_DISC_IDS = {"disc_001", "disc_002", "disc_003", "disc_004"}
_QUICK_FW_IDS = {"fw_001", "fw_004", "fw_005", "fw_010", "fw_011"}
_QUICK_ELEC_IDS = {"elec_001", "elec_002", "elec_003"}


def compute_confidence(
    item: ValidationResult | Discrepancy,
) -> float:
    """Compute a confidence score (0.0-1.0) for a diagnostic finding.

    Confidence reflects how certain we are that this finding is a real issue:
    - CRITICAL discrepancy checks (direct config vs fleet comparison) = 0.95
    - CRITICAL firmware validation (config vs component specs) = 0.90
    - WARNING findings from compatibility rules = 0.80
    - INFO findings = 0.70
    - Findings where a spec field was missing or estimated = 0.50
    """
    # Check for missing/estimated data in details
    if isinstance(item, ValidationResult):
        if item.details.get("skipped"):
            return 0.0
        if item.details.get("estimated") or item.details.get("missing_spec"):
            return 0.50

    # Determine source type from ID
    if isinstance(item, Discrepancy):
        check_id = item.id
        is_discrepancy = True
    else:
        check_id = item.constraint_id
        is_discrepancy = False

    severity = item.severity

    if is_discrepancy:
        # Discrepancy checks compare config directly against fleet — high confidence
        if severity == Severity.CRITICAL:
            return 0.95
        if severity == Severity.WARNING:
            return 0.85
        return 0.70

    # ValidationResult — check source by ID prefix
    if check_id.startswith("fw_"):
        # Firmware validation — config vs component specs
        if severity == Severity.CRITICAL:
            return 0.90
        if severity == Severity.WARNING:
            return 0.80
        return 0.70
    elif check_id.startswith("elec_"):
        # Electrical compatibility — YAML constraints
        if severity == Severity.CRITICAL:
            return 0.90
        if severity == Severity.WARNING:
            return 0.80
        return 0.70
    else:
        # Other compatibility rules (mechanical, protocol, weight)
        if severity == Severity.CRITICAL:
            return 0.85
        if severity == Severity.WARNING:
            return 0.80
        return 0.70


def assign_confidence_scores(
    report: "DiagnosticReport",
) -> dict[str, float]:
    """Compute confidence scores for all findings in a diagnostic report.

    Returns a dict mapping check_id to confidence score.
    """
    scores: dict[str, float] = {}

    for d in report.discrepancies:
        scores[d.id] = compute_confidence(d)

    if report.compatibility_report:
        for r in report.compatibility_report.results:
            if not r.passed:
                scores[r.constraint_id] = compute_confidence(r)

    if report.firmware_report:
        for r in report.firmware_report.results:
            if not r.passed:
                scores[r.constraint_id] = compute_confidence(r)

    return scores


# ---------------------------------------------------------------------------
# DiagnosticReport
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticReport:
    """Complete diagnostic report combining all analysis results."""

    build_name: str
    fc_info: str                               # "BTFL 4.5.2 on IFLIGHT_BLITZ_F722"
    discrepancies: list[Discrepancy] = field(default_factory=list)
    compatibility_report: ValidationReport | None = None
    firmware_report: ValidationReport | None = None
    symptoms: list[str] = field(default_factory=list)
    config_changes: list[str] | None = None
    confidence_scores: dict[str, float] = field(default_factory=dict)
    is_quick_check: bool = False

    @property
    def has_critical_issues(self) -> bool:
        """True if any critical discrepancy or failed validation result exists."""
        for d in self.discrepancies:
            if d.severity == Severity.CRITICAL:
                return True
        if self.compatibility_report:
            if self.compatibility_report.critical_failures:
                return True
        if self.firmware_report:
            if self.firmware_report.critical_failures:
                return True
        return False

    @property
    def all_findings_prioritized(self) -> list[ValidationResult | Discrepancy]:
        """All findings sorted: symptom-relevant first, then by severity."""
        all_results: list[ValidationResult] = []
        if self.compatibility_report:
            all_results.extend(self.compatibility_report.results)
        if self.firmware_report:
            all_results.extend(self.firmware_report.results)

        relevant, other = prioritize_results(
            all_results, self.discrepancies, self.symptoms
        )
        return relevant + other

    @property
    def symptom_relevant(self) -> list[ValidationResult | Discrepancy]:
        """Findings relevant to reported symptoms."""
        all_results: list[ValidationResult] = []
        if self.compatibility_report:
            all_results.extend(self.compatibility_report.results)
        if self.firmware_report:
            all_results.extend(self.firmware_report.results)

        relevant, _ = prioritize_results(
            all_results, self.discrepancies, self.symptoms
        )
        return relevant

    @property
    def other_findings(self) -> list[ValidationResult | Discrepancy]:
        """Findings not related to reported symptoms."""
        all_results: list[ValidationResult] = []
        if self.compatibility_report:
            all_results.extend(self.compatibility_report.results)
        if self.firmware_report:
            all_results.extend(self.firmware_report.results)

        _, other = prioritize_results(
            all_results, self.discrepancies, self.symptoms
        )
        return other

    def get_confidence(self, check_id: str) -> float | None:
        """Get the confidence score for a specific check ID, or None if not computed."""
        return self.confidence_scores.get(check_id)

    @property
    def safe_to_fly(self) -> bool:
        """Quick assessment: True if no critical issues were found."""
        return not self.has_critical_issues


# ---------------------------------------------------------------------------
# Config diff helper
# ---------------------------------------------------------------------------


def diff_configs(old: FCConfig, new: FCConfig) -> list[str]:
    """Compare two configs, return human-readable change list.

    Compares master settings, features, and serial port assignments.
    """
    changes: list[str] = []

    # Master settings diff
    all_keys = set(old.master_settings.keys()) | set(new.master_settings.keys())
    for key in sorted(all_keys):
        old_val = old.master_settings.get(key)
        new_val = new.master_settings.get(key)
        if old_val != new_val:
            if old_val is None:
                changes.append(f"{key} added: {new_val}")
            elif new_val is None:
                changes.append(f"{key} removed (was {old_val})")
            else:
                changes.append(f"{key} changed from {old_val} to {new_val}")

    # Feature diff
    old_features = old.features
    new_features = new.features
    for feat in sorted(new_features - old_features):
        changes.append(f"Feature {feat} was enabled")
    for feat in sorted(old_features - new_features):
        changes.append(f"Feature {feat} was disabled")

    # Serial port diff
    old_ports = {p.port_id: p for p in old.serial_ports}
    new_ports = {p.port_id: p for p in new.serial_ports}
    all_port_ids = set(old_ports.keys()) | set(new_ports.keys())

    for port_id in sorted(all_port_ids):
        old_port = old_ports.get(port_id)
        new_port = new_ports.get(port_id)

        if old_port and new_port:
            old_fns = set(old_port.functions)
            new_fns = set(new_port.functions)
            if old_fns != new_fns:
                changes.append(
                    f"UART {port_id} functions changed from "
                    f"{', '.join(sorted(old_fns))} to {', '.join(sorted(new_fns))}"
                )
        elif new_port:
            changes.append(
                f"UART {port_id} added with functions: {', '.join(new_port.functions)}"
            )
        elif old_port:
            changes.append(
                f"UART {port_id} removed (had functions: {', '.join(old_port.functions)})"
            )

    return changes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_diagnostics(
    config: FCConfig,
    build: Build,
    symptoms: list[str] | None = None,
    previous_config: FCConfig | None = None,
) -> DiagnosticReport:
    """Run the full diagnostic pipeline.

    1. Detect hardware discrepancies (FC config vs fleet build)
    2. Run component compatibility validation (YAML constraints)
    3. Run firmware cross-validation (fw_001..fw_020)
    4. Optionally diff against a previous config
    5. Prioritize results based on reported symptoms
    6. Compute confidence scores for all findings
    """
    fc_info = f"{config.firmware} {config.firmware_version}"
    if config.board_name:
        fc_info += f" on {config.board_name}"

    # 1. Discrepancy detection
    discrepancies = detect_discrepancies(config, build)

    # 2. Component compatibility
    compatibility_report = validate_build(build)

    # 3. Firmware cross-validation
    firmware_report = validate_firmware_config(config, build)

    # 4. Config diff
    config_changes = None
    if previous_config is not None:
        config_changes = diff_configs(previous_config, config)

    report = DiagnosticReport(
        build_name=build.name,
        fc_info=fc_info,
        discrepancies=discrepancies,
        compatibility_report=compatibility_report,
        firmware_report=firmware_report,
        symptoms=symptoms or [],
        config_changes=config_changes,
    )

    # 5. Compute confidence scores
    report.confidence_scores = assign_confidence_scores(report)

    return report


def run_quick_health_check(
    build: Build,
    fc_config: FCConfig | None = None,
) -> DiagnosticReport:
    """Run only the most critical checks for a quick "safe to fly" assessment.

    Checks a subset of the full diagnostic pipeline:
    - CRITICAL discrepancy checks: disc_001 through disc_004
    - Key firmware checks: fw_001 (motor protocol), fw_004 (RX protocol),
      fw_005 (RX UART), fw_010/011 (battery voltage)
    - Key electrical checks: elec_001/002 (battery vs ESC), elec_003 (ESC current)

    If fc_config is None, only compatibility checks are run.

    Returns a simplified DiagnosticReport with is_quick_check=True.
    """
    fc_info = ""
    discrepancies: list[Discrepancy] = []
    firmware_report: ValidationReport | None = None

    if fc_config is not None:
        fc_info = f"{fc_config.firmware} {fc_config.firmware_version}"
        if fc_config.board_name:
            fc_info += f" on {fc_config.board_name}"

        # Run all discrepancy checks, then filter to critical ones
        all_discs = detect_discrepancies(fc_config, build)
        discrepancies = [d for d in all_discs if d.id in _QUICK_DISC_IDS]

        # Run all firmware checks, then filter to key ones
        full_fw_report = validate_firmware_config(fc_config, build)
        filtered_fw_results = [
            r for r in full_fw_report.results
            if r.constraint_id in _QUICK_FW_IDS
        ]
        firmware_report = ValidationReport(build_name=build.name)
        firmware_report.results = filtered_fw_results

    # Run compatibility checks, then filter to key electrical ones
    full_compat_report = validate_build(build)
    filtered_compat_results = [
        r for r in full_compat_report.results
        if r.constraint_id in _QUICK_ELEC_IDS
    ]
    compatibility_report = ValidationReport(build_name=build.name)
    compatibility_report.results = filtered_compat_results

    report = DiagnosticReport(
        build_name=build.name,
        fc_info=fc_info,
        discrepancies=discrepancies,
        compatibility_report=compatibility_report,
        firmware_report=firmware_report,
        is_quick_check=True,
    )

    # Compute confidence scores
    report.confidence_scores = assign_confidence_scores(report)

    return report
