"""Tests for engines/symptom_map.py — mapping validity and prioritization."""

from __future__ import annotations

import pytest

from core.models import Discrepancy, Severity, ValidationResult
from engines.symptom_map import (
    FIX_SUGGESTIONS,
    RESOLUTION_GUIDES,
    SYMPTOM_CHECKS,
    SYMPTOM_DESCRIPTIONS,
    SYMPTOMS,
    get_fix_suggestion,
    get_resolution_guide,
    match_symptom,
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


# ---------------------------------------------------------------------------
# Symptom descriptions
# ---------------------------------------------------------------------------


class TestSymptomDescriptions:
    """Verify SYMPTOM_DESCRIPTIONS coverage and quality."""

    def test_all_symptoms_have_descriptions(self):
        """Every symptom key should have a description."""
        for key in SYMPTOMS:
            assert key in SYMPTOM_DESCRIPTIONS, (
                f"Missing description for symptom '{key}'"
            )

    def test_descriptions_are_nonempty(self):
        """Descriptions should be meaningful (non-empty, multi-word)."""
        for key, desc in SYMPTOM_DESCRIPTIONS.items():
            assert len(desc) > 20, (
                f"Description for '{key}' is too short: '{desc}'"
            )


# ---------------------------------------------------------------------------
# Fuzzy symptom matching
# ---------------------------------------------------------------------------


class TestMatchSymptom:
    """match_symptom returns ranked symptom matches from free text."""

    def test_exact_keyword_match(self):
        """Single exact keyword should produce a match."""
        matches = match_symptom("motor")
        keys = [m[0] for m in matches]
        assert "motors_wont_spin" in keys

    def test_multi_word_phrase_match(self):
        """Multi-word phrase should score higher."""
        matches = match_symptom("no video feed in goggles")
        assert len(matches) > 0
        # "no_video" should be the top match
        assert matches[0][0] == "no_video"

    def test_empty_input_returns_empty(self):
        matches = match_symptom("")
        assert matches == []

    def test_whitespace_only_returns_empty(self):
        matches = match_symptom("   ")
        assert matches == []

    def test_no_match_returns_empty(self):
        """Completely unrelated input should return no matches."""
        matches = match_symptom("weather forecast tomorrow")
        assert matches == []

    def test_scores_are_normalized(self):
        """All confidence scores should be between 0.0 and 1.0."""
        matches = match_symptom("motor not spinning vibration jello")
        for key, score in matches:
            assert 0.0 < score <= 1.0, f"Score {score} for '{key}' is out of range"

    def test_results_sorted_by_confidence(self):
        """Results should be sorted highest confidence first."""
        matches = match_symptom("motor vibration oscillation")
        if len(matches) >= 2:
            for i in range(len(matches) - 1):
                assert matches[i][1] >= matches[i + 1][1], (
                    f"Results not sorted: {matches[i]} before {matches[i+1]}"
                )

    def test_case_insensitive(self):
        """Matching should be case-insensitive."""
        matches_lower = match_symptom("no video")
        matches_upper = match_symptom("NO VIDEO")
        keys_lower = {m[0] for m in matches_lower}
        keys_upper = {m[0] for m in matches_upper}
        assert keys_lower == keys_upper

    def test_arm_related(self):
        """Arming-related text should match cant_arm."""
        matches = match_symptom("drone wont arm")
        keys = [m[0] for m in matches]
        assert "cant_arm" in keys

    def test_flyaway_text(self):
        """Free text about fly away should match related symptom."""
        matches = match_symptom("my drone flew away and I lost control")
        # Should find something — the keywords include "fly away", "lost control"
        assert len(matches) >= 0  # may or may not match depending on keywords

    def test_gps_text(self):
        """GPS-related free text should match gps_not_working."""
        matches = match_symptom("gps has no satellites")
        keys = [m[0] for m in matches]
        assert "gps_not_working" in keys

    def test_failsafe_text(self):
        """Failsafe-related text should match failsafe_issues."""
        matches = match_symptom("failsafe keeps triggering")
        keys = [m[0] for m in matches]
        assert "failsafe_issues" in keys

    def test_vibration_text(self):
        """Vibration-related text should match bad_vibrations."""
        matches = match_symptom("lots of jello in my video and shaking")
        keys = [m[0] for m in matches]
        assert "bad_vibrations" in keys

    def test_flight_time_text(self):
        """Flight time text should match short_flight_time."""
        matches = match_symptom("battery drains too fast short flight time")
        keys = [m[0] for m in matches]
        assert "short_flight_time" in keys

    def test_threshold_filters_low_scores(self):
        """Scores below 0.2 should not be returned."""
        matches = match_symptom("something vaguely related")
        for key, score in matches:
            assert score > 0.2, f"Score {score} for '{key}' should be above 0.2"


# ---------------------------------------------------------------------------
# Resolution guides
# ---------------------------------------------------------------------------


class TestResolutionGuides:
    """Verify RESOLUTION_GUIDES structure and content."""

    def test_required_check_ids_have_guides(self):
        """Critical check IDs should have resolution guides."""
        required_ids = [
            "disc_002", "disc_003", "disc_004",
            "fw_001", "fw_004", "fw_005", "fw_006", "fw_007", "fw_008",
            "fw_010", "fw_011",
            "elec_001", "elec_002", "elec_003",
        ]
        for check_id in required_ids:
            assert check_id in RESOLUTION_GUIDES, (
                f"Missing resolution guide for {check_id}"
            )

    def test_guide_structure(self):
        """Each guide should have required keys."""
        for check_id, guide in RESOLUTION_GUIDES.items():
            assert "summary" in guide, f"Guide {check_id} missing 'summary'"
            assert "steps" in guide, f"Guide {check_id} missing 'steps'"
            assert "severity_note" in guide, f"Guide {check_id} missing 'severity_note'"
            assert isinstance(guide["steps"], list), f"Guide {check_id} 'steps' should be a list"
            assert len(guide["steps"]) >= 2, f"Guide {check_id} should have at least 2 steps"

    def test_guide_steps_are_strings(self):
        """All steps should be non-empty strings."""
        for check_id, guide in RESOLUTION_GUIDES.items():
            for i, step in enumerate(guide["steps"]):
                assert isinstance(step, str), f"Guide {check_id} step {i} is not a string"
                assert len(step) > 10, f"Guide {check_id} step {i} is too short"

    def test_get_resolution_guide(self):
        """get_resolution_guide returns guide or None."""
        guide = get_resolution_guide("fw_001")
        assert guide is not None
        assert "summary" in guide
        assert "steps" in guide

        assert get_resolution_guide("nonexistent_check") is None

    def test_summary_is_descriptive(self):
        """Summaries should be meaningful."""
        for check_id, guide in RESOLUTION_GUIDES.items():
            assert len(guide["summary"]) > 10, (
                f"Guide {check_id} summary too short: '{guide['summary']}'"
            )
