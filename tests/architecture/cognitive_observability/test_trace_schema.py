"""Tests for cognitive trace schema specification.

Validates that the documented cognitive trace model has required fields,
correct structure, and satisfies architectural constraints.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture" / "cognitive-observability"
TRACE_MODEL = DOCS_ROOT / "TRACE_MODEL.md"
EVENT_TAXONOMY = DOCS_ROOT / "EVENT_TAXONOMY.md"
DECISION_LINEAGE = DOCS_ROOT / "DECISION_LINEAGE.md"
MEMORY_LINEAGE = DOCS_ROOT / "MEMORY_LINEAGE.md"
LEARNING_LINEAGE = DOCS_ROOT / "LEARNING_LINEAGE.md"
PRIVACY_REDACTION = DOCS_ROOT / "PRIVACY_REDACTION.md"
REPLAY_SPEC = DOCS_ROOT / "REPLAY_SPEC.md"
TRACE_COMPLETENESS = DOCS_ROOT / "TRACE_COMPLETENESS.md"


class TestTraceModelExists:
    """Verify trace model documentation exists and has required sections."""

    def test_trace_model_file_exists(self) -> None:
        assert TRACE_MODEL.exists(), f"TRACE_MODEL.md not found at {TRACE_MODEL}"

    def test_event_taxonomy_file_exists(self) -> None:
        assert EVENT_TAXONOMY.exists(), f"EVENT_TAXONOMY.md not found at {EVENT_TAXONOMY}"

    def test_decision_lineage_file_exists(self) -> None:
        assert DECISION_LINEAGE.exists(), f"DECISION_LINEAGE.md not found at {DECISION_LINEAGE}"

    def test_memory_lineage_file_exists(self) -> None:
        assert MEMORY_LINEAGE.exists(), f"MEMORY_LINEAGE.md not found at {MEMORY_LINEAGE}"

    def test_learning_lineage_file_exists(self) -> None:
        assert LEARNING_LINEAGE.exists(), f"LEARNING_LINEAGE.md not found at {LEARNING_LINEAGE}"

    def test_privacy_redaction_file_exists(self) -> None:
        assert PRIVACY_REDACTION.exists(), f"PRIVACY_REDACTION.md not found at {PRIVACY_REDACTION}"

    def test_replay_spec_file_exists(self) -> None:
        assert REPLAY_SPEC.exists(), f"REPLAY_SPEC.md not found at {REPLAY_SPEC}"

    def test_trace_completeness_file_exists(self) -> None:
        assert TRACE_COMPLETENESS.exists(), f"TRACE_COMPLETENESS.md not found at {TRACE_COMPLETENESS}"


class TestCognitiveTraceStructure:
    """Verify CognitiveTrace has required structural elements."""

    def test_trace_model_defines_cognitive_trace(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "CognitiveTrace" in content, "CognitiveTrace not defined in TRACE_MODEL.md"

    def test_trace_model_defines_event_graph(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "event graph" in content.lower() or "event_graph" in content.lower(), (
            "TRACE_MODEL.md must describe the trace as an event graph"
        )

    def test_trace_model_defines_request_section(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "request" in content.lower(), "TRACE_MODEL.md must include request section"

    def test_trace_model_defines_perception_intent(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "perception" in content.lower() or "intent" in content.lower(), (
            "TRACE_MODEL.md must include perception/intent section"
        )

    def test_trace_model_defines_recall(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "recall" in content.lower(), "TRACE_MODEL.md must include recall section"

    def test_trace_model_defines_beliefs(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "belief" in content.lower(), "TRACE_MODEL.md must include beliefs section"

    def test_trace_model_defines_goals_intentions(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "goal" in content.lower() or "intention" in content.lower(), (
            "TRACE_MODEL.md must include goals/intentions section"
        )

    def test_trace_model_defines_salience(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "salience" in content.lower(), "TRACE_MODEL.md must include salience section"

    def test_trace_model_defines_context_selection(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "context" in content.lower(), "TRACE_MODEL.md must include context selection section"

    def test_trace_model_defines_reasoning(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "reasoning" in content.lower(), "TRACE_MODEL.md must include reasoning section"

    def test_trace_model_defines_meta_cognition(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "meta" in content.lower(), "TRACE_MODEL.md must include meta-cognition section"

    def test_trace_model_defines_adaptive_recommendations(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "adaptive" in content.lower(), "TRACE_MODEL.md must include adaptive recommendations section"

    def test_trace_model_defines_cortex_decision(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "cortex" in content.lower(), "TRACE_MODEL.md must include CORTEX decision section"

    def test_trace_model_defines_runtime_outcome(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "runtime" in content.lower(), "TRACE_MODEL.md must include runtime outcome section"

    def test_trace_model_defines_learning_signals(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "learning" in content.lower(), "TRACE_MODEL.md must include learning signals section"

    def test_trace_model_defines_reflection_consolidation(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "reflection" in content.lower() or "consolidation" in content.lower(), (
            "TRACE_MODEL.md must include reflection/consolidation section"
        )


class TestTraceIdentityFields:
    """Verify trace identity fields are documented."""

    @pytest.mark.parametrize("field", [
        "trace_id",
        "request_id",
        "correlation_id",
        "tenant_id",
        "schema_version",
        "cognitive_policy_version",
        "started_at",
        "completed_at",
    ])
    def test_trace_identity_field_documented(self, field: str) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert field in content, f"Trace identity field '{field}' not documented in TRACE_MODEL.md"


class TestNotBrainDump:
    """Verify trace model explicitly rejects brain dump approach."""

    def test_trace_model_rejects_serialized_dump(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "brain dump" in content.lower(), (
            "TRACE_MODEL.md must explicitly state this is not a serialized brain dump"
        )

    def test_trace_model_uses_references(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "reference" in content.lower(), "TRACE_MODEL.md must describe reference-based design"


class TestDesignPrinciples:
    """Verify design principles are documented."""

    @pytest.mark.parametrize("principle", [
        "reference",
        "correlation",
        "structured",
        "deletion-safe",
        "sensitivity",
    ])
    def test_design_principle_documented(self, principle: str) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert principle in content.lower(), (
            f"Design principle '{principle}' not documented in TRACE_MODEL.md"
        )


class TestRelationshipToExisting:
    """Verify relationship to existing observability is documented."""

    def test_trace_model_documents_runtime_event_relationship(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "RuntimeEvent" in content, "TRACE_MODEL.md must reference existing RuntimeEvent"

    def test_trace_model_documents_observability_context_relationship(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "ObservabilityContext" in content, (
            "TRACE_MODEL.md must reference existing ObservabilityContext"
        )

    def test_trace_model_documents_decision_provenance_relationship(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "DecisionProvenance" in content, (
            "TRACE_MODEL.md must reference existing DecisionProvenance"
        )

    def test_trace_model_documents_execution_trajectory_relationship(self) -> None:
        content = TRACE_MODEL.read_text(encoding="utf-8")
        assert "ExecutionTrajectory" in content, (
            "TRACE_MODEL.md must reference existing ExecutionTrajectory"
        )
