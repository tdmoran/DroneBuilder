"""Compatibility engine — validates full builds and component pairs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import Build, Component, Constraint, Severity, ValidationResult
from core.loader import load_constraints
from core.resolver import evaluate_constraint


# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------
_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# ValidationReport
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    """Structured report produced by running all constraints against a build."""

    build_name: str
    results: list[ValidationResult] = field(default_factory=list)

    # -- properties ----------------------------------------------------------

    @property
    def passed(self) -> bool:
        """True only if there are zero critical failures."""
        return len(self.critical_failures) == 0

    @property
    def critical_failures(self) -> list[ValidationResult]:
        return [
            r for r in self.results
            if r.severity == Severity.CRITICAL and not r.passed
        ]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [
            r for r in self.results
            if r.severity == Severity.WARNING and not r.passed
        ]

    @property
    def info(self) -> list[ValidationResult]:
        return [
            r for r in self.results
            if r.severity == Severity.INFO and not r.passed
        ]

    # -- summary -------------------------------------------------------------

    def summary(self) -> str:
        """Return a human-readable, ANSI-colored summary of the report."""
        lines: list[str] = []

        # Header
        status = f"{_GREEN}PASSED{_RESET}" if self.passed else f"{_RED}FAILED{_RESET}"
        lines.append(
            f"{_BOLD}Compatibility Report: {self.build_name}{_RESET}  [{status}]"
        )
        lines.append(f"{_DIM}{'=' * 60}{_RESET}")

        # Counts
        total = len(self.results)
        passed_count = sum(1 for r in self.results if r.passed)
        skipped_count = sum(
            1 for r in self.results
            if r.passed and r.details.get("skipped")
        )
        crit_count = len(self.critical_failures)
        warn_count = len(self.warnings)
        info_count = len(self.info)

        lines.append(
            f"  Total checks: {total}  |  "
            f"Passed: {_GREEN}{passed_count}{_RESET}  |  "
            f"Skipped: {_DIM}{skipped_count}{_RESET}"
        )
        lines.append(
            f"  Critical: {_RED}{crit_count}{_RESET}  |  "
            f"Warnings: {_YELLOW}{warn_count}{_RESET}  |  "
            f"Info: {_CYAN}{info_count}{_RESET}"
        )
        lines.append("")

        # Critical failures
        if self.critical_failures:
            lines.append(f"{_RED}{_BOLD}CRITICAL FAILURES:{_RESET}")
            for r in self.critical_failures:
                lines.append(
                    f"  {_RED}[FAIL]{_RESET} {r.constraint_id}: "
                    f"{r.constraint_name}"
                )
                lines.append(f"         {r.message}")
            lines.append("")

        # Warnings
        if self.warnings:
            lines.append(f"{_YELLOW}{_BOLD}WARNINGS:{_RESET}")
            for r in self.warnings:
                lines.append(
                    f"  {_YELLOW}[WARN]{_RESET} {r.constraint_id}: "
                    f"{r.constraint_name}"
                )
                lines.append(f"         {r.message}")
            lines.append("")

        # Info
        if self.info:
            lines.append(f"{_CYAN}{_BOLD}INFO:{_RESET}")
            for r in self.info:
                lines.append(
                    f"  {_CYAN}[INFO]{_RESET} {r.constraint_id}: "
                    f"{r.constraint_name}"
                )
                lines.append(f"         {r.message}")
            lines.append("")

        # Footer
        lines.append(f"{_DIM}{'=' * 60}{_RESET}")
        if self.passed:
            lines.append(
                f"{_GREEN}{_BOLD}Build is compatible.{_RESET} "
                f"No critical issues found."
            )
        else:
            lines.append(
                f"{_RED}{_BOLD}Build has {crit_count} critical issue(s).{_RESET} "
                f"Resolve before building."
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_build(build: Build) -> ValidationReport:
    """Run ALL constraints against a full build. Return a structured report.

    Loads every constraint from the YAML files and evaluates each one
    against the supplied build.  Constraints whose required components are
    missing from the build are automatically skipped (recorded as passed
    with ``details["skipped"] = True``).
    """
    constraints = load_constraints()
    report = ValidationReport(build_name=build.name)

    for constraint in constraints:
        result = evaluate_constraint(constraint, build)
        report.results.append(result)

    return report


def check_pair(comp_a: Component, comp_b: Component) -> list[ValidationResult]:
    """Check compatibility between two specific components.

    Creates a minimal build containing only *comp_a* and *comp_b*, loads all
    constraints, and runs only those whose ``components`` list is fully
    satisfied by the pair.  Returns the list of evaluation results (which
    may be empty if no constraint applies to this pair).
    """
    # Build a minimal component dict keyed by component_type.
    components: dict[str, Component | list[Component]] = {}

    for comp in (comp_a, comp_b):
        if comp.component_type == "motor":
            # Motors are stored as a list of 4 in a build.
            components["motor"] = [comp] * 4
        else:
            components[comp.component_type] = comp

    mini_build = Build(
        name=f"Pair check: {comp_a.id} + {comp_b.id}",
        drone_class="unknown",
        components=components,
    )

    constraints = load_constraints()
    results: list[ValidationResult] = []

    for constraint in constraints:
        # Only evaluate constraints whose required component types are all
        # present in the mini build.
        required_types = set(constraint.components)
        available_types = set(components.keys())
        if not required_types.issubset(available_types):
            continue

        result = evaluate_constraint(constraint, mini_build)
        results.append(result)

    return results
