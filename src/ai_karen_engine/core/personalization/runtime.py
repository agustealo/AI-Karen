"""
User model runtime for AI-Karen personalization.

The runtime derives personalization state and coordinates canonical persistence.
It does not own a second durable behavior/goal store, call providers, select
models, invoke tools, or choose agents.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from .behavior.aggregator import BehaviorAggregator
from .contracts import (
    BehaviorCandidate,
    BehaviorPattern,
    CurrentUserState,
    PreferenceCandidate,
    PreferenceEvidence,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
    ResolvedPreferences,
    UserGoal,
    UserModelHealth,
    UserModelHealthStatus,
    UserStateSnapshot,
    make_evidence_id,
    make_goal_id,
    make_pattern_id,
    make_preference_id,
)
from .goals.contracts import GoalStore  # compatibility type only; runtime does not instantiate it
from .persistence.repository import PersonalizationRepository
from .preferences.catalog import PreferenceCatalog
from .preferences.drift import DriftDetector
from .preferences.evidence import PreferenceEvidenceStore
from .preferences.lifecycle import PreferenceLifecycle
from .preferences.resolver import PreferenceResolver
from .snapshot import SnapshotBuilder

logger = logging.getLogger(__name__)

try:
    from ai_karen_engine.monitoring.personalization_metrics import get_personalization_metrics

    _personalization_metrics = get_personalization_metrics()
except Exception:
    _personalization_metrics = None


class UserModelRuntime:
    """Derived personalization runtime backed by one repository authority."""

    _BEHAVIOR_PROMOTION_THRESHOLD = 2

    def __init__(self, repository: Optional[PersonalizationRepository] = None) -> None:
        self.repository = repository or PersonalizationRepository()
        # EvidenceStore is a request/runtime accumulator, not a durable database.
        self.evidence_store = PreferenceEvidenceStore()
        self.behavior_aggregator = BehaviorAggregator()
        self.resolver = PreferenceResolver()
        self.drift_detector = DriftDetector()
        self.snapshot_builder: Optional[SnapshotBuilder] = None
        self._healthy = True

    def _get_current_state(self, user_id: str, tenant_id: str) -> CurrentUserState:
        persisted = self.repository.get_current_state(user_id, tenant_id)
        if persisted is not None:
            return CurrentUserState(**persisted)
        return CurrentUserState(user_id=user_id, tenant_id=tenant_id)

    async def get_snapshot(self, user_id: str, tenant_id: str) -> UserStateSnapshot:
        start = time.perf_counter()
        state = self._get_current_state(user_id, tenant_id)
        preferences = await self.repository.async_list_preferences(user_id, tenant_id)
        behavior_records = await self.repository.async_list_behaviors(user_id, tenant_id)
        # Weak one-off observations may be retained for accumulation but are not
        # promoted into the user model until recurrence is established.
        behaviors = [
            pattern
            for pattern in behavior_records
            if pattern.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD
        ]
        goals = await self.repository.async_list_goals(user_id, tenant_id)
        snapshot = SnapshotBuilder(user_id, tenant_id).build(
            state,
            preferences,
            behaviors,
            goals,
        )
        duration = time.perf_counter() - start

        if _personalization_metrics is not None:
            try:
                _personalization_metrics.record_snapshot(
                    status="success",
                    duration_seconds=duration,
                )
            except Exception:
                logger.debug("Unable to record personalization snapshot metric", exc_info=True)

        return snapshot

    async def ingest_evidence(self, evidence: PreferenceEvidence) -> Optional[PreferenceRecord]:
        user_id = str(evidence.metadata.get("user_id", "")).strip()
        tenant_id = str(evidence.metadata.get("tenant_id", "")).strip()
        if not user_id or not tenant_id:
            raise ValueError("preference evidence requires tenant_id and user_id metadata")

        if not self.evidence_store.add(evidence):
            return None

        record = await self.repository.async_get_preference_by_key(
            user_id,
            tenant_id,
            evidence.preference_key,
        )
        if record is None:
            category, _ = PreferenceCatalog.parse_key(evidence.preference_key)
            record = PreferenceRecord(
                preference_id=make_preference_id(),
                user_id=user_id,
                tenant_id=tenant_id,
                key=evidence.preference_key,
                value=evidence.observed_value,
                confidence=evidence.confidence,
                stability=PreferenceStability.SESSION,
                state=PreferenceState.OBSERVED,
                evidence_count=1,
                contradiction_count=0,
                first_observed_at=evidence.observed_at,
                last_observed_at=evidence.observed_at,
                last_confirmed_at=(
                    evidence.observed_at if evidence.polarity == "positive" else None
                ),
                source_types=[evidence.source_type.value],
                scope=self._scope_from_evidence(evidence),
                version=1,
                category=category,
            )
        else:
            record.evidence_count += 1
            record.last_observed_at = evidence.observed_at
            if evidence.polarity == "positive":
                record.last_confirmed_at = evidence.observed_at
            if evidence.source_type.value not in record.source_types:
                record.source_types.append(evidence.source_type.value)
            if evidence.polarity == "negative":
                record, _ = PreferenceLifecycle.contradict(
                    record,
                    evidence.observed_value,
                    evidence.confidence,
                )
                await self.repository.async_save_preference(record)
                self._record_contradiction_metric(evidence.preference_key)
                return record

        new_confidence = self.evidence_store.compute_confidence(
            evidence.preference_key,
            record.confidence,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        record.confidence = new_confidence
        record = PreferenceLifecycle.promote(record, new_confidence)
        await self.repository.async_save_preference(record)
        self._record_preference_metrics(evidence)
        return record

    async def ingest_outcome(self, outcome: Any) -> List[BehaviorPattern]:
        """Accumulate behavior across requests and persist recurrence state.

        The previous implementation bucketed only candidates from a single call,
        which made a once-per-request behavior impossible to learn. We now merge
        each observation into the canonical repository record and expose only
        records that cross the promotion threshold.
        """
        candidates = self.behavior_aggregator.ingest_outcome(outcome)
        promoted: List[BehaviorPattern] = []
        for candidate in candidates:
            pattern = await self._accumulate_behavior(candidate)
            if pattern.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD:
                promoted.append(pattern)
        return promoted

    async def _accumulate_behavior(self, candidate: BehaviorCandidate) -> BehaviorPattern:
        existing_patterns = await self.repository.async_list_behaviors(
            candidate.user_id,
            candidate.tenant_id,
        )
        existing = next(
            (
                pattern
                for pattern in existing_patterns
                if pattern.pattern_type == candidate.pattern_type
                and pattern.context_signature == candidate.context_signature
            ),
            None,
        )
        now = datetime.utcnow()
        if existing is None:
            pattern = BehaviorPattern(
                pattern_id=make_pattern_id(),
                user_id=candidate.user_id,
                tenant_id=candidate.tenant_id,
                pattern_type=candidate.pattern_type,
                context_signature=candidate.context_signature,
                observation_count=1,
                confidence=max(0.0, min(1.0, candidate.confidence)),
                first_seen=now,
                last_seen=now,
                recurrence="observed",
                stability=PreferenceStability.SESSION,
            )
        else:
            existing.observation_count += 1
            existing.last_seen = now
            existing.confidence = min(
                1.0,
                max(existing.confidence, candidate.confidence)
                + (0.1 * min(existing.observation_count - 1, 4)),
            )
            existing.recurrence = (
                "recurring" if existing.observation_count >= 3 else "repeated"
            )
            if existing.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD:
                existing.stability = PreferenceStability.SHORT_TERM
            pattern = existing

        await self.repository.async_save_behavior(pattern)
        return pattern

    async def ingest_preference_candidate(
        self,
        candidate: PreferenceCandidate,
    ) -> Optional[PreferenceRecord]:
        """Convert model/runtime suggestions into evidence, never direct state mutation."""
        evidence = PreferenceEvidence(
            evidence_id=make_evidence_id(),
            preference_key=candidate.key,
            source_type=candidate.source_type,
            source_ref=candidate.source_ref,
            observed_value=candidate.value,
            polarity=candidate.polarity,
            confidence=candidate.confidence,
            observed_at=datetime.utcnow(),
            metadata={
                "user_id": candidate.user_id,
                "tenant_id": candidate.tenant_id,
                "category": candidate.category.value,
            },
        )
        return await self.ingest_evidence(evidence)

    async def update_current_state(
        self,
        user_id: str,
        tenant_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update ephemeral current state without claiming durable LTM storage."""
        state = self._get_current_state(user_id, tenant_id)
        for key, value in updates.items():
            if hasattr(state, key):
                setattr(state, key, value)
        if "expires_at" in updates:
            state.expires_at = updates["expires_at"]
        self.repository.save_current_state(user_id, tenant_id, state.__dict__)

    async def resolve_preferences(
        self,
        user_id: str,
        tenant_id: str,
        task_context: Dict[str, Any],
        scope: Optional[Any] = None,
    ) -> ResolvedPreferences:
        snapshot = await self.get_snapshot(user_id, tenant_id)
        return self.resolver.resolve(snapshot, task_context, scope)

    async def record_goal(
        self,
        user_id: str,
        tenant_id: str,
        description: str,
        scope: Any = None,
        status: str = "active",
    ) -> UserGoal:
        goal = UserGoal(
            goal_id=make_goal_id(),
            user_id=user_id,
            tenant_id=tenant_id,
            description=description,
            scope=scope or "global",
            status=status,
            confidence=0.5,
            evidence=[],
            started_at=datetime.utcnow(),
            last_observed_at=datetime.utcnow(),
        )
        await self.repository.async_save_goal(goal)
        return goal

    async def correct_preference(
        self,
        preference_id: str,
        new_value: Any,
    ) -> Optional[PreferenceRecord]:
        record = await self.repository.async_get_preference(preference_id)
        if record is None:
            return None
        record, _ = PreferenceLifecycle.contradict(
            record,
            new_value,
            record.confidence,
        )
        await self.repository.async_save_preference(record)
        return record

    async def delete_preference(self, preference_id: str) -> bool:
        return await self.repository.async_delete_preference(preference_id)

    async def get_behavior_patterns(
        self,
        user_id: str,
        tenant_id: str,
    ) -> List[BehaviorPattern]:
        patterns = await self.repository.async_list_behaviors(user_id, tenant_id)
        return [
            pattern
            for pattern in patterns
            if pattern.observation_count >= self._BEHAVIOR_PROMOTION_THRESHOLD
        ]

    async def health(self) -> UserModelHealthStatus:
        repo_health = await self.repository.health_check()
        return UserModelHealthStatus(
            repository=repo_health.repository,
            memory_integration=repo_health.memory_integration,
            queue=repo_health.queue,
            snapshot_cache=repo_health.snapshot_cache,
            evidence_processor=UserModelHealth.READY,
            overall=repo_health.overall,
        )

    @staticmethod
    def _scope_from_evidence(evidence: PreferenceEvidence) -> PreferenceScope:
        metadata = evidence.metadata
        if metadata.get("session_id"):
            return PreferenceScope.SESSION
        if metadata.get("conversation_id"):
            return PreferenceScope.CONVERSATION
        if metadata.get("task_id"):
            return PreferenceScope.TASK
        if metadata.get("domain"):
            return PreferenceScope.DOMAIN
        # Explicit user statements without a narrower context are the only
        # evidence eligible to begin at global scope. Other weak observations
        # remain session-scoped until lifecycle promotion establishes durability.
        source_name = evidence.source_type.value
        if "explicit" in source_name:
            return PreferenceScope.GLOBAL
        return PreferenceScope.SESSION

    @staticmethod
    def _record_contradiction_metric(preference_key: str) -> None:
        if _personalization_metrics is None:
            return
        try:
            category, _ = PreferenceCatalog.parse_key(preference_key)
            _personalization_metrics.record_contradiction(preference_category=category)
        except Exception:
            logger.debug("Unable to record personalization contradiction metric", exc_info=True)

    @staticmethod
    def _record_preference_metrics(evidence: PreferenceEvidence) -> None:
        if _personalization_metrics is None:
            return
        try:
            category, _ = PreferenceCatalog.parse_key(evidence.preference_key)
            _personalization_metrics.record_evidence(
                preference_category=category,
                source_type=evidence.source_type.value,
            )
            _personalization_metrics.record_update(
                preference_category=category,
                status="success",
            )
        except Exception:
            logger.debug("Unable to record personalization update metric", exc_info=True)


__all__ = ["UserModelRuntime"]
