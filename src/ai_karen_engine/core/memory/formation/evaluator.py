"""Canonical memory formation evaluation authority.

Signal extraction and worthiness admission happen exactly once here. Durable
formation and non-persisting shadow execution consume the same typed result so
feature flags can change mutation behavior without changing memory semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.memory.scoring import MemoryWorthinessScorer
from ai_karen_engine.core.memory.signals import MemorySignal, get_signal_pipeline


@dataclass(frozen=True, slots=True)
class AdmittedMemorySignal:
    """A signal admitted for memory formation with its normalized score."""

    signal: MemorySignal
    score: float


@dataclass(frozen=True, slots=True)
class MemoryFormationEvaluation:
    """Side-effect-free result of memory signal extraction and admission."""

    status: str
    normalized_text: str
    tenant_id: str
    user_id: str
    extracted_count: int
    admitted: tuple[AdmittedMemorySignal, ...]
    errors: tuple[str, ...]
    processing_time_ms: float | int | None
    reason: str | None = None

    @property
    def admitted_count(self) -> int:
        return len(self.admitted)

    def summary(self, *, status: str | None = None, persisted: int = 0) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status or self.status,
            "extracted": self.extracted_count,
            "admitted": self.admitted_count,
            "persisted": persisted,
            "errors": list(self.errors),
            "processing_time_ms": self.processing_time_ms,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


class MemoryFormationEvaluator:
    """Single authority for extraction and worthiness-based admission."""

    def __init__(
        self,
        *,
        signal_pipeline: Any | None = None,
        worthiness_scorer: MemoryWorthinessScorer | None = None,
    ) -> None:
        self._signal_pipeline = signal_pipeline or get_signal_pipeline()
        self._worthiness_scorer = worthiness_scorer or MemoryWorthinessScorer()

    async def evaluate(
        self,
        *,
        text: str,
        tenant_id: str,
        user_id: str,
    ) -> MemoryFormationEvaluation:
        normalized = str(text or "").strip()
        resolved_tenant = str(tenant_id or "").strip()
        resolved_user = str(user_id or "").strip()

        if not normalized:
            return MemoryFormationEvaluation(
                status="noop",
                normalized_text="",
                tenant_id=resolved_tenant,
                user_id=resolved_user,
                extracted_count=0,
                admitted=(),
                errors=(),
                processing_time_ms=0,
                reason="empty_interaction",
            )
        if not resolved_tenant or not resolved_user:
            return MemoryFormationEvaluation(
                status="rejected",
                normalized_text=normalized,
                tenant_id=resolved_tenant,
                user_id=resolved_user,
                extracted_count=0,
                admitted=(),
                errors=(),
                processing_time_ms=0,
                reason="missing_tenant_or_user_scope",
            )

        extraction = await self._signal_pipeline.process_text(
            text=normalized,
            tenant_id=resolved_tenant,
            user_id=resolved_user,
        )
        admitted: list[AdmittedMemorySignal] = []
        for signal in extraction.signals:
            worthiness = await self._worthiness_scorer.evaluate(
                signal.text,
                signal.signal_type,
            )
            if not worthiness.get("is_worthy"):
                continue
            admitted.append(
                AdmittedMemorySignal(
                    signal=signal,
                    score=max(0.0, min(1.0, float(worthiness.get("score") or 0.0))),
                )
            )

        status = "success" if extraction.status == "success" else "degraded"
        if extraction.status == "failed":
            status = "failed"
        return MemoryFormationEvaluation(
            status=status,
            normalized_text=normalized,
            tenant_id=resolved_tenant,
            user_id=resolved_user,
            extracted_count=len(extraction.signals),
            admitted=tuple(admitted),
            errors=tuple(str(error) for error in extraction.errors),
            processing_time_ms=extraction.processing_time_ms,
        )


__all__ = [
    "AdmittedMemorySignal",
    "MemoryFormationEvaluation",
    "MemoryFormationEvaluator",
]
