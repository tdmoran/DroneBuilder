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

    return DiagnosticReport(
        build_name=build.name,
        fc_info=fc_info,
        discrepancies=discrepancies,
        compatibility_report=compatibility_report,
        firmware_report=firmware_report,
        symptoms=symptoms or [],
        config_changes=config_changes,
    )
