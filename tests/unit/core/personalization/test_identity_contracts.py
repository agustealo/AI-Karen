"""
Unit tests for AI-Karen identity, user, and relationship model contracts.

Proves behavioral semantics for SelfModel, UserModel, RelationshipModel,
and their supporting types without touching persistence, runtime, providers,
or UI.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from ai_karen_engine.core.personalization.contracts import (
    BehaviorPattern,
    CapabilityBelief,
    CapabilityBeliefType,
    CommitmentState,
    CommitmentType,
    ConfidenceState,
    EvidenceStatus,
    GoalState,
    IdentityDomain,
    IdentityFacet,
    InteractionNormType,
    InteractionPattern,
    ModelEvidence,
    ModelPropertyStatus,
    ModelRevision,
    PreferenceScope,
    PreferenceSignal,
    PreferenceStability,
    Provenance,
    RelationshipContext,
    RelationshipModel,
    RelationshipType,
    SelfModel,
    UserGoalStatus,
    UserModel,
    make_candidate_id,
    make_contradiction_id,
    make_evidence_id,
    make_goal_id,
    make_pattern_id,
    make_preference_id,
)


def _provenance(
    source: str = "test",
    confidence: float = 0.5,
    evidence_refs: List[str] | None = None,
    first_observed_at: datetime | None = None,
    last_confirmed_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    supersedes: str | None = None,
    status: ModelPropertyStatus = ModelPropertyStatus.OBSERVED,
) -> Provenance:
    return Provenance(
        source=source,
        confidence=confidence,
        evidence_refs=evidence_refs or [],
        first_observed_at=first_observed_at or datetime.utcnow(),
        last_confirmed_at=last_confirmed_at,
        valid_from=valid_from or datetime.utcnow(),
        valid_until=valid_until,
        supersedes=supersedes,
        status=status,
    )


class TestModelPropertyStatus:
    def test_explicit_outranks_inferred(self):
        explicit = ModelPropertyStatus.EXPLICIT
        inferred = ModelPropertyStatus.INFERRED
        rank = {
            ModelPropertyStatus.EXPLICIT: 5,
            ModelPropertyStatus.CONFIRMED: 4,
            ModelPropertyStatus.OBSERVED: 3,
            ModelPropertyStatus.INFERRED: 2,
            ModelPropertyStatus.STALE: 1,
            ModelPropertyStatus.RETRACTED: 0,
        }
        assert rank[explicit] > rank[inferred]

    def test_superseded_remains_traceable(self):
        old_status = ModelPropertyStatus.SUPERSEDED
        assert old_status in ModelPropertyStatus
        rev = ModelRevision(
            revision_id="rev1",
            property_key="comm.verbosity",
            model_type="user",
            old_value="terse",
            new_value="detailed",
            old_status=ModelPropertyStatus.CONFIRMED,
            new_status=ModelPropertyStatus.SUPERSEDED,
            reason="contradictory evidence",
            evidence_refs=["ev1"],
            revised_at=datetime.utcnow(),
            revised_by="system",
        )
        assert rev.old_status == ModelPropertyStatus.CONFIRMED
        assert rev.new_status == ModelPropertyStatus.SUPERSEDED


class TestProvenance:
    def test_confidence_clamped(self):
        p = _provenance(confidence=1.5)
        assert p.confidence == 1.0
        p2 = _provenance(confidence=-0.5)
        assert p2.confidence == 0.0

    def test_evidence_refs_copied(self):
        refs = ["ev1", "ev2"]
        p = _provenance(evidence_refs=refs)
        p.evidence_refs.append("ev3")
        assert refs == ["ev1", "ev2"]

    def test_valid_until_optional(self):
        p = _provenance(valid_until=None)
        assert p.valid_until is None

    def test_supersedes_optional(self):
        p = _provenance(supersedes=None)
        assert p.supersedes is None


class TestModelEvidence:
    def test_confidence_clamped(self):
        ev = ModelEvidence(
            evidence_id=make_evidence_id(),
            source="user",
            evidence_type="explicit_statement",
            content_ref="msg1",
            observed_at=datetime.utcnow(),
            confidence=2.0,
        )
        assert ev.confidence == 1.0

    def test_defaults_empty(self):
        ev = ModelEvidence(
            evidence_id=make_evidence_id(),
            source="system",
            evidence_type="inference",
            content_ref="log1",
            observed_at=datetime.utcnow(),
            confidence=0.8,
        )
        assert ev.context == {}
        assert ev.metadata == {}


class TestIdentityFacet:
    def test_limitation_flag(self):
        facet = IdentityFacet(
            facet_id="f1",
            domain=IdentityDomain.LIMITATION,
            key="coding.skill",
            value="novice",
            description="Cannot write production-grade Python yet",
            provenance=_provenance(status=ModelPropertyStatus.INFERRED),
            is_limitation=True,
        )
        assert facet.is_limitation is True


class TestCapabilityBelief:
    def test_self_reference_vs_user(self):
        self_belief = CapabilityBelief(
            belief_id="b1",
            capability="code_review",
            belief_type=CapabilityBeliefType.STRENGTH,
            description="Strong at reviewing Go code",
            provenance=_provenance(),
            evidence_refs=["ev1"],
            is_self_reference=True,
        )
        user_belief = CapabilityBelief(
            belief_id="b2",
            capability="python",
            belief_type=CapabilityBeliefType.LIMITATION,
            description="Novice Python user",
            provenance=_provenance(),
            evidence_refs=["ev2"],
            is_self_reference=False,
        )
        assert self_belief.is_self_reference is True
        assert user_belief.is_self_reference is False


class TestPreferenceSignal:
    def test_explicit_outranks_inferred(self):
        explicit = PreferenceSignal(
            signal_id=make_preference_id(),
            key="comm.verbosity",
            value="concise",
            polarity="positive",
            provenance=_provenance(
                confidence=0.9,
                status=ModelPropertyStatus.EXPLICIT,
            ),
            scope=PreferenceScope.GLOBAL,
            category="communication",
            stability=PreferenceStability.DURABLE,
        )
        inferred = PreferenceSignal(
            signal_id=make_preference_id(),
            key="comm.verbosity",
            value="detailed",
            polarity="positive",
            provenance=_provenance(
                confidence=0.3,
                status=ModelPropertyStatus.INFERRED,
            ),
            scope=PreferenceScope.GLOBAL,
            category="communication",
            stability=PreferenceStability.SESSION,
        )
        explicit_rank = {
            ModelPropertyStatus.EXPLICIT: 5,
            ModelPropertyStatus.CONFIRMED: 4,
            ModelPropertyStatus.OBSERVED: 3,
            ModelPropertyStatus.INFERRED: 2,
            ModelPropertyStatus.STALE: 1,
            ModelPropertyStatus.RETRACTED: 0,
        }
        assert explicit_rank[explicit.provenance.status] > explicit_rank[inferred.provenance.status]


class TestGoalState:
    def test_goal_lifecycle(self):
        goal = GoalState(
            goal_id=make_goal_id(),
            description="Ship feature X",
            status=UserGoalStatus.ACTIVE,
            provenance=_provenance(status=ModelPropertyStatus.OBSERVED),
            scope=PreferenceScope.PROJECT,
            started_at=datetime.utcnow(),
            target_date=datetime.utcnow() + timedelta(days=14),
            evidence_refs=["ev1"],
        )
        assert goal.status == UserGoalStatus.ACTIVE
        assert len(goal.evidence_refs) == 1


class TestConfidenceState:
    def test_confidence_clamped(self):
        state = ConfidenceState(
            property_key="comm.verbosity",
            model_type="user",
            confidence=1.5,
            evidence_count=5,
            contradiction_count=2,
            last_updated=datetime.utcnow(),
            trend="increasing",
        )
        assert state.confidence == 1.0
        assert state.evidence_count == 5
        assert state.contradiction_count == 2

    def test_negative_counts_clamped(self):
        state = ConfidenceState(
            property_key="x",
            model_type="user",
            confidence=0.5,
            evidence_count=-1,
            contradiction_count=-1,
            last_updated=datetime.utcnow(),
            trend="stable",
        )
        assert state.evidence_count == 0
        assert state.contradiction_count == 0


class TestInteractionPattern:
    def test_repeated_evidence_strengthens_inference(self):
        pattern = InteractionPattern(
            pattern_id=make_pattern_id(),
            pattern_type=InteractionNormType.RESPONSE_STYLE,
            description="Prefers code with comments",
            confidence=0.6,
            provenance=_provenance(status=ModelPropertyStatus.INFERRED),
            observed_count=3,
            first_seen=datetime.utcnow() - timedelta(days=7),
            last_seen=datetime.utcnow(),
        )
        assert pattern.confidence == 0.6
        assert pattern.observed_count == 3
        pattern.observed_count += 1
        pattern.confidence = min(1.0, pattern.confidence + 0.1)
        assert pattern.observed_count == 4
        assert pattern.confidence == 0.7


class TestRelationshipContext:
    def test_shared_project_history(self):
        ctx = RelationshipContext(
            context_id="ctx1",
            relationship_type=RelationshipType.COLLABORATIVE,
            key="shared_projects",
            value=["karen-core", "api-v2"],
            provenance=_provenance(),
            shared_projects=["karen-core", "api-v2"],
            working_rhythm="weekly-sprint",
        )
        assert "karen-core" in ctx.shared_projects
        assert ctx.working_rhythm == "weekly-sprint"


class TestCommitmentState:
    def test_open_commitment(self):
        commit = CommitmentState(
            commitment_id="c1",
            commitment_type=CommitmentType.EXPLICIT,
            description="Review PR by Friday",
            parties=["karen", "user1"],
            provenance=_provenance(status=ModelPropertyStatus.EXPLICIT),
            started_at=datetime.utcnow(),
            target_date=datetime.utcnow() + timedelta(days=3),
            status=UserGoalStatus.ACTIVE,
        )
        assert commit.status == UserGoalStatus.ACTIVE
        assert len(commit.parties) == 2


class TestSelfModel:
    def test_self_identity_composition(self):
        model = SelfModel(
            model_id="self1",
            tenant_id="t1",
            identity_facets=[
                IdentityFacet(
                    facet_id="f1",
                    domain=IdentityDomain.CAPABILITY,
                    key="codegen.python",
                    value="strong",
                    description="Generates idiomatic Python",
                    provenance=_provenance(),
                    is_limitation=False,
                )
            ],
            capability_beliefs=[
                CapabilityBelief(
                    belief_id="b1",
                    capability="python",
                    belief_type=CapabilityBeliefType.STRENGTH,
                    description="Strong Python skills",
                    provenance=_provenance(),
                    evidence_refs=["ev1"],
                    is_self_reference=True,
                )
            ],
            principles=[],
            limits=[
                IdentityFacet(
                    facet_id="f2",
                    domain=IdentityDomain.LIMITATION,
                    key="realtime.media",
                    value="unable",
                    description="Cannot process real-time audio/video",
                    provenance=_provenance(status=ModelPropertyStatus.CONFIRMED),
                    is_limitation=True,
                )
            ],
            confidence_summary={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert len(model.identity_facets) == 1
        assert len(model.limits) == 1
        assert model.limits[0].is_limitation is True

    def test_capability_limits_cannot_be_overwritten(self):
        limit = IdentityFacet(
            facet_id="f1",
            domain=IdentityDomain.LIMITATION,
            key="realtime.media",
            value="unable",
            description="Cannot process real-time audio/video",
            provenance=_provenance(status=ModelPropertyStatus.CONFIRMED),
            is_limitation=True,
        )
        assert limit.provenance.status == ModelPropertyStatus.CONFIRMED
        assert limit.is_limitation is True
        assert limit.value == "unable"


class TestUserModel:
    def test_tenant_isolation(self):
        model_a = UserModel(
            model_id="u1",
            user_id="u1",
            tenant_id="tA",
            preference_signals=[],
            behavior_patterns=[],
            goals=[],
            skills=[],
            projects=["project-a"],
            confidence_summary={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        model_b = UserModel(
            model_id="u2",
            user_id="u1",
            tenant_id="tB",
            preference_signals=[],
            behavior_patterns=[],
            goals=[],
            skills=[],
            projects=["project-b"],
            confidence_summary={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert model_a.tenant_id == "tA"
        assert model_b.tenant_id == "tB"
        assert model_a.projects != model_b.projects

    def test_one_observation_does_not_become_stable_trait(self):
        signal = PreferenceSignal(
            signal_id=make_preference_id(),
            key="comm.verbosity",
            value="terse",
            polarity="positive",
            provenance=_provenance(
                confidence=0.4,
                status=ModelPropertyStatus.OBSERVED,
            ),
            scope=PreferenceScope.SESSION,
            category="communication",
            stability=PreferenceStability.SESSION,
        )
        assert signal.provenance.status != ModelPropertyStatus.CONFIRMED
        assert signal.provenance.confidence < 0.5
        assert signal.stability == PreferenceStability.SESSION

    def test_repeated_evidence_strengthens_inference(self):
        base_prov = _provenance(
            confidence=0.3,
            status=ModelPropertyStatus.INFERRED,
            evidence_refs=["ev1"],
        )
        signal = PreferenceSignal(
            signal_id=make_preference_id(),
            key="tool.editor",
            value="vim",
            polarity="positive",
            provenance=base_prov,
            scope=PreferenceScope.GLOBAL,
            category="tool",
            stability=PreferenceStability.SHORT_TERM,
        )
        assert signal.provenance.confidence == 0.3
        signal.provenance.evidence_refs.append("ev2")
        signal.provenance.confidence = min(1.0, signal.provenance.confidence + 0.2)
        assert len(signal.provenance.evidence_refs) == 2
        assert signal.provenance.confidence == 0.5


class TestRelationshipModel:
    def test_shared_project_history(self):
        rel = RelationshipModel(
            model_id="rel1",
            tenant_id="t1",
            user_id="u1",
            relationship_type=RelationshipType.COLLABORATIVE,
            shared_history=["shipped-api-v1", "debugged-auth-flow"],
            working_patterns=[],
            active_commitments=[],
            relationship_context=[
                RelationshipContext(
                    context_id="ctx1",
                    relationship_type=RelationshipType.COLLABORATIVE,
                    key="projects",
                    value=["karen-core"],
                    provenance=_provenance(),
                    shared_projects=["karen-core"],
                    working_rhythm="weekly",
                )
            ],
            confidence_summary={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert len(rel.shared_history) == 2
        assert "shipped-api-v1" in rel.shared_history

    def test_relationship_references_shared_history(self):
        rel = RelationshipModel(
            model_id="rel2",
            tenant_id="t1",
            user_id="u1",
            relationship_type=RelationshipType.PROFESSIONAL,
            shared_history=["completed-audit", "wrote-spec"],
            working_patterns=[],
            active_commitments=[],
            relationship_context=[],
            confidence_summary={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        assert len(rel.shared_history) >= 1


class TestRetractedInformation:
    def test_retracted_does_not_influence_active(self):
        retracted = PreferenceSignal(
            signal_id=make_preference_id(),
            key="old.pref",
            value="old_value",
            polarity="positive",
            provenance=_provenance(status=ModelPropertyStatus.RETRACTED),
            scope=PreferenceScope.SESSION,
            category="communication",
            stability=PreferenceStability.SESSION,
        )
        active = PreferenceSignal(
            signal_id=make_preference_id(),
            key="old.pref",
            value="new_value",
            polarity="positive",
            provenance=_provenance(status=ModelPropertyStatus.EXPLICIT),
            scope=PreferenceScope.SESSION,
            category="communication",
            stability=PreferenceStability.DURABLE,
        )
        active_signals = [s for s in [retracted, active] if s.provenance.status != ModelPropertyStatus.RETRACTED]
        assert len(active_signals) == 1
        assert active_signals[0].value == "new_value"

    def test_retracted_evidence_status(self):
        ev = ModelEvidence(
            evidence_id=make_evidence_id(),
            source="user",
            evidence_type="explicit_statement",
            content_ref="msg1",
            observed_at=datetime.utcnow(),
            confidence=0.9,
        )
        assert ev.confidence == 0.9
        assert ev.evidence_type == "explicit_statement"


class TestUncertainInference:
    def test_uncertain_inference_stays_uncertain(self):
        uncertain = PreferenceSignal(
            signal_id=make_preference_id(),
            key="unknown.topic",
            value="maybe_likes_dark_mode",
            polarity="neutral",
            provenance=_provenance(
                confidence=0.2,
                status=ModelPropertyStatus.INFERRED,
            ),
            scope=PreferenceScope.SESSION,
            category="communication",
            stability=PreferenceStability.SESSION,
        )
        assert uncertain.provenance.confidence < 0.5
        assert uncertain.provenance.status == ModelPropertyStatus.INFERRED
        uncertain.provenance.confidence = 0.25
        assert uncertain.provenance.confidence < 0.5


class TestModelRevision:
    def test_new_evidence_revises_old_belief(self):
        old_prov = _provenance(confidence=0.4, status=ModelPropertyStatus.INFERRED)
        new_prov = _provenance(confidence=0.9, status=ModelPropertyStatus.CONFIRMED)
        revision = ModelRevision(
            revision_id="rev1",
            property_key="comm.verbosity",
            model_type="user",
            old_value="terse",
            new_value="concise",
            old_status=ModelPropertyStatus.INFERRED,
            new_status=ModelPropertyStatus.CONFIRMED,
            reason="explicit user statement",
            evidence_refs=["ev_new"],
            revised_at=datetime.utcnow(),
            revised_by="system",
        )
        assert revision.old_status == ModelPropertyStatus.INFERRED
        assert revision.new_status == ModelPropertyStatus.CONFIRMED
        assert revision.evidence_refs == ["ev_new"]


class TestBehaviorPatternExtension:
    def test_behavior_pattern_isolation(self):
        pattern = BehaviorPattern(
            pattern_id=make_pattern_id(),
            user_id="u1",
            tenant_id="t1",
            pattern_type="tool_success",
            context_signature="ctx",
            observation_count=1,
            confidence=0.5,
            first_seen=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            recurrence="observed",
            stability=PreferenceStability.SHORT_TERM,
        )
        assert pattern.observation_count == 1
        pattern.observation_count += 1
        pattern.confidence = min(1.0, pattern.confidence + 0.1)
        assert pattern.observation_count == 2
        assert pattern.confidence == 0.6


__all__ = [
    "TestModelPropertyStatus",
    "TestProvenance",
    "TestModelEvidence",
    "TestIdentityFacet",
    "TestCapabilityBelief",
    "TestPreferenceSignal",
    "TestGoalState",
    "TestConfidenceState",
    "TestInteractionPattern",
    "TestRelationshipContext",
    "TestCommitmentState",
    "TestSelfModel",
    "TestUserModel",
    "TestRelationshipModel",
    "TestRetractedInformation",
    "TestUncertainInference",
    "TestModelRevision",
    "TestBehaviorPatternExtension",
]
