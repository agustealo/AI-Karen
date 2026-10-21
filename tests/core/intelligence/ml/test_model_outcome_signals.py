"""Learning observes durable runtime truth without acquiring routing authority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
    MODEL_SIGNAL_VERSION,
    ModelOutcomeSignalService,
    ScopedModelSignals,
    choose_operationally_learned_model,
    derive_model_signals,
)

TENANT = "tenant-1"
USER = "user-1"
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def outcome(
    index: int, *, model: str = "model-a", provider: str = "ollama-local",
    status: str = "success", task: str = "research", tenant: str = TENANT,
    user: str = USER, fallback: int = 0, source: str = "runtime.execution",
    recorded_at: str | None = None, attribution: str = "single_provider_model",
    completed: bool | None = None,
) -> dict:
    return {
        "outcome_id": f"out-{model}-{index}",
        "tenant_id": tenant, "user_id": user, "source": source,
        "recorded_at": recorded_at or NOW.isoformat(),
        "status": status,
        "response_completed": (status == "success" if completed is None else completed),
        "latency_ms": 100.0 if model == "model-b" else 250.0,
        "fallback_count": fallback,
        "metadata": {
            "actual_provider": provider, "actual_model": model,
            "task_type": task, "model_calls": 1,
            "model_attribution": attribution,
        },
    }


def pick(records, *, baseline="model-a", tenant=TENANT, user=USER, task="research",
         min_samples=8):
    signals = derive_model_signals(
        records, tenant_id=tenant, user_id=user, task_type=task, now=NOW,
    )
    return choose_operationally_learned_model(
        signals, tenant_id=tenant, user_id=user, task_type=task,
        provider_id="ollama-local", baseline_model=baseline,
        eligible_models=["model-a", "model-b"],
        min_samples=min_samples, max_failure_rate=0.4,
        min_reliability_gain=0.2,
    )


def test_repeated_observed_failures_steer_auto_selection_to_reliable_model():
    rows = [
        outcome(i, status=("failure" if i < 9 else "success"))
        for i in range(12)
    ] + [outcome(i, model="model-b") for i in range(12)]
    model, reason = pick(rows)
    assert model == "model-b"
    assert reason == "learning_operational_reliability_v1"
    signals = derive_model_signals(
        rows, tenant_id=TENANT, user_id=USER, task_type="research", now=NOW,
    )
    assert signals.version == MODEL_SIGNAL_VERSION
    assert signals.profile("ollama-local", "model-a").completion_rate == 0.25
    assert signals.profile("ollama-local", "model-b").completion_rate == 1.0


def test_cold_start_or_insufficient_samples_preserve_registered_baseline():
    assert pick([])[0] == "model-a"
    assert pick(
        [outcome(i, status="failure") for i in range(6)]
        + [outcome(i, model="model-b") for i in range(6)],
    )[0] == "model-a"


def test_successful_baseline_is_not_replaced_by_latency_alone():
    rows = [outcome(i) for i in range(12)]
    rows += [outcome(i, model="model-b") for i in range(12)]
    assert pick(rows)[0] == "model-a"


def test_wrong_tenant_user_intent_source_fallback_or_expired_are_excluded():
    fresh = outcome(1, status="failure")
    bad = [
        outcome(2, tenant="other"),
        outcome(3, user="other"),
        outcome(4, task="coding"),
        outcome(5, source="user.feedback"),
        outcome(6, fallback=1),
        outcome(7, attribution="unverified"),
        outcome(8, recorded_at=(NOW - timedelta(days=100)).isoformat()),
        outcome(9, recorded_at="not-a-date"),
    ]
    signals = derive_model_signals(
        [fresh, *bad], tenant_id=TENANT, user_id=USER,
        task_type="research", now=NOW,
    )
    assert signals.profile("ollama-local", "model-a").samples == 1


def test_no_duplicate_outcome_can_train_twice_or_cross_scope():
    rows = [outcome(1), outcome(1)]
    signals = derive_model_signals(
        rows, tenant_id=TENANT, user_id=USER,
        task_type="research", now=NOW,
    )
    assert signals.profile("ollama-local", "model-a").samples == 1
    other = ScopedModelSignals(
        "other-tenant", USER, "research", MODEL_SIGNAL_VERSION,
        "ready", signals.profiles,
    )
    result = choose_operationally_learned_model(
        other, tenant_id=TENANT, user_id=USER, task_type="research",
        provider_id="ollama-local", baseline_model="model-a",
        eligible_models=["model-a", "model-b"],
        min_samples=1, max_failure_rate=0.4,
        min_reliability_gain=0.2,
    )
    assert result == ("model-a", "baseline_scope_mismatch")


def test_unauthorized_baseline_cannot_be_rescued_by_learning():
    with pytest.raises(ValueError, match="authorized"):
        choose_operationally_learned_model(
            None, tenant_id=TENANT, user_id=USER, task_type="research",
            provider_id="ollama-local", baseline_model="ghost",
            eligible_models=["model-a"], min_samples=8,
            max_failure_rate=0.4, min_reliability_gain=0.2,
        )


@pytest.mark.asyncio
async def test_service_reloads_durable_outcomes_on_each_execution(monkeypatch):
    from ai_karen_engine.core.intelligence.ml import model_outcome_signals as signals_module

    stored = [outcome(i, status="failure") for i in range(10)]
    reads = []

    class ExistingOutcomeStore:
        def list_for_tenant(self, tenant, *, limit, user_id, source=None):
            reads.append((tenant, limit, user_id, source))
            assert source == "runtime.execution"
            return [row for row in stored if row["source"] == source]

    monkeypatch.setattr(signals_module, "get_outcome_store", ExistingOutcomeStore)
    monkeypatch.setattr(
        signals_module, "get_learning_settings",
        lambda: SimpleNamespace(
            model_routing_signals_enabled=True,
            model_routing_history_limit=500,
            model_routing_history_days=90,
            model_routing_read_timeout_seconds=1.0,
        ),
    )
    # Real clock is used by the service: use freshly dated records.
    for row in stored:
        row["recorded_at"] = datetime.now(timezone.utc).isoformat()
    service = ModelOutcomeSignalService()
    first = await service.for_execution(
        tenant_id=TENANT, user_id=USER, task_type="research"
    )
    stored.extend([
        outcome(i, model="model-b",
                recorded_at=datetime.now(timezone.utc).isoformat())
        for i in range(12)
    ])
    second = await service.for_execution(
        tenant_id=TENANT, user_id=USER, task_type="research"
    )
    assert first.profile("ollama-local", "model-b") is None
    assert second.profile("ollama-local", "model-b").samples == 12
    assert reads == [
        (TENANT, 500, USER, "runtime.execution"),
        (TENANT, 500, USER, "runtime.execution"),
    ]


@pytest.mark.asyncio
async def test_service_failure_preserves_cold_start_and_exact_scope(monkeypatch):
    from ai_karen_engine.core.intelligence.ml import model_outcome_signals as module

    class Offline:
        def list_for_tenant(self, *args, **kwargs):
            raise RuntimeError("PostgreSQL unavailable")

    monkeypatch.setattr(module, "get_outcome_store", Offline)
    monkeypatch.setattr(
        module, "get_learning_settings",
        lambda: SimpleNamespace(
            model_routing_signals_enabled=True,
            model_routing_history_limit=500,
            model_routing_history_days=90,
            model_routing_read_timeout_seconds=1.0,
        ),
    )
    signals = await ModelOutcomeSignalService().for_execution(
        tenant_id=TENANT, user_id=USER, task_type="research"
    )
    assert signals.status == "unavailable"
    assert signals.profiles == ()
    with pytest.raises(ValueError, match="identity"):
        await ModelOutcomeSignalService().for_execution(
            tenant_id="", user_id=USER, task_type="research"
        )
