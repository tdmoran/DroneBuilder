"""Cost-optimized build suggestion engine for DroneBuilder.

Generates candidate drone builds from the component database, scores them
according to user-defined priority weights, validates them against
constraints, and returns the top suggestions.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any

from core.loader import load_components, load_constraints
from core.models import Build, Component, Severity, ValidationResult
from core.resolver import evaluate_constraint

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

DEFAULT_PRIORITIES: dict[str, float] = {
    "performance": 0.25,
    "weight": 0.25,
    "price": 0.25,
    "durability": 0.25,
}


@dataclass
class OptimizationRequest:
    """Parameters that drive the optimizer."""

    drone_class: str  # "5inch", "3inch", "whoop"
    budget_usd: float
    priorities: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_PRIORITIES))


@dataclass
class BuildSuggestion:
    """A single scored build returned by the optimizer."""

    build: Build
    total_cost: float
    score: float  # 0-100, higher is better
    score_breakdown: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Mapping helpers — VTX and receiver categories are not per-drone-class.
# ---------------------------------------------------------------------------

_VTX_CATEGORY_MAP: dict[str, list[str]] = {
    "5inch": ["digital_hd", "analog"],
    "3inch": ["digital_hd", "digital_hd_micro", "analog", "analog_micro"],
    "whoop": ["digital_hd_micro", "analog_micro"],
}

# Receivers are universal; every protocol works for every class.
_RX_CATEGORIES: list[str] = [
    "elrs",
    "crossfire",
    "frsky",
    "ghost",
]

# How many motors per build (quad).
_MOTOR_COUNT = 4

# Reference weights by class (grams, rough midrange AUW).  Used to compute
# relative weight scores.
_CLASS_REFERENCE_WEIGHT_G: dict[str, float] = {
    "5inch": 680.0,
    "3inch": 250.0,
    "whoop": 35.0,
}

# Maximum number of random candidate builds to sample.
_MAX_CANDIDATES = 600

# How many top candidates survive to the constraint-validation phase.
_PRE_CONSTRAINT_TOP_N = 30

# Final results returned.
_RESULT_TOP_N = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _filter_by_category(
    components: dict[str, list[Component]],
    drone_class: str,
) -> dict[str, list[Component]]:
    """Return a dict with only components compatible with *drone_class*."""

    vtx_cats = set(_VTX_CATEGORY_MAP.get(drone_class, []))
    rx_cats = set(_RX_CATEGORIES)

    filtered: dict[str, list[Component]] = {}
    for comp_type, comp_list in components.items():
        matching: list[Component] = []
        for c in comp_list:
            if comp_type == "vtx":
                if c.category in vtx_cats:
                    matching.append(c)
            elif comp_type == "receiver":
                if c.category in rx_cats:
                    matching.append(c)
            else:
                if c.category == drone_class:
                    matching.append(c)
        if matching:
            filtered[comp_type] = matching
    return filtered


def _build_total_price(
    motor: Component,
    esc: Component,
    fc: Component,
    frame: Component,
    propeller: Component,
    battery: Component,
    vtx: Component,
    receiver: Component,
) -> float:
    """Compute total price for a full build (4 motors, 1 prop set, etc.)."""
    return (
        motor.price_usd * _MOTOR_COUNT
        + esc.price_usd
        + fc.price_usd
        + frame.price_usd
        + propeller.price_usd  # sold as a set of 4
        + battery.price_usd
        + vtx.price_usd
        + receiver.price_usd
    )


def _make_build(
    motor: Component,
    esc: Component,
    fc: Component,
    frame: Component,
    propeller: Component,
    battery: Component,
    vtx: Component,
    receiver: Component,
    drone_class: str,
    idx: int,
) -> Build:
    """Assemble a Build dataclass from individual components."""
    return Build(
        name=f"Optimized {drone_class} #{idx}",
        drone_class=drone_class,
        components={
            "motor": [motor] * _MOTOR_COUNT,
            "esc": esc,
            "fc": fc,
            "frame": frame,
            "propeller": propeller,
            "battery": battery,
            "vtx": vtx,
            "receiver": receiver,
        },
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _thrust_class_value(label: str | None) -> float:
    """Convert a thrust_class label from the propeller spec into a number."""
    mapping = {
        "Very Low": 1.0,
        "Low": 2.0,
        "Low-Medium": 3.0,
        "Medium": 4.0,
        "Medium-High": 5.0,
        "High": 6.0,
        "Very High": 7.0,
    }
    return mapping.get(label or "", 4.0)


def _performance_score(build: Build) -> float:
    """Score based on estimated thrust-to-weight ratio.

    Higher KV, higher max-power motors, and higher-thrust props yield better
    performance.  The score is normalised to 0-100.
    """
    motor = build.motor
    if motor is None:
        return 0.0

    kv = motor.specs.get("kv", 0)
    max_power_w = motor.specs.get("max_power_w", 0)

    prop = build.get_component("propeller")
    thrust_val = _thrust_class_value(prop.specs.get("thrust_class") if prop else None)

    # Rough relative thrust proxy:  kv * max_power * thrust_val / AUW
    auw = build.all_up_weight_g or 1.0
    thrust_proxy = (kv * max_power_w * thrust_val) / auw

    # Normalise.  For a 5-inch quad this proxy is typically 5 000–20 000.
    # We clamp to 0-100.
    return min(100.0, max(0.0, thrust_proxy / 200.0))


def _weight_score(build: Build, drone_class: str) -> float:
    """Lighter-than-average builds score higher."""
    reference = _CLASS_REFERENCE_WEIGHT_G.get(drone_class, 500.0)
    auw = build.all_up_weight_g
    if auw <= 0:
        return 50.0
    ratio = auw / reference
    # ratio < 1 -> lighter than average -> high score
    # ratio = 1 -> average -> 50
    # ratio > 1 -> heavier -> low score
    score = 100.0 * (1.0 - (ratio - 0.5))  # 0.5 ratio -> 100, 1.5 -> 0
    return min(100.0, max(0.0, score))


def _price_score(total_cost: float, budget: float) -> float:
    """Cheaper relative to budget -> higher score."""
    if budget <= 0:
        return 0.0
    ratio = total_cost / budget
    # ratio = 0 -> 100; ratio = 1 -> 0
    return min(100.0, max(0.0, 100.0 * (1.0 - ratio)))


def _durability_score(build: Build) -> float:
    """Estimates durability from ESC current headroom and frame arm thickness."""
    score = 50.0  # base

    esc = build.get_component("esc")
    motor = build.motor

    if esc and motor:
        esc_amps = esc.specs.get("continuous_current_a", 0)
        motor_draw = motor.specs.get("max_current_a", 0)
        if motor_draw > 0:
            headroom = esc_amps / motor_draw
            # headroom >= 1.5 -> +30, headroom ~1.0 -> +0, headroom < 1 -> -20
            score += min(30.0, max(-20.0, (headroom - 1.0) * 60.0))

    frame = build.get_component("frame")
    if frame:
        arm_mm = frame.specs.get("arm_thickness_mm", 0)
        # 5 mm arms -> +20, 4 mm -> +10, 3 mm -> 0, 0 (whoop) -> 0
        score += min(20.0, max(0.0, (arm_mm - 3.0) * 10.0))

    return min(100.0, max(0.0, score))


def _score_build(
    build: Build,
    total_cost: float,
    request: OptimizationRequest,
) -> tuple[float, dict[str, float]]:
    """Compute the composite 0-100 score and a breakdown dict."""
    breakdown: dict[str, float] = {
        "performance": _performance_score(build),
        "weight": _weight_score(build, request.drone_class),
        "price": _price_score(total_cost, request.budget_usd),
        "durability": _durability_score(build),
    }

    # Normalise priority weights so they sum to 1.
    weights = request.priorities
    total_w = sum(weights.values()) or 1.0
    composite = sum(
        breakdown[k] * (weights.get(k, 0.0) / total_w)
        for k in breakdown
    )

    composite = min(100.0, max(0.0, composite))
    return composite, breakdown


# ---------------------------------------------------------------------------
# Constraint validation
# ---------------------------------------------------------------------------

# Constraint IDs that only apply to sub-250g builds (whoops, toothpicks).
# These should not penalise 5-inch or 3-inch builds that are inherently heavier.
_SUB250_CONSTRAINT_IDS: set[str] = {"wt_001", "wt_002"}

# Drone classes that are expected to stay under 250 g.
_SUB250_CLASSES: set[str] = {"whoop"}


def _has_critical_failure(build: Build) -> bool:
    """Return True if any constraint with severity=CRITICAL fails.

    Constraints whose IDs are in ``_SUB250_CONSTRAINT_IDS`` are only
    evaluated for drone classes listed in ``_SUB250_CLASSES``.
    """
    constraints = load_constraints()
    drone_class = build.drone_class
    for constraint in constraints:
        # Skip sub-250g constraints for larger builds.
        if constraint.id in _SUB250_CONSTRAINT_IDS and drone_class not in _SUB250_CLASSES:
            continue
        result: ValidationResult = evaluate_constraint(constraint, build)
        if not result.passed and result.severity == Severity.CRITICAL:
            return True
    return False


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------


def _generate_candidates(
    pool: dict[str, list[Component]],
    drone_class: str,
    budget: float,
) -> list[tuple[Build, float]]:
    """Generate candidate builds via greedy + random sampling.

    Returns a list of (Build, total_cost) tuples.
    """
    # Required component types.
    required = ["motor", "esc", "fc", "frame", "propeller", "battery", "vtx", "receiver"]

    # If any required type is missing, we cannot build.
    for rt in required:
        if rt not in pool or not pool[rt]:
            return []

    lists = [pool[rt] for rt in required]

    # Full cartesian product size.
    product_size = 1
    for lst in lists:
        product_size *= len(lst)
        if product_size > _MAX_CANDIDATES * 10:
            break

    candidates: list[tuple[Build, float]] = []
    seen_keys: set[str] = set()
    idx = 0

    if product_size <= _MAX_CANDIDATES:
        # Exhaustive for small product spaces.
        for combo in itertools.product(*lists):
            motor, esc, fc, frame, propeller, battery, vtx, receiver = combo
            cost = _build_total_price(motor, esc, fc, frame, propeller, battery, vtx, receiver)
            if cost > budget:
                continue
            idx += 1
            build = _make_build(motor, esc, fc, frame, propeller, battery, vtx, receiver, drone_class, idx)
            candidates.append((build, cost))
    else:
        # Greedy: cheapest of each type first.
        sorted_lists = [sorted(lst, key=lambda c: c.price_usd) for lst in lists]
        greedy = tuple(sl[0] for sl in sorted_lists)
        cost = _build_total_price(*greedy)
        if cost <= budget:
            idx += 1
            build = _make_build(*greedy, drone_class, idx)
            key = "-".join(c.id for c in greedy)
            seen_keys.add(key)
            candidates.append((build, cost))

        # Random sampling.
        attempts = 0
        max_attempts = _MAX_CANDIDATES * 5
        while len(candidates) < _MAX_CANDIDATES and attempts < max_attempts:
            attempts += 1
            combo = tuple(random.choice(lst) for lst in lists)
            key = "-".join(c.id for c in combo)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            motor, esc, fc, frame, propeller, battery, vtx, receiver = combo
            cost = _build_total_price(motor, esc, fc, frame, propeller, battery, vtx, receiver)
            if cost > budget:
                continue
            idx += 1
            build = _make_build(motor, esc, fc, frame, propeller, battery, vtx, receiver, drone_class, idx)
            candidates.append((build, cost))

    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimize(request: OptimizationRequest) -> list[BuildSuggestion]:
    """Return up to 5 optimized build suggestions for the given request.

    Algorithm:
    a. Filter components by category matching drone_class
    b. Filter by budget (total of all components <= budget)
    c. Generate candidate builds (greedy + random sampling)
    d. Score each build based on priority weights
    e. Run constraints on top candidates; filter out critical failures
    f. Return top 5, sorted by score descending
    """
    all_components = load_components()
    pool = _filter_by_category(all_components, request.drone_class)

    candidates = _generate_candidates(pool, request.drone_class, request.budget_usd)

    if not candidates:
        return []

    # Score all candidates.
    scored: list[BuildSuggestion] = []
    for build, cost in candidates:
        composite, breakdown = _score_build(build, cost, request)
        scored.append(
            BuildSuggestion(
                build=build,
                total_cost=cost,
                score=composite,
                score_breakdown=breakdown,
            )
        )

    # Sort by score descending.
    scored.sort(key=lambda s: s.score, reverse=True)

    # Take top N for constraint validation (expensive).
    top_candidates = scored[:_PRE_CONSTRAINT_TOP_N]

    # Filter out builds with critical constraint failures.
    validated: list[BuildSuggestion] = []
    for suggestion in top_candidates:
        if not _has_critical_failure(suggestion.build):
            validated.append(suggestion)
        if len(validated) >= _RESULT_TOP_N:
            break

    return validated[:_RESULT_TOP_N]


def suggest_quick(
    drone_class: str,
    budget_usd: float,
) -> BuildSuggestion | None:
    """Convenience: return the single best build for a class and budget.

    Returns ``None`` when no valid build can be found.
    """
    request = OptimizationRequest(drone_class=drone_class, budget_usd=budget_usd)
    results = optimize(request)
    return results[0] if results else None
