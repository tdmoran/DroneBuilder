"""Tests for engines.optimizer — cost-optimized build suggestions."""

from __future__ import annotations

import pytest

from core.loader import load_constraints
from core.models import Severity
from core.resolver import evaluate_constraint
from engines.optimizer import (
    BuildSuggestion,
    OptimizationRequest,
    optimize,
    suggest_quick,
    _SUB250_CONSTRAINT_IDS,
    _SUB250_CLASSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_critical_constraint_failure(suggestion: BuildSuggestion) -> bool:
    """Return True if any CRITICAL constraint fails for the build.

    Mirrors the optimizer's logic: sub-250g constraints are skipped for
    drone classes that are not expected to be sub-250g (e.g. 5inch, 3inch).
    """
    constraints = load_constraints()
    drone_class = suggestion.build.drone_class
    for constraint in constraints:
        if constraint.id in _SUB250_CONSTRAINT_IDS and drone_class not in _SUB250_CLASSES:
            continue
        result = evaluate_constraint(constraint, suggestion.build)
        if not result.passed and result.severity == Severity.CRITICAL:
            return True
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOptimizeReturnsWithinBudget:
    """All returned builds must have a total cost at or below the budget."""

    @pytest.mark.parametrize(
        "drone_class, budget",
        [
            ("5inch", 300.0),
            ("5inch", 500.0),
            ("3inch", 200.0),
            ("whoop", 150.0),
        ],
    )
    def test_within_budget(self, drone_class: str, budget: float) -> None:
        request = OptimizationRequest(drone_class=drone_class, budget_usd=budget)
        suggestions = optimize(request)
        for s in suggestions:
            assert s.total_cost <= budget, (
                f"Build '{s.build.name}' costs ${s.total_cost:.2f} "
                f"which exceeds budget ${budget:.2f}"
            )


class TestNoCriticalCompatibilityFailures:
    """No suggestion should have a critical constraint failure."""

    @pytest.mark.parametrize(
        "drone_class, budget",
        [
            ("5inch", 400.0),
            ("3inch", 200.0),
            ("whoop", 150.0),
        ],
    )
    def test_no_critical_failures(self, drone_class: str, budget: float) -> None:
        request = OptimizationRequest(drone_class=drone_class, budget_usd=budget)
        suggestions = optimize(request)
        for s in suggestions:
            assert not _has_critical_constraint_failure(s), (
                f"Build '{s.build.name}' has a critical constraint failure"
            )


class TestFiveInch300BudgetReturnsAtLeastOne:
    """A $300 5-inch budget must return at least one suggestion."""

    def test_at_least_one_suggestion(self) -> None:
        request = OptimizationRequest(drone_class="5inch", budget_usd=300.0)
        suggestions = optimize(request)
        assert len(suggestions) >= 1, (
            "Expected at least 1 suggestion for 5inch @ $300, got 0"
        )


class TestScoreBetweenZeroAndHundred:
    """Every returned score must be in the range [0, 100]."""

    @pytest.mark.parametrize(
        "drone_class, budget",
        [
            ("5inch", 300.0),
            ("5inch", 500.0),
            ("3inch", 200.0),
            ("whoop", 150.0),
        ],
    )
    def test_score_range(self, drone_class: str, budget: float) -> None:
        request = OptimizationRequest(drone_class=drone_class, budget_usd=budget)
        suggestions = optimize(request)
        for s in suggestions:
            assert 0.0 <= s.score <= 100.0, (
                f"Score {s.score} for '{s.build.name}' is out of [0, 100]"
            )


class TestScoreBreakdownKeys:
    """Each breakdown must contain exactly the four priority dimensions."""

    def test_breakdown_keys(self) -> None:
        request = OptimizationRequest(drone_class="5inch", budget_usd=400.0)
        suggestions = optimize(request)
        expected_keys = {"performance", "weight", "price", "durability"}
        for s in suggestions:
            assert set(s.score_breakdown.keys()) == expected_keys


class TestSuggestQuickConvenience:
    """suggest_quick returns a single BuildSuggestion or None."""

    def test_returns_suggestion_for_valid_input(self) -> None:
        result = suggest_quick("5inch", 400.0)
        assert result is not None
        assert isinstance(result, BuildSuggestion)
        assert result.total_cost <= 400.0

    def test_returns_none_for_impossible_budget(self) -> None:
        result = suggest_quick("5inch", 10.0)
        assert result is None


class TestMaxFiveSuggestions:
    """The optimizer must return at most 5 suggestions."""

    def test_max_five(self) -> None:
        request = OptimizationRequest(drone_class="5inch", budget_usd=600.0)
        suggestions = optimize(request)
        assert len(suggestions) <= 5


class TestSortedByScoreDescending:
    """Results must be sorted highest-score-first."""

    def test_sorted(self) -> None:
        request = OptimizationRequest(drone_class="5inch", budget_usd=500.0)
        suggestions = optimize(request)
        scores = [s.score for s in suggestions]
        assert scores == sorted(scores, reverse=True)


class TestCustomPriorities:
    """Custom priority weights should influence the ranking."""

    def test_price_priority_favours_cheaper(self) -> None:
        cheap_request = OptimizationRequest(
            drone_class="5inch",
            budget_usd=400.0,
            priorities={"performance": 0.0, "weight": 0.0, "price": 1.0, "durability": 0.0},
        )
        balanced_request = OptimizationRequest(
            drone_class="5inch",
            budget_usd=400.0,
        )
        cheap_results = optimize(cheap_request)
        balanced_results = optimize(balanced_request)

        if cheap_results and balanced_results:
            # With price-only priority the cheapest build should surface.
            assert cheap_results[0].total_cost <= balanced_results[0].total_cost + 50.0
