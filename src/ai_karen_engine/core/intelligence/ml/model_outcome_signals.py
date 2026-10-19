"""Read-only, scoped operational model learning from durable runtime outcomes.

This is an Intelligence-owned *projection* of the canonical OutcomeStore,
not a second store, model registry, policy engine or provider router.
Successful generation is NOT independently verified answer quality.
Signals are conservative, bounded, versioned and ignored if insufficient.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from ai_karen_engine.config.learning import get_learning_settings
from ai_karen_engine.core.runtime.outcome.store import get_outcome_store

logger = logging.getLogger(__name__)

MODEL_SIGNAL_VERSION = "model_operational_outcome_v1"


@dataclass(frozen=True, slots=True)
class ModelOperationalProfile:
    provider_id: str
    model_id: str
    samples: int
    completed: int
    average_latency_ms: float

    @property
    def completion_rate(self) -> float:
        return self.completed / self.samples if self.samples else 0.0


@dataclass(frozen=True, slots=True)
class ScopedModelSignals:
    """Trusted in-process evidence snapshot, never a client-provided request."""

    tenant_id: str
    user_id: str
    task_type: str
    version: str
    status: str
    profiles: tuple[ModelOperationalProfile, ...]

    def profile(self, provider_id: str, model_id: str) -> ModelOperationalProfile | None:
        return next(
            (item for item in self.profiles
             if item.provider_id == provider_id and item.model_id == model_id),
            None,
        )


def _fresh_record(value: Any, *, now: datetime, days: int) -> bool:
    if isinstance(value, datetime):
        observed = value
    elif isinstance(value, str):
        try:
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        return False
    if observed.tzinfo is None:
        return False
    utc = observed.astimezone(timezone.utc)
    return now - timedelta(days=days) <= utc <= now


def derive_model_signals(
    records: list[dict[str, Any]], *,
    tenant_id: str, user_id: str, task_type: str,
    now: datetime | None = None, history_days: int = 90,
) -> ScopedModelSignals:
    """Allowlist observed runtime facts; reject feedback and cross-scope rows.

    No outcome claims that a response is *correct*. The score is operational
    completion only. Bounded historical samples cannot grant permissions.
    """
    if not tenant_id or not user_id or not task_type:
        raise ValueError("Model learning requires exact tenant, user and task scope")
    now = now or datetime.now(timezone.utc)
    stats: dict[tuple[str, str], list[float]] = {}
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        if row.get("source") != "runtime.execution":
            continue
        if row.get("tenant_id") != tenant_id or row.get("user_id") != user_id:
            continue
        outcome_id = row.get("outcome_id")
        if not isinstance(outcome_id, str) or not outcome_id or outcome_id in seen:
            continue
        seen.add(outcome_id)
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if metadata.get("task_type") != task_type or metadata.get("model_attribution") != "single_provider_model":
            continue
        provider_id = metadata.get("actual_provider")
        model_id = metadata.get("actual_model")
        if not all(isinstance(x, str) and 0 < len(x) <= 256 for x in (provider_id, model_id)):
            continue
        if row.get("status") not in {"success", "failure"}:
            continue
        if not _fresh_record(row.get("recorded_at"), now=now, days=history_days):
            continue
        if row.get("fallback_count") != 0:
            continue
        calls = metadata.get("model_calls")
        if isinstance(calls, bool) or not isinstance(calls, int) or calls <= 0:
            continue
        latency = row.get("latency_ms")
        if isinstance(latency, bool) or not isinstance(latency, (int, float)):
            continue
        if not math.isfinite(latency) or not 0 < latency <= 600_000:
            continue
        complete = row["status"] == "success" and row.get("response_completed") is True
        data = stats.setdefault((provider_id, model_id), [0, 0, 0.0])
        data[0] += 1
        data[1] += int(complete)
        data[2] += float(latency)
    profiles = tuple(
        ModelOperationalProfile(
            provider_id=provider, model_id=model,
            samples=int(values[0]), completed=int(values[1]),
            average_latency_ms=values[2] / values[0],
        )
        for (provider, model), values in sorted(stats.items())
    )
    return ScopedModelSignals(
        tenant_id=tenant_id, user_id=user_id, task_type=task_type,
        version=MODEL_SIGNAL_VERSION,
        status="ready" if profiles else "cold_start",
        profiles=profiles,
    )


class ModelOutcomeSignalService:
    """Asynchronously reads existing durable outcome evidence, fail-open to baseline."""

    async def for_execution(
        self, *, tenant_id: str, user_id: str, task_type: str,
    ) -> ScopedModelSignals:
        if not tenant_id or not user_id or not task_type:
            raise ValueError("Model learning requires authenticated execution identity")
        settings = get_learning_settings()
        if not settings.model_routing_signals_enabled:
            return ScopedModelSignals(
                tenant_id, user_id, task_type, MODEL_SIGNAL_VERSION, "disabled", ()
            )
        try:
            store = get_outcome_store()
            records = await asyncio.wait_for(
                asyncio.to_thread(
                    store.list_for_tenant,
                    tenant_id,
                    limit=settings.model_routing_history_limit,
                    user_id=user_id,
                ),
                timeout=settings.model_routing_read_timeout_seconds,
            )
            return derive_model_signals(
                records, tenant_id=tenant_id, user_id=user_id,
                task_type=task_type, history_days=settings.model_routing_history_days,
            )
        except Exception as exc:
            # Learning is advisory. Preserve direct execution and record truthful
            # degradation. Never silently switch tenant scope or use test data.
            logger.warning(
                "intelligence.model_outcome_signals_unavailable",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )
            return ScopedModelSignals(
                tenant_id, user_id, task_type,
                MODEL_SIGNAL_VERSION, "unavailable", (),
            )


def choose_operationally_learned_model(
    signals: ScopedModelSignals | None, *,
    tenant_id: str, user_id: str, task_type: str,
    provider_id: str, baseline_model: str, eligible_models: list[str],
    min_samples: int, max_failure_rate: float,
    min_reliability_gain: float,
) -> tuple[str, str]:
    """Conservative reliability veto, never a claim of answer correctness.

    Both models require adequate *observed* evidence. Switch only if
    baseline is demonstrably unreliable and candidate materially better.
    Explicit user/provider/RuntimePolicy choices must be checked upstream.
    """
    if baseline_model not in eligible_models:
        raise ValueError("Baseline must be an authorized, registered model")
    if signals is None or signals.status != "ready":
        return baseline_model, "baseline_no_learning"
    if (signals.tenant_id != tenant_id or signals.user_id != user_id
            or signals.task_type != task_type
            or signals.version != MODEL_SIGNAL_VERSION):
        return baseline_model, "baseline_scope_mismatch"
    baseline = signals.profile(provider_id, baseline_model)
    if baseline is None or baseline.samples < min_samples:
        return baseline_model, "baseline_insufficient_evidence"
    if 1 - baseline.completion_rate < max_failure_rate:
        return baseline_model, "baseline_reliable"
    candidates = [
        p for p in signals.profiles
        if p.provider_id == provider_id and p.model_id in eligible_models
        and p.model_id != baseline_model
        and p.samples >= min_samples
        and p.completion_rate >= baseline.completion_rate + min_reliability_gain
    ]
    if not candidates:
        return baseline_model, "baseline_no_verified_alternative"
    winner = sorted(
        candidates, key=lambda p: (-p.completion_rate, p.average_latency_ms, p.model_id)
    )[0]
    return winner.model_id, "learning_operational_reliability_v1"


_MODEL_OUTCOME_SIGNALS = ModelOutcomeSignalService()


def get_model_outcome_signal_service() -> ModelOutcomeSignalService:
    return _MODEL_OUTCOME_SIGNALS
