"""Assertion helpers for COG-EVAL-1.

Translate an ExpectedSpec into concrete pass/fail checks over a CognitiveResult.
Pure functions so they can be unit-tested in isolation.
"""

from __future__ import annotations

from typing import Any

from benchmarks.cognitive.contracts import CognitiveResult, ExpectedSpec


def _norm(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().lower()


def assert_expectations(result: CognitiveResult, expected: ExpectedSpec) -> list[str]:
    """Return a list of human-readable failure messages (empty == pass)."""
    failures: list[str] = []

    if expected.result and _norm(result.verdict) != _norm(expected.result):
        failures.append(
            f"verdict mismatch: expected '{expected.result}', got '{result.verdict}'"
        )

    if (expected.confidence_min or expected.confidence_max) and not (
        expected.confidence_min <= result.confidence <= expected.confidence_max
    ):
        failures.append(
            f"confidence {result.confidence:.3f} outside "
            f"[{expected.confidence_min}, {expected.confidence_max}]"
        )


    if expected.active is not None and bool(result.active) != bool(expected.active):
        failures.append(f"active mismatch: expected {expected.active}, got {result.active}")

    if expected.retained is not None and bool(result.retained) != bool(expected.retained):
        failures.append(f"retained mismatch: expected {expected.retained}, got {result.retained}")

    if expected.tenant_scoped is not None and bool(result.tenant_scoped) != bool(expected.tenant_scoped):
        failures.append(
            f"tenant_scoped mismatch: expected {expected.tenant_scoped}, got {result.tenant_scoped}"
        )

    if expected.policy_violation is not None and bool(result.policy_violation) != bool(expected.policy_violation):
        failures.append(
            f"policy_violation mismatch: expected {expected.policy_violation}, got {result.policy_violation}"
        )

    if expected.promoted_to_trusted is not None and bool(result.promoted_to_trusted) != bool(expected.promoted_to_trusted):
        failures.append(
            f"promoted_to_trusted mismatch: expected {expected.promoted_to_trusted}, got {result.promoted_to_trusted}"
        )

    result_set = set(result.appears_in)
    for token in (expected.appears_in or []):
        if _norm(token) not in {_norm(t) for t in result_set}:
            failures.append(f"expected '{token}' in appears_in, not found")

    for token in (expected.not_appears_in or []):
        if _norm(token) in {_norm(t) for t in result_set}:
            failures.append(f"unexpected '{token}' appeared in appears_in")

    if expected.flags:
        for key, value in expected.flags.items():
            actual = result.flags.get(key)
            if actual is None:
                continue
            if _norm(actual) != _norm(value) and actual != value:
                failures.append(f"flag '{key}' mismatch: expected '{value}', got '{actual}'")

    return failures


def assert_no_defects(result: CognitiveResult) -> list[str]:
    if result.defects:
        descs = [f"{d.severity.value}:{d.expected} vs {d.actual} ({d.detail})" for d in result.defects]
        return [f"unexpected defects: {'; '.join(descs)}"]
    return []


def assert_has_defects(result: CognitiveResult, count: int | None = None) -> list[str]:
    if count is not None and len(result.defects) != count:
        return [f"expected {count} defect(s), got {len(result.defects)}"]
    if not result.defects:
        return ["expected at least one defect, found none"]
    return []


def evaluate(result: CognitiveResult, expected: ExpectedSpec) -> list[str]:
    """Aggregate all checks for a single scenario."""
    failures = assert_expectations(result, expected)
    if expected.result and "DEFECT" not in expected.result.upper():
        failures.extend(assert_no_defects(result))
    return failures
