"""Tests for engines/symptom_map.py — mapping validity and prioritization."""

from __future__ import annotations

import pytest

from core.models import Discrepancy, Severity, ValidationResult
from engines.symptom_map import (
    FIX_SUGGESTIONS,
    SYMPTOM_CHECKS,
    SYMPTOMS,
    get_fix_suggestion,
    prioritize_results,
)


# ---------------------------------------------------------------------------
# Mapping validity
# ---------------------------------------------------------------------------


class TestMappingIntegrity:
    """Verify SYMPTOM_CHECKS references valid symptom keys."""

    def test_all_symptom_checks_have_labels(self):
        """Every key in SYMPTOM_CHECKS must exist in SYMPTOMS."""
        for key in SYMPTOM_CHECKS:
            assert key in SYMPTOMS, f"SYMPTOM_CHECKS has key '{key}' not in SYMPTOMS"

    def test_all_symptoms_have_checks(self):
        """Every symptom should have at least one check mapped."""
        for key in SYMPTOMS:
            assert key in SYMPTOM_CHECKS, f"SYMPTOMS has key '{key}' not in SYMPTOM_CHECKS"
            assert len(SYMPTOM_CHECKS[key]) > 0, f"'{key}' has empty check list"

    def test_check_ids_are_valid_format(self):
        """All check IDs should match disc_*, fw_*, or elec_* patterns."""
        import re
        pattern = re.compile(r"^(disc|fw|elec)_\d{3}$")
        for symptom, checks in SYMPTOM_CHECKS.items():
            for check_id in checks:
                assert pattern.match(check_id), (
                    f"Invalid check ID '{check_id}' in symptom '{symptom}'"
                )

    def test_no_duplicate_checks_per_symptom(self):
        """No symptom should have duplicate check IDs."""
        for symptom, checks in SYMPTOM_CHECKS.items():
            assert len(checks) == len(set(checks)), (
                f"Duplicate check IDs in symptom '{symptom}'"
            )


class TestFixSuggestions:
    """Verify fix suggestions coverage."""

    def test_all_fw_checks_have_suggestions(self):
        """Every fw_001..fw_020 should have a fix suggestion."""
        for i in range(1, 21):
            check_id = f"fw_{i:03d}"
            assert check_id in FIX_SUGGESTIONS, (
                f"Missing fix suggestion for {check_id}"
            )

    def test_get_fix_suggestion(self):
        assert get_fix_suggestion("fw_001") != ""
        assert get_fix_suggestion("nonexistent") == ""


# ---------------------------------------------------------------------------
# Prioritization
# ---------------------------------------------------------------------------


def _make_result(check_id: str, severity: Severity, passed: bool) -> ValidationResult:
    return ValidationResult(
        constraint_id=check_id,
        constraint_name=f"Check {check_id}",
        severity=severity,
        passed=passed,
        message=f"Test message for {check_id}",
    )


def _make_discrepancy(disc_id: str, severity: Severity) -> Discrepancy:
    return Discrepancy(
        id=disc_id,
        component_type="test",
        category="test",
        severity=severity,
        fleet_value="fleet",
        detected_value="detected",
        message=f"Test discrepancy {disc_id}",
        fix_suggestion="Fix it",
    )


class TestPrioritize:
    """prioritize_results splits into symptom-relevant and other."""

    def test_splits_by_symptom(self):
        results = [
            _make_result("fw_001", Severity.CRITICAL, False),  # in motors_wont_spin
            _make_result("fw_004", Severity.CRITICAL, False),  # in no_receiver
            _make_result("fw_012", Severity.WARNING, False),   # in bad_vibrations
        ]
        discrepancies = [
            _make_discrepancy("disc_004", Severity.WARNING),   # in motors_wont_spin
        ]

        relevant, other = prioritize_results(
            results, discrepancies, ["motors_wont_spin"]
        )

        relevant_ids = {
            r.constraint_id if isinstance(r, ValidationResult) else r.id
            for r in relevant
        }
        other_ids = {
            r.constraint_id if isinstance(r, ValidationResult) else r.id
            for r in other
        }

        assert "fw_001" in relevant_ids
        assert "disc_004" in relevant_ids
        assert "fw_004" in other_ids
        assert "fw_012" in other_ids

    def test_no_symptoms_all_in_other(self):
        results = [
            _make_result("fw_001", Severity.CRITICAL, False),
        ]
        discrepancies = [
            _make_discrepancy("disc_002", Severity.CRITICAL),
        ]

        relevant, other = prioritize_results(results, discrepancies, [])
        assert len(relevant) == 0
        assert len(other) == 2

    def test_passed_results_excluded(self):
        """Passed results should not appear in either list."""
        results = [
            _make_result("fw_001", Severity.CRITICAL, True),  # passed
            _make_result("fw_002", Severity.CRITICAL, False),
        ]

        relevant, other = prioritize_results(results, [], ["motors_wont_spin"])
        all_items = relevant + other
        ids = {
            r.constraint_id if isinstance(r, ValidationResult) else r.id
            for r in all_items
        }
        assert "fw_001" not in ids
        assert "fw_002" in ids

    def test_sorted_by_severity(self):
        results = [
            _make_result("fw_014", Severity.INFO, False),
            _make_result("fw_012", Severity.WARNING, False),
            _make_result("fw_013", Severity.INFO, False),
        ]

        relevant, other = prioritize_results(results, [], ["bad_vibrations"])

        # All three are in bad_vibrations
        assert len(relevant) == 3
        assert relevant[0].severity == Severity.WARNING
        assert relevant[1].severity == Severity.INFO
        assert relevant[2].severity == Severity.INFO

    def test_multiple_symptoms(self):
        results = [
            _make_result("fw_001", Severity.CRITICAL, False),  # motors_wont_spin
            _make_result("fw_007", Severity.WARNING, False),   # no_video
            _make_result("fw_012", Severity.WARNING, False),   # bad_vibrations (not selected)
        ]

        relevant, other = prioritize_results(
            results, [], ["motors_wont_spin", "no_video"]
        )

        relevant_ids = {
            r.constraint_id if isinstance(r, ValidationResult) else r.id
            for r in relevant
        }
        assert "fw_001" in relevant_ids
        assert "fw_007" in relevant_ids
        assert "fw_012" not in relevant_ids
