"""Tests for decision lineage specification.

Validates that DecisionLineage has required fields and satisfies
the requirement to explain every final behavior decision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture" / "cognitive-observability"
DECISION_LINEAGE = DOCS_ROOT / "DECISION_LINEAGE.md"


class TestDecisionLineageStructure:
    """Verify DecisionLineage has all required fields."""

    @pytest.mark.parametrize("field", [
        "decision_id",
        "trace_id",
        "request_id",
        "correlation_id",
        "selected_behavior",
        "selection_confidence",
        "candidate_ids",
        "rejected_candidate_ids",
        "rejection_reasons",
        "reason_codes",
        "memory_refs",
        "belief_refs",
        "goal_refs",
        "salience_ref",
        "context_plan_ref",
        "reasoning_ref",
        "meta_ref",
        "adaptive_ref",
        "policy_ref",
        "policy_version",
        "verification_required",
        "verification_depth",
        "abstained",
        "abstain_reason",
        "occurred_at",
        "schema_version",
    ])
    def test_decision_lineage_field_documented(self, field: str) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8")
        assert field in content, f"DecisionLineage field '{field}' not documented"


class TestDecisionLineageQuestions:
    """Verify the spec answers all required questions."""

    @pytest.mark.parametrize("question_keyword", [
        "what did karen choose",
        "alternatives",
        "rejected",
        "why",
        "memory mattered",
        "beliefs mattered",
        "goal mattered",
        "salience",
        "policy block",
        "verification required",
        "policy version",
    ])
    def test_decision_question_addressed(self, question_keyword: str) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert question_keyword in content, (
            f"Decision lineage must address: '{question_keyword}'"
        )


class TestNoRawChainOfThought:
    """Verify decision lineage explicitly rejects raw chain-of-thought."""

    def test_spec_rejects_raw_reasoning(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "no raw chain-of-thought" in content or "no raw reasoning" in content or "structured decision evidence only" in content, (
            "Decision lineage must explicitly reject raw chain-of-thought"
        )

    def test_spec_uses_references(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "reference" in content, "Decision lineage must use reference-based design"


class TestRejectionTransparency:
    """Verify rejection transparency requirements."""

    def test_spec_requires_rejection_reasons(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "rejection" in content
        assert "reason" in content
        assert "silent" in content or "every rejected" in content, (
            "Spec must require reasons for every rejection"
        )


class TestPolicyVersionPinned:
    """Verify policy version pinning requirement."""

    def test_spec_requires_policy_version(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8")
        assert "policy_version" in content

    def test_spec_documents_drift_detection(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "drift" in content, "Spec must document behavioral drift detection"


class TestAbstentionLineage:
    """Verify abstention is a first-class outcome."""

    def test_spec_documents_abstention(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "abstain" in content

    def test_spec_documents_abstention_reason(self) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert "abstain_reason" in content or "reason for abstention" in content


class TestDecisionEvidenceMatrix:
    """Verify decision evidence matrix is documented."""

    @pytest.mark.parametrize("evidence_type", [
        "selected behavior",
        "candidate set",
        "rejected candidates",
        "memory influences",
        "belief influences",
        "goal influences",
        "salience",
        "context plan",
        "reasoning trace",
        "meta-cognition",
        "adaptive ranking",
        "policy decision",
        "verification",
        "abstention",
    ])
    def test_evidence_type_documented(self, evidence_type: str) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert evidence_type in content, f"Evidence type '{evidence_type}' not documented"


class TestAuditUseCases:
    """Verify audit use cases are documented."""

    @pytest.mark.parametrize("use_case", [
        "why did karen choose",
        "memories influenced",
        "policy block",
        "current policy",
    ])
    def test_audit_use_case_documented(self, use_case: str) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8").lower()
        assert use_case in content, f"Audit use case '{use_case}' not documented"


class TestRelationshipToExisting:
    """Verify relationship to existing structures is documented."""

    @pytest.mark.parametrize("existing", [
        "DecisionProvenance",
        "DecisionObservation",
        "BehaviorDecision",
        "ExecutionDecision",
    ])
    def test_existing_structure_referenced(self, existing: str) -> None:
        content = DECISION_LINEAGE.read_text(encoding="utf-8")
        assert existing in content, f"Existing structure '{existing}' not referenced"
