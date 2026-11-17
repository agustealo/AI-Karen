"""Adversarial proof that only an observed model may complete normal chat.

This validates the canonical ExpressionGateway boundary used by ChatRuntime.
All engines are isolated in-process: no network, fabricated service health,
or implicit external provider configuration is required.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionResult, ExpressionTask
from ai_karen_engine.core.expression.errors import EngineUnavailableError
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings


def _settings(*, fallback: bool) -> ExpressionSettings:
    settings = ExpressionSettings(
        active_engine="local",
        engine_fallback_order=["cloud"] if fallback else [],
    )
    settings.engines["local"] = EngineConfig(
        enabled=True,
        type="openai_compatible",
        fallback_eligible=fallback,
    )
    settings.engines["cloud"] = EngineConfig(
        enabled=fallback,
        type="openai_compatible",
        fallback_eligible=True,
    )
    settings.policies.allow_external_engines = fallback
    # Fallback scenarios isolate generation provenance, not user RBAC.
    settings.policies.require_admin_for_external = False
    return settings


def _task(*, sink=None) -> ExpressionTask:
    return ExpressionTask(
        task_id="chat-provenance-integrity",
        kind="chat",
        messages=[{"role": "user", "content": "Explain the evidence."}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        token_sink=sink,
        preferred_provider="auto",
        max_tokens=120,
    )


def _receipt(
    task: ExpressionTask,
    *,
    engine_id: str,
    provider: str | None = "ollama-local",
    model: str | None = "observed-model",
    source: str = "provider_runtime",
    text: str = "A model generated this explanation.",
    task_id: str | None = None,
) -> ExpressionResult:
    return ExpressionResult(
        task_id=task_id or task.task_id,
        text=text,
        provider=provider,
        model=model,
        engine_id=engine_id,
        engine_mode="openai_compatible",
        runtime_engine="ollama" if engine_id == "local" else "cloud",
        response_source=source,
        attempts=[],
        skipped=[],
        latency_ms=2.0,
        degraded=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "model", "source", "task_id"),
    [
        ("ollama-local", None, "provider_runtime", None),
        ("ollama-local", "", "provider_runtime", None),
        ("", "observed-model", "provider_runtime", None),
        ("ollama-local", "observed-model", "emergency_static", None),
        ("ollama-local", "observed-model", "engine_disabled", None),
        ("ollama-local", "observed-model", "persisted_history", None),
        ("ollama-local", "observed-model", "model_unavailable", None),
        ("ollama-local", "observed-model", "model", "foreign-chat-request"),
    ],
)
async def test_unverified_receipts_fail_closed(
    provider: str,
    model: str | None,
    source: str,
    task_id: str | None,
) -> None:
    class Engine:
        async def generate(self, task):
            return _receipt(
                task,
                engine_id="local",
                provider=provider,
                model=model,
                source=source,
                task_id=task_id,
            )

    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        with pytest.raises(EngineUnavailableError, match="No model engine produced"):
            await ExpressionGateway(_settings(fallback=False)).generate(_task())


@pytest.mark.asyncio
async def test_non_model_primary_can_recover_only_through_verified_model() -> None:
    visited: list[str] = []

    class Engine:
        def __init__(self, engine_id: str):
            self.engine_id = engine_id

        async def generate(self, task):
            visited.append(self.engine_id)
            if self.engine_id == "local":
                return _receipt(
                    task,
                    engine_id="local",
                    source="emergency_static",
                    text="Static unavailable text masquerading as a model.",
                )
            return _receipt(
                task,
                engine_id="cloud",
                provider="cloud-provider",
                model="cloud-model",
                source="provider_runtime",
                text="A genuine generated answer.",
            )

    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _type: Engine(engine_id),
    ):
        result = await ExpressionGateway(_settings(fallback=True)).generate(_task())

    assert visited == ["local", "cloud"]
    assert result.text == "A genuine generated answer."
    assert result.provider == "cloud-provider"
    assert result.model == "cloud-model"
    assert result.response_source == "provider_runtime"
    assert result.degraded is True
    assert result.degradation_reason == "model_engine_fallback"
    assert result.metadata["fallback_level"] == 1
    assert [item["outcome"] for item in result.metadata["engine_attempt_timings"]] == [
        "invalid_output",
        "verified_model",
    ]
    assert result.metadata["skipped_engines"][0]["reason"] == "non_model_output_rejected"


@pytest.mark.asyncio
async def test_visible_partial_response_cannot_switch_after_static_terminal_receipt() -> None:
    deltas: list[str] = []
    visited: list[str] = []

    async def sink(text: str) -> None:
        deltas.append(text)

    class Engine:
        def __init__(self, engine_id: str):
            self.engine_id = engine_id

        async def generate(self, task):
            visited.append(self.engine_id)
            if self.engine_id == "local":
                task.stream_started = True
                await task.token_sink("Unfinished")
                return _receipt(
                    task,
                    engine_id="local",
                    source="emergency_static",
                    text="Unfinished",
                )
            return _receipt(task, engine_id="cloud")

    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _type: Engine(engine_id),
    ):
        with pytest.raises(
            EngineUnavailableError, match="partial_provider_stream_unverified"
        ):
            await ExpressionGateway(_settings(fallback=True)).generate(
                _task(sink=sink)
            )

    assert deltas == ["Unfinished"]
    assert visited == ["local"]


@pytest.mark.asyncio
async def test_gateway_preserves_intra_engine_provider_fallback_receipt() -> None:
    class Engine:
        async def generate(self, task):
            receipt = _receipt(
                task,
                engine_id="local",
                source="fallback_provider_runtime",
                provider="alternate-local",
                model="alternate-model",
                text="Response from another registered provider.",
            )
            receipt.metadata["fallback_level"] = 1
            return receipt

    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        result = await ExpressionGateway(_settings(fallback=False)).generate(_task())

    assert result.degraded is True
    assert result.degradation_reason == "provider_fallback"
    assert result.metadata["fallback_level"] == 1
    assert result.provider == "alternate-local"
    assert result.model == "alternate-model"


@pytest.mark.asyncio
async def test_gateway_adds_engine_and_provider_fallback_hops_without_hiding_them() -> None:
    class Engine:
        def __init__(self, engine_id):
            self.engine_id = engine_id

        async def generate(self, task):
            if self.engine_id == "local":
                raise RuntimeError("Primary engine failed")
            result = _receipt(task, engine_id="cloud", provider="actual-cloud")
            result.metadata["fallback_level"] = 1
            return result

    with patch(
        "ai_karen_engine.core.expression.gateway.get_engine",
        side_effect=lambda engine_id, _type: Engine(engine_id),
    ):
        result = await ExpressionGateway(_settings(fallback=True)).generate(_task())

    assert result.degraded is True
    assert result.degradation_reason == "model_engine_fallback"
    assert result.metadata["fallback_level"] == 2
    assert result.metadata["engine_attempt_timings"][-1]["fallback_level"] == 1


@pytest.mark.asyncio
async def test_foreign_engine_receipt_is_not_a_model_completion() -> None:
    class Engine:
        async def generate(self, task):
            return _receipt(task, engine_id="foreign-engine")

    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        with pytest.raises(EngineUnavailableError, match="No model engine produced"):
            await ExpressionGateway(_settings(fallback=False)).generate(_task())


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_level", [-1, True, "one", 1.5])
async def test_malformed_internal_fallback_receipts_cannot_be_laundered(
    bad_level,
) -> None:
    class Engine:
        async def generate(self, task):
            result = _receipt(task, engine_id="local")
            result.metadata["fallback_level"] = bad_level
            return result

    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        with pytest.raises(EngineUnavailableError, match="No model engine produced"):
            await ExpressionGateway(_settings(fallback=False)).generate(_task())
