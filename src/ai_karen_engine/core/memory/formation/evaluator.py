"""Canonical memory formation evaluation authority.

Signal extraction and worthiness admission happen exactly once here. Durable
formation and non-persisting shadow execution consume the same typed result so
feature flags can change mutation behavior without changing memory semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_karen_engine.core.memory.guards import (
    MemoryConsentPolicy,
    MemoryGuards,
    MemoryOrigin,
    MemoryRetentionScope,
    MemorySensitivity,
    MemoryTrustClass,
    MemoryTrustProvenance,
)
from ai_karen_engine.core.memory.scoring import MemoryWorthinessScorer
from ai_karen_engine.core.memory.signals import MemorySignal, get_signal_pipeline


class PrivacyClassifier(Protocol):
    """Minimal privacy-classification contract consumed by formation."""

    def extract_safe_metadata(self, value: str) -> dict[str, Any]: ...


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
    """Single authority for extraction, privacy gating and worthiness admission."""

    def __init__(
        self,
        *,
        signal_pipeline: Any | None = None,
        worthiness_scorer: MemoryWorthinessScorer | None = None,
        privacy_classifier: PrivacyClassifier | None = None,
    ) -> None:
        self._signal_pipeline = signal_pipeline or get_signal_pipeline()
        self._worthiness_scorer = worthiness_scorer or MemoryWorthinessScorer()
        self._privacy_classifier = privacy_classifier or self._default_privacy_classifier()

    @staticmethod
    def _default_privacy_classifier() -> PrivacyClassifier:
        """Resolve the existing privacy authority without duplicating its rules.

        PIIDetector currently lives with the privacy-compliance application
        service. Formation consumes only its narrow, deterministic classifier
        contract. Keeping the import lazy avoids import-time database/service
        initialization while preserving one PII rule owner until that pure
        classifier is moved to the platform security package.
        """
        from ai_karen_engine.services.privacy_compliance import PIIDetector

        return PIIDetector()

    @staticmethod
    def _consent_policy_for_signal(
        signal: MemorySignal,
        *,
        privacy_metadata: dict[str, Any],
    ) -> MemoryConsentPolicy:
        """Map classified PII to memory retention without weakening privacy globally.

        Explicit user identity is allowed only for name-only PII. More sensitive
        PII remains prohibited in automatic formation and requires a separate,
        explicit product consent path before durable storage is ever considered.
        """

        pii_types = {
            str(item).casefold()
            for item in list(privacy_metadata.get("pii_types") or [])
            if str(item).strip()
        }
        explicit = bool(signal.metadata.get("explicit_user_statement"))
        is_identity = signal.signal_type == "identity_fact"

        if pii_types:
            profile_safe_name = pii_types.issubset({"name"}) and explicit and is_identity
            sensitivity = (
                MemorySensitivity.CONFIDENTIAL
                if profile_safe_name
                else MemorySensitivity.PROHIBITED
            )
        else:
            sensitivity = (
                MemorySensitivity.CONFIDENTIAL
                if explicit and is_identity
                else MemorySensitivity.INTERNAL
            )

        retention = (
            MemoryRetentionScope.USER_PROFILE
            if signal.signal_type
            in {
                "identity_fact",
                "preference",
                "goal",
                "goal_transition",
                "prospective_event",
                "prospective_transition",
                "open_loop",
                "open_loop_transition",
            }
            else MemoryRetentionScope.CONVERSATION
        )

        return MemoryConsentPolicy(
            sensitivity=sensitivity,
            explicit_user_intent=explicit,
            retention_scope=retention,
            purpose="personalization_and_continuity",
            deletion_rights="user_controlled",
            require_explicit_consent=False,
            propagation_allowed=sensitivity is not MemorySensitivity.PROHIBITED,
        )

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

        privacy_metadata = self._privacy_classifier.extract_safe_metadata(normalized)
        contains_pii = bool(privacy_metadata.get("contains_pii", False))

        admitted: list[AdmittedMemorySignal] = []
        for signal in extraction.signals:
            worthiness = await self._worthiness_scorer.evaluate(
                signal.text,
                signal.signal_type,
            )
            if not worthiness.get("is_worthy"):
                continue

            score = max(0.0, min(1.0, float(worthiness.get("score") or 0.0)))
            consent_policy = self._consent_policy_for_signal(
                signal,
                privacy_metadata=privacy_metadata,
            )
            guards = MemoryGuards(
                trust_provenance=MemoryTrustProvenance(
                    origin=MemoryOrigin.USER_INPUT,
                    trust_class=MemoryTrustClass.EXPLICIT_USER,
                    verification_confidence=1.0,
                    source_ref="chat_interaction",
                ),
                consent_policy=consent_policy,
                strict_mode=True,
                metadata={"privacy": privacy_metadata},
            )
            allowed, _reason = guards.can_create_memory(score, signal.text)
            if not allowed:
                continue

            signal.metadata.setdefault(
                "sensitivity_class",
                consent_policy.sensitivity.value,
            )
            signal.metadata.setdefault(
                "retention_scope",
                consent_policy.retention_scope.value,
            )
            admitted.append(
                AdmittedMemorySignal(
                    signal=signal,
                    score=score,
                )
            )

        status = "success" if extraction.status == "success" else "degraded"
        if extraction.status == "failed":
            status = "failed"
        reason = "privacy_sensitive_interaction" if contains_pii and not admitted else None
        return MemoryFormationEvaluation(
            status=("rejected" if reason else status),
            normalized_text=normalized,
            tenant_id=resolved_tenant,
            user_id=resolved_user,
            extracted_count=len(extraction.signals),
            admitted=tuple(admitted),
            errors=tuple(str(error) for error in extraction.errors),
            processing_time_ms=extraction.processing_time_ms,
            reason=reason,
        )


__all__ = [
    "AdmittedMemorySignal",
    "MemoryFormationEvaluation",
    "MemoryFormationEvaluator",
    "PrivacyClassifier",
]
