"""
Unit tests for AI-Karen personalization behavior.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict

import pytest

from ai_karen_engine.core.personalization.behavior.aggregator import BehaviorAggregator
from ai_karen_engine.core.personalization.behavior.contracts import BehaviorPatternStore
from ai_karen_engine.core.personalization.contracts import BehaviorPattern, PreferenceStability


class DummyOutcome:
    def __init__(self, tool_success=None, fallback_count=0, response_completed=None, metadata=None, user_id="u1", tenant_id="t1"):
        self.execution_outcome = type("E", (), {
            "tool_success": tool_success,
            "fallback_count": fallback_count,
            "response_completed": response_completed,
        })()
        self.metadata = metadata or {}
        self.user_id = user_id
        self.tenant_id = tenant_id


class TestBehaviorAggregator:
    def test_tool_success_creates_candidate(self):
        agg = BehaviorAggregator()
        outcome = DummyOutcome(tool_success=True)
        candidates = agg.ingest_outcome(outcome)
        assert len(candidates) == 1
        assert candidates[0].pattern_type == "tool_success"

    def test_fallback_creates_candidate(self):
        agg = BehaviorAggregator()
        outcome = DummyOutcome(fallback_count=2)
        candidates = agg.ingest_outcome(outcome)
        assert any(c.pattern_type == "fallback_used" for c in candidates)

    def test_promote_candidates_requires_multiple(self):
        agg = BehaviorAggregator()
        c1 = agg._make_candidate("u1", "t1", "audit_workflow", {}, "audit", 0.5)
        c2 = agg._make_candidate("u1", "t1", "audit_workflow", {}, "audit", 0.5)
        patterns = agg.promote_candidates([c1, c2])
        assert len(patterns) == 1
        assert patterns[0].observation_count == 2


class TestBehaviorPatternStore:
    def test_upsert_and_list(self):
        store = BehaviorPatternStore()
        pattern = BehaviorPattern(
            pattern_id="p1",
            user_id="u1",
            tenant_id="t1",
            pattern_type="audit",
            context_signature="ctx",
            observation_count=1,
            confidence=0.5,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            recurrence="observed",
            stability=PreferenceStability.SHORT_TERM,
        )
        store.upsert(pattern)
        assert store.get("p1") is pattern
        assert len(store.list_for_user("u1", "t1")) == 1


__all__ = ["TestBehaviorAggregator", "TestBehaviorPatternStore"]
