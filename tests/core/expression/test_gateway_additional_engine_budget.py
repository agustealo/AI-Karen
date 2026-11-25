"""Adversarial proof for charged ExpressionGateway fallback engine attempts.

The initial model call is charged by canonical ChatRuntime, before the gateway.
Only an additional enabled, non-circuit-open engine selected for execution may
reserve another call. The original Runtime meter owns every reservation.
"""

from __future__ import annotations

import traceback
from unittest.mock import patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionResult, ExpressionTask
from ai_karen_engine.core.expression.errors import EngineUnavailableError, PrivateEvidenceAuthorizationError
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings
from ai_karen_engine.core.runtime.contracts import ExecutionBudget, ExecutionBudgetMeter


def _settings(
    *,
    cloud_enabled: bool = True,
    extra_engine: bool = False,
    local_enabled: bool = True,
    external_allowed: bool = True,
    admin_required: bool = False,
) -> ExpressionSettings:
    order = ["cloud", "alternate"] if extra_engine else ["cloud"]
    settings = ExpressionSettings(
        active_engine="local",
        engine_fallback_order=order,
    )
    settings.policies.allow_external_engines = external_allowed
    settings.policies.require_admin_for_external = admin_required
    settings.engines["local"] = EngineConfig(
        enabled=local_enabled,
        type="openai_compatible",
        fallback_eligible=True,
    )
    settings.engines["cloud"] = EngineConfig(
        enabled=cloud_enabled,
        type="openai_compatible",
        fallback_eligible=True,
    )
    if extra_engine:
        settings.engines["alternate"] = EngineConfig(
            enabled=True,
            type="openai_compatible",
            fallback_eligible=True,
        )
    return settings


