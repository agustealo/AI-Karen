"""Exact accounting, expiry and concurrency proof for Runtime's single budget meter."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime import contracts
from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter


def _clock(monkeypatch, initial: float = 100.0) -> dict[str, float]:
    observed = {"seconds": initial}
    monkeypatch.setattr(
        contracts,
        "time",
        SimpleNamespace(monotonic=lambda: observed["seconds"]),
    )
    return observed


@pytest.mark.asyncio
async def test_monotonic_deadline_is_fixed_on_first_start(monkeypatch) -> None:
    clock = _clock(monkeypatch)
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_duration_ms=1000, max_model_calls=2),
    )
    meter.start()
    clock["seconds"] = 100.6
    meter.start()
    assert await meter.check_duration() is True
    clock["seconds"] = 101.0
    assert await meter.check_duration() is False
    assert meter.exhausted is True
    assert await meter.reserve_model_call() is False
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_all_reservations_check_deadline_without_manual_check(monkeypatch) -> None:
    clock = _clock(monkeypatch)
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_duration_ms=750, max_model_calls=3, max_tool_calls=3),
    )
    meter.start()
    assert await meter.reserve_model_call() is True
    clock["seconds"] = 100.751
    assert await meter.reserve_tool_call() is False
    assert meter.tool_calls == 0
    assert meter.model_calls == 1
    assert meter.exhausted is True


@pytest.mark.asyncio
async def test_unstarted_meter_starts_on_first_accounted_operation(monkeypatch) -> None:
    clock = _clock(monkeypatch)
    meter = ExecutionBudgetMeter(ExecutionBudget(max_duration_ms=100))
    assert await meter.reserve_model_call() is True
    clock["seconds"] = 100.101
    assert await meter.reserve_model_call() is False
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_concurrent_model_reservations_never_exceed_authorized_limit() -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_model_calls=3, max_duration_ms=30000),
    )
    meter.start()
    results = await asyncio.gather(*(meter.reserve_model_call() for _ in range(32)))
    assert sum(results) == 3
    assert meter.model_calls == 3
    assert meter.exhausted is True
    assert await meter.reserve_model_call() is False
    assert meter.model_calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "counter"),
    [
        ("reserve_model_call", "model_calls"),
        ("reserve_reasoning_step", "reasoning_steps"),
        ("reserve_tool_call", "tool_calls"),
        ("reserve_agent_turn", "agent_turns"),
        ("reserve_external_request", "external_requests"),
    ],
)
async def test_rejected_unit_reservations_do_not_inflate_usage(
    method: str, counter: str,
) -> None:
    budget = ExecutionBudget(
        max_model_calls=1,
        max_reasoning_steps=1,
        max_tool_calls=1,
        max_agent_turns=1,
        max_external_requests=1,
    )
    meter = ExecutionBudgetMeter(budget)
    meter.start()
    action = getattr(meter, method)
    assert await action() is True
    assert await action() is False
    assert getattr(meter, counter) == 1
    assert meter.exhausted is True


@pytest.mark.asyncio
@pytest.mark.parametrize("method,counter", [
    ("add_input_tokens", "input_tokens"),
    ("add_output_tokens", "output_tokens"),
])
async def test_token_usage_never_exceeds_budget_or_counts_failed_reservations(
    method: str, counter: str,
) -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_input_tokens=5, max_output_tokens=5),
    )
    meter.start()
    action = getattr(meter, method)
    assert await action(3) is True
    assert await action(2) is True
    assert await action(1) is False
    assert getattr(meter, counter) == 5
    assert meter.exhausted is True


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [-1, -100, True, False, 1.5, "1", None])
async def test_invalid_token_usage_cannot_refund_or_corrupt_budget(invalid) -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_input_tokens=10))
    meter.start()
    assert await meter.add_input_tokens(5) is True
    with pytest.raises(ValueError, match="nonnegative integer"):
        await meter.add_input_tokens(invalid)
    assert meter.input_tokens == 5
    assert meter.exhausted is False
    assert await meter.add_input_tokens(5) is True


@pytest.mark.asyncio
async def test_zero_model_budget_is_never_counted_as_an_actual_model_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=0))
    meter.start()
    assert await meter.consume_model_call() is False
    assert meter.model_calls == 0
    assert meter.exhausted is True


@pytest.mark.asyncio
async def test_misconfigured_non_integer_limit_fails_before_counting() -> None:
    budget = ExecutionBudget(max_model_calls=True)
    meter = ExecutionBudgetMeter(budget)
    with pytest.raises(ValueError, match="limit must be a nonnegative integer"):
        await meter.reserve_model_call()
    assert meter.model_calls == 0
    assert meter.exhausted is False


@pytest.mark.asyncio
async def test_external_model_transport_reserves_both_quotas_atomically() -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_model_calls=3, max_external_requests=1),
    )
    assert await meter.reserve_model_execution(external=True) is True
    assert meter.model_calls == 1
    assert meter.external_requests == 1
    assert await meter.reserve_model_execution(external=True) is False
    assert meter.model_calls == 1
    assert meter.external_requests == 1
    assert meter.exhausted is True


@pytest.mark.asyncio
async def test_model_quota_rejection_never_partially_spends_external_quota() -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_model_calls=0, max_external_requests=3),
    )
    assert await meter.reserve_model_execution(external=True) is False
    assert meter.model_calls == 0
    assert meter.external_requests == 0


@pytest.mark.asyncio
async def test_concurrent_nested_model_calls_share_atomic_external_budget() -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_model_calls=2, max_external_requests=2),
    )
    results = await asyncio.gather(
        *(meter.reserve_model_execution(external=True) for _ in range(24))
    )
    assert sum(results) == 2
    assert meter.model_calls == 2
    assert meter.external_requests == 2


@pytest.mark.asyncio
async def test_local_model_execution_does_not_spend_external_quota() -> None:
    meter = ExecutionBudgetMeter(
        ExecutionBudget(max_model_calls=2, max_external_requests=0),
    )
    assert await meter.reserve_model_execution(external=False) is True
    assert meter.model_calls == 1
    assert meter.external_requests == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, 0, 1, "yes", "false"])
async def test_external_reservation_mode_must_be_a_literal_boolean(invalid) -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget())
    with pytest.raises(ValueError, match="must be a boolean"):
        await meter.reserve_model_execution(external=invalid)
    assert meter.model_calls == 0
    assert meter.external_requests == 0


@pytest.mark.asyncio
async def test_original_remaining_deadline_cannot_be_extended_by_child_runtime(monkeypatch):
    clock = _clock(monkeypatch)
    meter = ExecutionBudgetMeter(ExecutionBudget(max_duration_ms=1000))
    meter.start()
    assert await meter.remaining_duration_ms() == pytest.approx(1000.0)
    clock["seconds"] = 100.4
    meter.start()
    assert await meter.remaining_duration_ms() == pytest.approx(600.0)
    clock["seconds"] = 101.0
    assert await meter.remaining_duration_ms() == 0.0
    assert meter.exhausted is True
    assert await meter.reserve_model_execution() is False


@pytest.mark.asyncio
async def test_admitted_duration_survives_sibling_quota_denial_but_never_expiry(monkeypatch):
    clock = _clock(monkeypatch)
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1, max_duration_ms=1000))
    assert await meter.remaining_admitted_duration_ms() == 0
    assert await meter.reserve_model_execution()
    assert not await meter.reserve_model_execution()
    assert meter.exhausted
    assert await meter.remaining_duration_ms() == 0
    clock["seconds"] = 100.4
    assert await meter.remaining_admitted_duration_ms() == pytest.approx(600.0)
    clock["seconds"] = 101.0
    assert await meter.remaining_admitted_duration_ms() == 0
    assert not await meter.reserve_model_execution()
    assert meter.model_calls == 1
