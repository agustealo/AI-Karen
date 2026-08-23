"""
User model runtime for AI-Karen personalization.

Single runtime authority for personalization state management.
Does NOT call providers, select models, invoke tools, or choose agents.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .contracts import (
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
    make_contradiction_id,
    make_evidence_id,
    make_goal_id,
    make_pattern_id,
    make_preference_id,
)
from .preferences.catalog import PreferenceCatalog
from .preferences.evidence import PreferenceEvidenceStore
from .preferences.lifecycle import PreferenceLifecycle
from .preferences.resolver import PreferenceResolver
from .preferences.drift import DriftDetector
from .behavior.aggregator import BehaviorAggregator
from .behavior.contracts import BehaviorPatternStore
from .goals.contracts import GoalStore
from .snapshot import SnapshotBuilder
from .persistence.repository import PersonalizationRepository

logger = logging.getLogger(__name__)

try:
    from ai_karen_engine.monitoring.personalization_metrics import get_personalization_metrics
    _personalization_metrics = get_personalization_metrics()
except Exception:
    _personalization_metrics = None


class UserModelRuntime:
    """Single runtime authority for KAREN personalization."""

    def __init__(self, repository: Optional[PersonalizationRepository] = None):
        self.repository = repository or PersonalizationRepository()
        self.evidence_store = PreferenceEvidenceStore()
        self.behavior_store = BehaviorPatternStore()
        self.goal_store = GoalStore()
        self.behavior_aggregator = BehaviorAggregator(self.behavior_store)
        self.resolver = PreferenceResolver()
        self.drift_detector = DriftDetector()
        self.snapshot_builder: Optional[SnapshotBuilder] = None
        self._current_state: Dict[str, CurrentUserState] = {}
        self._healthy = True

    def _state_key(self, user_id: str, tenant_id: str) -> str:
        return f"{tenant_id}:{user_id}"

    def _get_current_state(self, user_id: str, tenant_id: str) -> CurrentUserState:
        key = self._state_key(user_id, tenant_id)
        if key not in self._current_state:
            self._current_state[key] = CurrentUserState(
                user_id=user_id,
                tenant_id=tenant_id,
            )
        return self._current_state[key]

    async def get_snapshot(self, user_id: str, tenant_id: str) -> UserStateSnapshot:
        start = time.perf_counter()
        state = self._get_current_state(user_id, tenant_id)
        prefs = self.repository.list_preferences(user_id, tenant_id)
        behaviors = self.behavior_store.list_for_user(user_id, tenant_id)
        goals = self.goal_store.list_for_user(user_id, tenant_id)
        builder = SnapshotBuilder(user_id, tenant_id)
        snapshot = builder.build(state, prefs, behaviors, goals)
        duration = time.perf_counter() - start

        if _personalization_metrics is not None:
            try:
                _personalization_metrics.record_snapshot(
                    status="success",
                    duration_seconds=duration,
                )
            except Exception:
                pass

        return snapshot

    async def ingest_evidence(self, evidence: PreferenceEvidence) -> Optional[PreferenceRecord]:
        if not self.evidence_store.add(evidence):
            return None

        record = self.repository.get_preference_by_key(
            evidence.metadata.get("user_id", ""), evidence.metadata.get("tenant_id", ""), evidence.preference_key
        )
        if not record:
            user_id = evidence.metadata.get("user_id", "")
            tenant_id = evidence.metadata.get("tenant_id", "")
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
                last_confirmed_at=evidence.observed_at if evidence.polarity == "positive" else None,
                source_types=[evidence.source_type.value],
                scope=PreferenceScope.SESSION,
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
                record, contradiction = PreferenceLifecycle.contradict(record, evidence.observed_value, evidence.confidence)
                self.repository.save_preference(record)
                if _personalization_metrics is not None:
                    category, _ = PreferenceCatalog.parse_key(evidence.preference_key)
                    _personalization_metrics.record_contradiction(
                        preference_category=category,
                    )
                return record

        new_confidence = self.evidence_store.compute_confidence(evidence.preference_key, record.confidence)
        record.confidence = new_confidence
        record = PreferenceLifecycle.promote(record, new_confidence)
        self.repository.save_preference(record)

        if _personalization_metrics is not None:
            category, _ = PreferenceCatalog.parse_key(evidence.preference_key)
            _personalization_metrics.record_evidence(
                preference_category=category,
                source_type=evidence.source_type.value,
            )
            _personalization_metrics.record_update(
                preference_category=category,
                status="success",
            )

        return record

    async def ingest_outcome(self, outcome: Any) -> List[BehaviorPattern]:
        candidates = self.behavior_aggregator.ingest_outcome(outcome)
        return self.behavior_aggregator.promote_candidates(candidates)

    async def ingest_preference_candidate(self, candidate: PreferenceCandidate) -> Optional[PreferenceRecord]:
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

    async def update_current_state(self, user_id: str, tenant_id: str, updates: Dict[str, Any]) -> None:
        state = self._get_current_state(user_id, tenant_id)
        for k, v in updates.items():
            if hasattr(state, k):
                setattr(state, k, v)
        state.expires_at = updates.get("expires_at")
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
        self.goal_store.upsert(goal)
        return goal

    async def correct_preference(self, preference_id: str, new_value: Any) -> Optional[PreferenceRecord]:
        record = self.repository.get_preference(preference_id)
        if not record:
            return None
        record, contradiction = PreferenceLifecycle.contradict(record, new_value, record.confidence)
        self.repository.save_preference(record)
        return record

    async def delete_preference(self, preference_id: str) -> bool:
        return self.repository.delete_preference(preference_id)

    async def get_behavior_patterns(self, user_id: str, tenant_id: str) -> List[BehaviorPattern]:
        return self.behavior_store.list_for_user(user_id, tenant_id)

    async def health(self) -> UserModelHealthStatus:
        repo_health = await self.repository.health_check()
        return UserModelHealthStatus(
            repository=repo_health.repository,
            memory_integration=UserModelHealth.READY,
            queue=UserModelHealth.READY,
            snapshot_cache=UserModelHealth.READY,
            evidence_processor=UserModelHealth.READY,
            overall=repo_health.overall,
        )


__all__ = ["UserModelRuntime"]