def _task(meter: ExecutionBudgetMeter, *, sink=None) -> ExpressionTask:
    return ExpressionTask(
        task_id="authorized-runtime-generation",
        kind="chat",
        messages=[{"role": "user", "content": "Explain the evidence"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        correlation_id="cid-budget",
        request_id="rid-budget",
        preferred_provider="auto",
        reserve_additional_model_call=meter.consume_model_call,
        token_sink=sink,
    )


def _verified(task: ExpressionTask, engine_id: str) -> ExpressionResult:
    return ExpressionResult(
        task_id=task.task_id,
        text="Generated answer",
        provider="registered-provider",
        model="verified-model",
        engine_id=engine_id,
        engine_mode="openai_compatible",
        runtime_engine="openai_compatible",
        response_source="provider_runtime",
        attempts=[],
        skipped=[],
        latency_ms=2.0,
    )


class _FakeEngine:
    def __init__(self, engine_id: str, visited: list[str], *, fail_primary=True):
        self.engine_id = engine_id
        self.visited = visited
        self.fail_primary = fail_primary

    async def generate(self, task: ExpressionTask) -> ExpressionResult:
        self.visited.append(self.engine_id)
        if self.engine_id == "local" and self.fail_primary:
            raise RuntimeError("primary failed")
        return _verified(task, self.engine_id)


def test_availability_rejects_cloud_only_when_external_execution_forbidden() -> None:
    settings = _settings(local_enabled=False, external_allowed=False)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = ["cloud"]

    available, reason = ExpressionGateway(settings).availability()

    assert available is False
    assert reason is not None
    assert "cloud:external_engines_forbidden" in reason


def test_availability_can_use_local_fallback_when_cloud_is_forbidden() -> None:
    settings = _settings(local_enabled=True, external_allowed=False)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = ["local"]

    available, reason = ExpressionGateway(settings).availability()

    assert available is True
    assert reason is None


@pytest.mark.asyncio
async def test_successful_second_engine_consumes_one_more_original_model_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(_settings()).generate(_task(meter))

    assert visited == ["local", "cloud"]
    assert result.model == "verified-model"
    assert result.metadata["fallback_level"] == 1
    assert meter.model_calls == 2
    assert meter.exhausted is False
    assert [item["engine_id"] for item in result.metadata["engine_attempt_timings"]] == visited


@pytest.mark.asyncio
async def test_unavailable_extra_call_budget_prevents_fallback_provider_invocation() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(
            EngineUnavailableError,
            match="execution_budget_exhausted_max_model_calls",
        ):
            await ExpressionGateway(_settings()).generate(_task(meter))

    assert visited == ["local"]
    assert meter.model_calls == 1
    assert meter.exhausted is True


@pytest.mark.asyncio
async def test_disabled_engine_is_skipped_without_consuming_an_additional_model_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(
            _settings(cloud_enabled=False, extra_engine=True)
        ).generate(_task(meter))

    assert visited == ["local", "alternate"]
    assert result.metadata["fallback_level"] == 2
    assert {
        "engine_id": "cloud", "reason": "disabled",
    } in result.metadata["skipped_engines"]
    assert meter.model_calls == 2


@pytest.mark.asyncio
async def test_disabled_primary_does_not_count_as_an_extra_attempt() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(
            _settings(local_enabled=False)
        ).generate(_task(meter))

    assert visited == ["cloud"]
    assert result.metadata["fallback_level"] == 1
    assert meter.model_calls == 1
    assert meter.exhausted is False


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, None, 1, "yes"])
async def test_only_true_from_original_meter_authorizes_fallback(invalid) -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    task = _task(meter)

    async def invalid_guard():
        return invalid

    task.reserve_additional_model_call = invalid_guard
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(
            EngineUnavailableError,
            match="execution_budget_exhausted_max_model_calls",
        ):
            await ExpressionGateway(_settings()).generate(task)

    assert visited == ["local"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_guard_exception_fails_closed_before_any_second_provider_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    task = _task(meter)

    async def broken_guard():
        raise PermissionError("host detail must not leak")

    task.reserve_additional_model_call = broken_guard
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(
            EngineUnavailableError, match="execution_budget_guard_failed"
        ) as captured:
            await ExpressionGateway(_settings()).generate(task)
    assert "host detail must not leak" not in "".join(
        traceback.format_exception(captured.value)
    )
    assert visited == ["local"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_partial_stream_never_switches_models_or_reserves_extra_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    deltas: list[str] = []
    visited: list[str] = []

    async def sink(text: str) -> None:
        deltas.append(text)

    class StreamingEngine(_FakeEngine):
        async def generate(self, task):
            self.visited.append(self.engine_id)
            if self.engine_id == "local":
                task.stream_started = True
                await task.token_sink("Partially rendered")
                raise RuntimeError("wire terminated early")
            return _verified(task, self.engine_id)

    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: StreamingEngine(engine_id, visited),
    ):
        with pytest.raises(
            EngineUnavailableError,
            match="partial_provider_stream_unverified",
        ):
            await ExpressionGateway(_settings()).generate(_task(meter, sink=sink))
    assert deltas == ["Partially rendered"]
    assert visited == ["local"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_single_verified_engine_never_reserves_an_extra_call() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(
            engine_id, visited, fail_primary=False,
        ),
    ):
        result = await ExpressionGateway(_settings()).generate(_task(meter))
    assert result.text == "Generated answer"
    assert visited == ["local"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_external_provider_policy_denies_enabled_cloud_engine_before_invocation() -> None:
    # A runtime setting enabling an endpoint is never a grant to send private
    # chat context outside the installation.
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    settings = _settings(external_allowed=False)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = []
    task = _task(meter)
    task.preferred_provider = "gemini"
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(
            engine_id, visited, fail_primary=False,
        ),
    ):
        with pytest.raises(EngineUnavailableError, match="No model engine produced"):
            await ExpressionGateway(settings).generate(task)

    assert visited == []
    assert meter.model_calls == 1
    assert meter.exhausted is False


@pytest.mark.asyncio
async def test_external_policy_blocks_cloud_fallback_without_spending_extra_quota() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(
            _settings(external_allowed=False, extra_engine=True)
        ).generate(_task(meter))

    assert visited == ["local", "alternate"]
    assert result.metadata["fallback_level"] == 2
    assert {
        "engine_id": "cloud", "reason": "external_engines_forbidden",
    } in result.metadata["skipped_engines"]
    assert meter.model_calls == 2


@pytest.mark.asyncio
async def test_cloud_only_requires_trusted_runtime_admin_guard() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    settings = _settings(local_enabled=False, admin_required=True)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = []
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(EngineUnavailableError, match="No model engine produced"):
            await ExpressionGateway(settings).generate(_task(meter))
    assert visited == []
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_explicit_admin_approval_allows_cloud_only_engine() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    settings = _settings(local_enabled=False, admin_required=True)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = []
    task = _task(meter)

    async def authorize():
        return True

    task.authorize_external_engine_attempt = authorize
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(settings).generate(task)
    assert result.model == "verified-model"
    assert visited == ["cloud"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", [False, None, 1, "admin"])
async def test_cloud_guard_requires_literal_true(approval) -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    settings = _settings(local_enabled=False, admin_required=True)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = []
    task = _task(meter)

    async def authorize():
        return approval

    task.authorize_external_engine_attempt = authorize
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(EngineUnavailableError):
            await ExpressionGateway(settings).generate(task)
    assert visited == []
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_external_admin_guard_exception_fails_closed_without_secret_leak() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=1))
    assert await meter.consume_model_call() is True
    settings = _settings(local_enabled=False, admin_required=True)
    settings.active_engine = "cloud"
    settings.engine_fallback_order = []
    task = _task(meter)

    async def authorize():
        raise PermissionError("private token: must not appear in a traceback")

    task.authorize_external_engine_attempt = authorize
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(EngineUnavailableError) as captured:
            await ExpressionGateway(settings).generate(task)
    assert "private token" not in "".join(traceback.format_exception(captured.value))
    assert visited == []
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_cloud_fallback_denied_by_role_uses_only_authorized_local_engines() -> None:
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    task = _task(meter)
    settings = _settings(extra_engine=True, admin_required=True)
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(settings).generate(task)
    assert visited == ["local", "alternate"]
    assert meter.model_calls == 2
    assert {"engine_id": "cloud", "reason": "external_admin_permission_required"} in result.metadata["skipped_engines"]


