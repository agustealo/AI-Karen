"""Governed durability adapter for Intelligence online-learning predictor evidence.

Shares the existing tenant-RLS OutcomeStore. This does not authorize training,
change active MLModelRegistry models, or promote candidate models. The
process-local MLOutcomeCollector stays a test/shadow observation cache; all
production-quality comparisons must rebuild from durable verified evidence.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.online_learning import (
    AdaptiveLayer, MLOutcomeRecord,
)
from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStore, get_outcome_store,
)

_ML_SOURCE = "intelligence.ml"
_ML_SCHEMA = "ml_predictor_evidence_v1"
_ALLOWED_LABEL_SOURCES = frozenset({"human_review", "heldout_evaluation"})


class GovernedMLLearningEvidence:
    """One principal-scoped, append-only ML predictor evaluation adapter.

    A legitimate training/evaluation caller must supply the verifiable label
    reference. The label quality must be evaluated separately before this
    call. Only a redacted, numeric evidence summary is persisted.
    """

    def __init__(
        self, *, tenant_id: str, user_id: str,
        store: OutcomeStore | None = None,
    ) -> None:
        if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id == "default":
            raise ValueError("ML learning requires an authenticated tenant")
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("ML learning requires an authenticated user")
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.store = store or get_outcome_store()

    @staticmethod
    def _finite_fraction(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        result = float(value)
        if not math.isfinite(result) or not 0 <= result <= 1:
            raise ValueError(f"{name} must lie between 0 and 1")
        return result

    @classmethod
    def _validated_metrics(cls, result: MLOutcomeRecord) -> dict[str, Any]:
        if not isinstance(result, MLOutcomeRecord):
            raise TypeError("Expected a typed ML predictor outcome")
        if not isinstance(result.task, PredictionTask):
            raise ValueError("Unknown ML predictor task")
        if not all(
            isinstance(value, str) and 0 < len(value) <= 256
            for value in (
                result.outcome_id, result.model_id,
                result.model_version, result.feature_version,
            )
        ):
            raise ValueError("ML predictor IDs and versions must be non-empty")
        if not isinstance(result.correct, bool):
            raise ValueError("Ground-truth correctness must be explicitly evaluated")
        latency = result.latency_ms
        if (
            isinstance(latency, bool)
            or not isinstance(latency, (int, float))
            or not math.isfinite(latency)
            or not 0 <= latency <= 600_000
        ):
            raise ValueError("Invalid predictor inference latency")
        return {
            "model_id": result.model_id,
            "model_version": result.model_version,
            "feature_version": result.feature_version,
            "task": result.task.value,
            "correct": result.correct,
            "raw_probability": cls._finite_fraction(
                result.raw_probability, "raw_probability"
            ),
            "calibrated_probability": cls._finite_fraction(
                result.calibrated_probability, "calibrated_probability"
            ),
            "confidence": cls._finite_fraction(result.confidence, "confidence"),
            "calibration_error": cls._finite_fraction(
                result.calibration_error, "calibration_error"
            ),
            "latency_ms": float(latency),
            "fallback_used": bool(result.fallback_used),
        }

    async def record_verified(
        self, result: MLOutcomeRecord, *,
        label_source: str, label_evidence_ref: str,
        trajectory_id: str | None = None,
    ) -> dict[str, Any]:
        """Append and await a unique durable receipt before reporting success.

        Never store raw labels, training examples, prompts, model output or
        arbitrary metadata from MLOutcomeRecord.
        """
        if label_source not in _ALLOWED_LABEL_SOURCES:
            raise ValueError("Only governed human review or held-out evaluation is eligible")
        if (
            not isinstance(label_evidence_ref, str)
            or not 1 <= len(label_evidence_ref) <= 256
            or not label_evidence_ref.isascii()
            or not all(
                ch.isalnum() or ch in "-._:/" for ch in label_evidence_ref
            )
        ):
            raise ValueError("Verified ML outcome requires an evaluation evidence reference")
        data = self._validated_metrics(result)
        recorded_at = datetime.now(timezone.utc)
        payload = {
            "outcome_id": result.outcome_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "trajectory_id": trajectory_id,
            "source": _ML_SOURCE,
            "recorded_at": recorded_at.isoformat(),
            "metadata": {
                "schema_version": _ML_SCHEMA,
                "label_source": label_source,
                "label_evidence_ref": label_evidence_ref,
                **data,
            },
        }
        await self.store.save_unique_outcome_async(payload)
        # An explicit successful strict insert is the only acknowledgement.
        return {
            "outcome_id": result.outcome_id,
            "source": _ML_SOURCE,
            "stored": True,
            "evidence_version": _ML_SCHEMA,
        }

    async def load_verified(
        self, *, limit: int = 500,
        task: PredictionTask | None = None,
    ) -> list[MLOutcomeRecord]:
        """Rehydrate numeric verified evidence across worker restarts.

        A scoped list query is required. No cross-tenant/anonymous fallback.
        This never trusts process-local cache or exposes stored raw labels.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("ML outcome read limit must be 1-1000")
        records = await asyncio.to_thread(
            self.store.list_for_tenant,
            self.tenant_id, limit=limit, user_id=self.user_id,
        )
        restored: list[MLOutcomeRecord] = []
        seen: set[str] = set()
        for row in records:
            if not isinstance(row, dict):
                continue
            if (
                row.get("source") != _ML_SOURCE
                or row.get("tenant_id") != self.tenant_id
                or row.get("user_id") != self.user_id
            ):
                continue
            identity = row.get("outcome_id")
            metadata = row.get("metadata")
            if (
                not isinstance(identity, str)
                or identity in seen
                or not isinstance(metadata, dict)
                or metadata.get("schema_version") != _ML_SCHEMA
                or metadata.get("label_source") not in _ALLOWED_LABEL_SOURCES
                or not metadata.get("label_evidence_ref")
                or not isinstance(metadata.get("correct"), bool)
            ):
                continue
            try:
                prediction_task = PredictionTask(metadata["task"])
                if task is not None and prediction_task != task:
                    continue
                stamp = row.get("recorded_at")
                if isinstance(stamp, str):
                    verified_at = datetime.fromisoformat(
                        stamp.replace("Z", "+00:00")
                    )
                elif isinstance(stamp, datetime):
                    verified_at = stamp
                else:
                    continue
                if verified_at.tzinfo is None:
                    continue
                item = MLOutcomeRecord(
                    outcome_id=identity,
                    task=prediction_task,
                    model_id=metadata["model_id"],
                    model_version=metadata["model_version"],
                    feature_version=metadata["feature_version"],
                    predicted_label="",
                    expected_label="",  # Raw labels never persisted.
                    correct=metadata["correct"],
                    raw_probability=float(metadata["raw_probability"]),
                    calibrated_probability=float(metadata["calibrated_probability"]),
                    confidence=float(metadata["confidence"]),
                    latency_ms=float(metadata["latency_ms"]),
                    fallback_used=metadata["fallback_used"] is True,
                    calibration_error=float(metadata["calibration_error"]),
                    # OnlineLearning's historical profile-decay contract
                    # uses Unix seconds, even though OutcomeStore persists ISO.
                    timestamp=str(verified_at.timestamp()),
                )
                self._validated_metrics(item)
            except (ValueError, KeyError, TypeError):
                continue
            seen.add(identity)
            restored.append(item)
        return restored

    async def build_adaptive_layer(
        self, *, limit: int = 500, task: PredictionTask | None = None,
    ) -> AdaptiveLayer:
        """Recompute evidence profiles, don't trust a stale process cache.

        Returned thresholds and promotion hints remain shadow/advisory; the
        existing MLModelRegistry governance alone may promote a predictor.
        """
        learned = AdaptiveLayer()
        for observation in await self.load_verified(limit=limit, task=task):
            learned.record_outcome(observation)
        return learned
