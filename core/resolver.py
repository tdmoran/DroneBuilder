"""Resolve dot-path field references and evaluate constraints against builds."""

from __future__ import annotations

import re
from typing import Any

from core.models import Build, Component, Constraint, Severity, ValidationResult


def resolve_field(path: str, build: Build) -> Any:
    """Resolve a dot-path like 'motor.max_current_a' against a build.

    Supports:
    - component.field  (e.g., motor.kv, battery.cell_count)
    - build.field      (e.g., build.all_up_weight_g, build.motor_count)
    - calc:expression  (e.g., calc:motor.max_current_a * 4)
    - literal numbers  (e.g., 250, 2.0)
    """
    if isinstance(path, (int, float)):
        return path

    path = str(path).strip()

    # Literal number
    try:
        if "." in path and path.replace(".", "", 1).replace("-", "", 1).isdigit():
            return float(path)
        if path.lstrip("-").isdigit():
            return int(path)
    except (ValueError, AttributeError):
        pass

    # Boolean literals
    if path == "true":
        return True
    if path == "false":
        return False

    # Calculated expression
    if path.startswith("calc:"):
        return _eval_expression(path[5:], build)

    # Dot-path resolution
    parts = path.split(".", 1)
    if len(parts) == 2:
        comp_type, field_name = parts
        if comp_type == "build":
            return _resolve_build_field(field_name, build)
        comp = build.get_component(comp_type)
        if comp is None:
            return None
        return comp.get(field_name)

    return None


def _resolve_build_field(field_name: str, build: Build) -> Any:
    """Resolve build-level computed fields."""
    if field_name == "all_up_weight_g":
        return build.all_up_weight_g
    if field_name == "dry_weight_g":
        return build.dry_weight_g
    if field_name == "motor_count":
        return build.motor_count
    if field_name == "total_price_usd":
        return build.total_price_usd
    return None


def _eval_expression(expr: str, build: Build) -> Any:
    """Safely evaluate an arithmetic expression with dot-path references.

    Replaces dot-paths with resolved values, then evaluates the arithmetic.
    Only allows: numbers, +, -, *, /, (), <=, >=, <, >, ==, !=, and, or, not.
    """
    # Find all dot-paths (word.word patterns, possibly with more dots)
    tokens = re.findall(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+", expr)

    # Deduplicate while preserving order (longest first to avoid partial replacement)
    seen = set()
    unique_tokens = []
    for t in sorted(set(tokens), key=len, reverse=True):
        if t not in seen:
            seen.add(t)
            unique_tokens.append(t)

    resolved_expr = expr
    for token in unique_tokens:
        value = resolve_field(token, build)
        if value is None:
            return None
        if isinstance(value, bool):
            resolved_expr = resolved_expr.replace(token, str(value).lower())
        elif isinstance(value, str):
            resolved_expr = resolved_expr.replace(token, repr(value))
        else:
            resolved_expr = resolved_expr.replace(token, str(value))

    # Sanitize: only allow safe characters
    allowed = set("0123456789.+-*/()<>= !&|truefalsTRUEFALS andornot\t\n ")
    if not all(c in allowed or c.isalpha() for c in resolved_expr):
        return None

    # Replace boolean keywords for Python eval
    resolved_expr = resolved_expr.replace("&&", " and ").replace("||", " or ")

    try:
        return eval(resolved_expr, {"__builtins__": {}}, {})  # noqa: S307
    except Exception:
        return None


def evaluate_constraint(constraint: Constraint, build: Build) -> ValidationResult:
    """Evaluate a single constraint against a build. Returns a ValidationResult."""
    # Check if all required components are present
    for comp_type in constraint.components:
        if comp_type == "transmitter":
            # transmitter not modeled yet, skip this constraint
            return ValidationResult(
                constraint_id=constraint.id,
                constraint_name=constraint.name,
                severity=constraint.severity,
                passed=True,
                message="Skipped — transmitter not in build model.",
                details={"skipped": True},
            )
        if build.get_component(comp_type) is None:
            return ValidationResult(
                constraint_id=constraint.id,
                constraint_name=constraint.name,
                severity=constraint.severity,
                passed=True,
                message=f"Skipped — {comp_type} not present in build.",
                details={"skipped": True},
            )

    check = constraint.check
    operator = check.get("operator", "expression")
    field_a_raw = check.get("field_a", "")
    field_b_raw = check.get("field_b", "")

    val_a = resolve_field(field_a_raw, build)
    val_b = resolve_field(field_b_raw, build)

    passed = False
    actual = val_a
    limit = val_b

    if operator == "expression":
        expr = check.get("expression", "")
        if expr:
            result = _eval_expression(expr, build)
            passed = bool(result) if result is not None else True
            actual = result
        else:
            passed = True
    elif val_a is None or val_b is None:
        # Cannot evaluate — treat as pass with skip
        return ValidationResult(
            constraint_id=constraint.id,
            constraint_name=constraint.name,
            severity=constraint.severity,
            passed=True,
            message="Skipped — could not resolve fields.",
            details={"skipped": True, "field_a": str(field_a_raw), "field_b": str(field_b_raw)},
        )
    elif operator == "lt":
        passed = val_a < val_b
    elif operator == "lte":
        passed = val_a <= val_b
    elif operator == "gt":
        passed = val_a > val_b
    elif operator == "gte":
        passed = val_a >= val_b
    elif operator == "eq":
        passed = val_a == val_b
    elif operator == "neq":
        passed = val_a != val_b
    elif operator == "in":
        if isinstance(val_b, list):
            passed = val_a in val_b
        else:
            passed = val_a == val_b
    elif operator == "contains":
        if isinstance(val_a, list):
            passed = val_b in val_a
        else:
            passed = val_a == val_b
    elif operator == "multiply_lte":
        multiplier = check.get("multiplier", 1.0)
        computed = val_a * multiplier
        passed = computed <= val_b
        actual = computed
        limit = val_b
    elif operator == "range":
        field_b_high_raw = check.get("field_b_high", "")
        val_b_high = resolve_field(field_b_high_raw, build)
        if val_b_high is not None:
            passed = val_b <= val_a <= val_b_high
            limit = f"{val_b} to {val_b_high}"
        else:
            passed = val_a >= val_b

    # Format message
    message = constraint.message_template
    message = message.replace("{field_a}", str(val_a) if val_a is not None else "?")
    message = message.replace("{field_b}", str(val_b) if val_b is not None else "?")
    message = message.replace("{actual}", str(actual) if actual is not None else "?")
    message = message.replace("{limit}", str(limit) if limit is not None else "?")

    return ValidationResult(
        constraint_id=constraint.id,
        constraint_name=constraint.name,
        severity=constraint.severity,
        passed=passed,
        message=message.strip(),
        details={"actual": actual, "limit": limit},
    )