@pytest.mark.asyncio
@pytest.mark.parametrize("admin_required", [False, True])
async def test_private_evidence_local_failure_never_attempts_cloud(admin_required):
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    task = _task(meter)
    task.local_only = True
    task.authorize_private_evidence_attempt = _allow_private_evidence

    async def authorize():
        pytest.fail("Private evidence must not request external approval")

    task.authorize_external_engine_attempt = authorize
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(EngineUnavailableError):
            await ExpressionGateway(_settings(admin_required=admin_required)).generate(task)
    assert visited == ["local"]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_private_evidence_eligible_fallback_uses_original_budget():
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    task = _task(meter)
    task.local_only = True
    task.authorize_private_evidence_attempt = _allow_private_evidence
    visited: list[str] = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        result = await ExpressionGateway(_settings(extra_engine=True)).generate(task)
    assert visited == ["local", "alternate"]
    assert meter.model_calls == 2
    assert {"engine_id": "cloud", "reason": "private_evidence_local_only"} in result.metadata["skipped_engines"]


async def _allow_private_evidence() -> bool:
    return True


@pytest.mark.asyncio
@pytest.mark.parametrize("approval", [None, False, 1, "yes"])
async def test_private_evidence_denied_before_initial_attempt(approval):
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    task = _task(meter)
    task.local_only = True

    async def guard():
        return approval

    task.authorize_private_evidence_attempt = guard if approval is not None else None
    visited = []
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(PrivateEvidenceAuthorizationError, match="attachment_session_denied"):
            await ExpressionGateway(_settings(extra_engine=True)).generate(task)
    assert visited == []
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_private_evidence_revoked_between_engine_attempts():
    meter = ExecutionBudgetMeter(ExecutionBudget(max_model_calls=2))
    assert await meter.consume_model_call() is True
    task = _task(meter)
    task.local_only = True
    visited = []

    async def guard():
        return not visited

    task.authorize_private_evidence_attempt = guard
    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _: _FakeEngine(engine_id, visited),
    ):
        with pytest.raises(PrivateEvidenceAuthorizationError, match="attachment_session_denied"):
            await ExpressionGateway(_settings(extra_engine=True)).generate(task)
    assert visited == ["local"]
    assert meter.model_calls == 1
