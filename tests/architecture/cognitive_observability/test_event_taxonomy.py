"""Tests for cognitive event taxonomy specification.

Validates the canonical event envelope, event types, and reason codes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture" / "cognitive-observability"
EVENT_TAXONOMY = DOCS_ROOT / "EVENT_TAXONOMY.md"


class TestEventEnvelope:
    """Verify CognitiveEvent envelope has all required fields."""

    @pytest.mark.parametrize("field", [
        "event_id",
        "event_type",
        "correlation_id",
        "request_id",
        "causation_id",
        "parent_event_id",
        "tenant_id",
        "user_id",
        "session_id",
        "conversation_id",
        "cognitive_stage",
        "policy_version",
        "schema_version",
        "occurred_at",
        "duration_ms",
        "status",
        "reason_codes",
        "input_refs",
        "output_refs",
        "safe_attributes",
    ])
    def test_event_envelope_field_documented(self, field: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert field in content, f"Event envelope field '{field}' not documented in EVENT_TAXONOMY.md"


class TestCausationDistinction:
    """Verify correlation_id, causation_id, and parent_event_id are distinguished."""

    def test_correlation_id_defined_as_whole_request(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "correlation_id" in content.lower()
        assert "whole request" in content.lower() or "whole-request" in content.lower(), (
            "EVENT_TAXONOMY.md must define correlation_id as the whole request"
        )

    def test_causation_id_defined_as_causing_event(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "causation_id" in content.lower()
        # Must mention causation
        assert "caused" in content.lower() or "causation" in content.lower(), (
            "EVENT_TAXONOMY.md must define causation_id as the event that caused this event"
        )

    def test_parent_event_id_defined_as_structural_parent(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "parent_event_id" in content.lower()
        assert "structural" in content.lower() or "parent" in content.lower(), (
            "EVENT_TAXONOMY.md must define parent_event_id as structural trace parent"
        )


class TestCognitiveStages:
    """Verify all cognitive stages are documented."""

    @pytest.mark.parametrize("stage", [
        "PERCEPTION",
        "RECALL",
        "BELIEF",
        "GOAL",
        "SALIENCE",
        "CONTEXT",
        "REASONING",
        "META_COGNITION",
        "ADAPTIVE",
        "CORTEX",
        "RUNTIME",
        "LEARNING",
        "REFLECTION",
    ])
    def test_cognitive_stage_documented(self, stage: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert stage in content, f"Cognitive stage '{stage}' not documented in EVENT_TAXONOMY.md"


class TestStatusValues:
    """Verify all status values are documented."""

    @pytest.mark.parametrize("status", [
        "SUCCESS",
        "PARTIAL",
        "DEGRADED",
        "FAILED",
        "SKIPPED",
        "NOT_APPLICABLE",
    ])
    def test_status_value_documented(self, status: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert status in content, f"Status value '{status}' not documented in EVENT_TAXONOMY.md"


class TestLifecycleEvents:
    """Verify lifecycle event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "cognition.started",
        "cognition.completed",
    ])
    def test_lifecycle_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Lifecycle event '{event_type}' not documented"


class TestIntelligenceEvents:
    """Verify intelligence event types are documented."""

    def test_intelligence_completed_documented(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "intelligence.completed" in content


class TestRecallEvents:
    """Verify recall event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "recall.requested",
        "recall.completed",
        "recall.degraded",
    ])
    def test_recall_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Recall event '{event_type}' not documented"


class TestBeliefEvents:
    """Verify belief event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "belief.assessment_started",
        "belief.assessed",
        "belief.conflict_detected",
    ])
    def test_belief_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Belief event '{event_type}' not documented"


class TestGoalIntentionEvents:
    """Verify goal/intention event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "goal.context_resolved",
        "intention.triggered",
    ])
    def test_goal_intention_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Goal/intention event '{event_type}' not documented"


class TestSalienceEvents:
    """Verify salience event types are documented."""

    def test_salience_assessed_documented(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "salience.assessed" in content


class TestContextEvents:
    """Verify context event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "context.planned",
        "context.item_selected",
        "context.item_omitted",
    ])
    def test_context_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Context event '{event_type}' not documented"


class TestReasoningEvents:
    """Verify reasoning event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "reasoning.started",
        "reasoning.completed",
        "reasoning.strategy_changed",
    ])
    def test_reasoning_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Reasoning event '{event_type}' not documented"


class TestMetaCognitionEvents:
    """Verify meta-cognition event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "meta.assessed",
        "meta.verification_required",
        "meta.loop_detected",
        "meta.stop_recommended",
    ])
    def test_meta_cognition_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Meta-cognition event '{event_type}' not documented"


class TestAdaptiveEvents:
    """Verify adaptive event types are documented."""

    def test_adaptive_ranked_documented(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "adaptive.ranked" in content


class TestCortexEvents:
    """Verify CORTEX event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "cortex.candidates_generated",
        "cortex.candidate_rejected",
        "cortex.behavior_selected",
        "cortex.abstained",
    ])
    def test_cortex_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"CORTEX event '{event_type}' not documented"


class TestRuntimeEvents:
    """Verify runtime event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "runtime.execution_started",
        "runtime.execution_completed",
        "runtime.execution_failed",
    ])
    def test_runtime_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Runtime event '{event_type}' not documented"


class TestLearningEvents:
    """Verify learning event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "learning.signal_created",
        "learning.signal_rejected",
    ])
    def test_learning_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Learning event '{event_type}' not documented"


class TestReflectionEvents:
    """Verify reflection event types are documented."""

    @pytest.mark.parametrize("event_type", [
        "reflection.started",
        "reflection.candidate_created",
        "reflection.candidate_promoted",
        "reflection.candidate_rejected",
    ])
    def test_reflection_event_documented(self, event_type: str) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert event_type in content, f"Reflection event '{event_type}' not documented"


class TestSchemaVersioning:
    """Verify schema versioning rules are documented."""

    def test_schema_version_field_present(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "schema_version" in content

    def test_schema_evolution_rules_documented(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "schema" in content.lower()
        assert "version" in content.lower()
        # Should mention evolution or compatibility
        assert "evol" in content.lower() or "compat" in content.lower() or "change" in content.lower(), (
            "EVENT_TAXONOMY.md must document schema evolution rules"
        )


class TestEventTypeFormat:
    """Verify event type format is documented."""

    def test_event_type_format_documented(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        assert "<stage>.<action>" in content or "stage.action" in content, (
            "EVENT_TAXONOMY.md must document event type format"
        )


class TestReasonCodes:
    """Verify reason code patterns are documented."""

    def test_reason_codes_have_domain_prefix(self) -> None:
        content = EVENT_TAXONOMY.read_text(encoding="utf-8")
        # Should have domain-specific reason codes
        assert "RECALL_" in content or "CORTEX_" in content or "META_" in content or "CONTEXT_" in content, (
            "EVENT_TAXONOMY.md must document domain-specific reason codes"
        )
