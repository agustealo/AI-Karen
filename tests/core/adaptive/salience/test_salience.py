from __future__ import annotations

from ai_karen_engine.core.adaptive.salience.contracts import (
    SalienceAssessment,
    SalienceAssessmentRequest,
    SalienceContext,
    SalienceDimension,
    SalienceReasonCode,
    SalienceSignal,
    SalienceSource,
)
from ai_karen_engine.core.adaptive.salience.assessment import SalienceAssessmentEngine
from ai_karen_engine.core.adaptive.salience.decay import SalienceDecayEngine


def _make_request(**kwargs: Any) -> SalienceAssessmentRequest:
    ctx = SalienceContext(request_id="r1", correlation_id="c1", tenant_id="t1", user_id="u1")
    return SalienceAssessmentRequest(context=ctx, **kwargs)


def test_high_urgency_can_produce_high_salience():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.URGENCY, value=0.95, confidence=0.9, reason_codes=[SalienceReasonCode.HIGH_URGENCY])
    ])
    result = engine.assess(req)
    assert result.assessment.overall > 0.5
    assert result.assessment.urgency == 0.95


def test_high_confidence_does_not_automatically_produce_high_salience():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.GOAL_RELEVANCE, value=0.1, confidence=0.99, reason_codes=[SalienceReasonCode.GOAL_CRITICAL])
    ])
    result = engine.assess(req)
    assert result.assessment.overall < 0.3


def test_low_confidence_high_risk_event_can_still_be_salient():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.RISK, value=0.9, confidence=0.2, reason_codes=[SalienceReasonCode.HIGH_RISK])
    ])
    result = engine.assess(req)
    assert result.assessment.overall > 0.5


def test_repeated_trivial_events_remain_low_salience():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.NOVELTY, value=0.05, confidence=0.8, reason_codes=[SalienceReasonCode.LOW_REPETITION])
    ])
    result = engine.assess(req)
    assert result.assessment.overall < 0.2


def test_unresolved_commitment_can_stay_salient():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.UNRESOLVED_STATE, value=1.0, confidence=0.8, persistence_class="persistent", reason_codes=[SalienceReasonCode.UNRESOLVED_COMMITMENT])
    ])
    result = engine.assess(req)
    assert result.assessment.overall > 0.5


def test_resolved_event_can_decay():
    engine = SalienceDecayEngine()
    assessment = SalienceAssessment(novelty=0.8, urgency=0.9, surprise=0.7)
    decayed = engine.decay_assessment(assessment)
    assert decayed.novelty < assessment.novelty
    assert decayed.urgency < assessment.urgency


def test_user_emphasis_raises_salience():
    engine = SalienceAssessmentEngine()
    from ai_karen_engine.core.adaptive.salience.contracts import UserEmphasisSignal
    req = _make_request(signals=[], user_emphasis=[
        UserEmphasisSignal(emphasis_type="critical", target="deployment", strength=0.8, confidence=0.9)
    ])
    result = engine.assess(req)
    assert result.assessment.user_emphasis > 0.5


def test_relationship_relevance_can_affect_weighting():
    engine = SalienceAssessmentEngine()
    from ai_karen_engine.core.adaptive.salience.contracts import RelationshipRelevanceSignal
    req = _make_request(signals=[], relationship_signals=[
        RelationshipRelevanceSignal(relationship_id="r1", relevance_strength=0.9)
    ])
    result = engine.assess(req)
    assert result.assessment.relationship_importance > 0.5


def test_failure_significance_differs_from_generic_negativity():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.FAILURE_SIGNIFICANCE, value=0.9, reason_codes=[SalienceReasonCode.REPEATED_FAILURE])
    ])
    result = engine.assess(req)
    assert SalienceReasonCode.REPEATED_FAILURE in result.assessment.reason_codes
    assert result.assessment.failure_significance == 0.9


def test_components_remain_explainable():
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[
        SalienceSignal(dimension=SalienceDimension.URGENCY, value=0.9, reason_codes=[SalienceReasonCode.HIGH_URGENCY]),
        SalienceSignal(dimension=SalienceDimension.RISK, value=0.7, reason_codes=[SalienceReasonCode.HIGH_RISK]),
    ])
    result = engine.assess(req)
    assert len(result.assessment.reason_codes) >= 2
    assert result.assessment.urgency == 0.9
    assert result.assessment.risk == 0.7


def test_tenant_boundaries_preserved():
    from ai_karen_engine.core.adaptive.salience.contracts import MemorySalienceSignal
    engine = SalienceAssessmentEngine()
    req = _make_request(signals=[], relationship_signals=[
        RelationshipRelevanceSignal(relationship_id="r1", relevance_strength=0.5)
    ])
    result = engine.assess(req)
    for ms in result.memory_signals:
        assert ms.tenant_id == "t1"
    for ga in result.goal_adjustments:
        assert ga.tenant_id == "t1"
