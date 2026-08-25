"""Builds real cognitive-domain objects from declarative scenario fixtures.

Every helper here maps a small, declarative YAML fragment into the concrete
domain contracts used by Karen's cognitive modules (beliefs, preferences,
goals, commitments, salience signals, ...) so scenarios stay data-driven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ai_karen_engine.core.personalization.contracts import (
    PreferenceCategory,
    PreferenceEvidenceSourceType,
    PreferenceRecord,
    PreferenceScope,
    PreferenceState,
    PreferenceStability,
    UserGoalStatus,
)
from ai_karen_engine.core.personalization.goals.contracts import (
    Commitment,
    CommitmentCondition,
    CommitmentEvidence,
    CommitmentParty,
    CommitmentSource,
    CommitmentStrength,
    CommitmentStatus,
    CompletionEvidenceSource,
    EvidenceSourceType,
    Goal,
    GoalOrigin,
    GoalPriority,
    GoalState,
    GoalType,
    Intention,
    IntentionPriority,
    IntentionState,
    IntentionTriggerType,
)
from ai_karen_engine.core.reasoning.belief.contracts import (
    BeliefClaim,
    ClaimScope,
    ClaimStatus,
    ClaimTemporalValidity,
    Evidence,
    EvidenceRelation,
    EvidenceStrength,
    EvidenceType,
)
from ai_karen_engine.core.adaptive.salience.contracts import (
    PredictionError,
    UserEmphasisSignal,
    ExpectedState,
    ObservedState,
    SalienceSignal,
    SalienceDimension,
    SalienceReasonCode,
    SalienceSource,
)

# Sentinel used to make type-checkers/ignores explicit at import boundaries.
# (mypy is told to ignore the cognitive imports via per-line comments.)


def _enum(value: Any, enum_cls: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    text = str(value)
    try:
        return enum_cls(text)
    except ValueError:
        try:
            return enum_cls[text]
        except KeyError:
            return default


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _parse_claim_text(text: str) -> tuple[str, str, str]:
    """Parse a ``subject predicate=object`` style claim shorthand."""
    if "=" in text:
        left, obj = text.split("=", 1)
        left = left.strip()
        parts = left.split()
        if len(parts) >= 2:
            return parts[0], parts[1], obj.strip()
        if len(parts) == 1:
            return parts[0], "is", obj.strip()
        return "fact", "is", text.strip()
    if " " in text.strip():
        parts = text.strip().split()
        return parts[0], "is", " ".join(parts[1:])
    return text.strip(), "is", ""


def build_claim(d: dict[str, Any], tenant_id: str, user_id: str) -> BeliefClaim:
    claim_id = d.get("id") or d.get("claim_id") or f"claim_{id(d)}"
    if "subject" in d and "predicate" in d and "object" in d:
        subject, predicate, obj = d["subject"], d["predicate"], d["object"]
    else:
        subject, predicate, obj = _parse_claim_text(d.get("claim", d.get("subject", "")))
    temporal = ClaimTemporalValidity(
        asserted_at=_parse_dt(d.get("temporal", {}).get("asserted_at")),
        observed_at=_parse_dt(d.get("temporal", {}).get("observed_at")),
        valid_from=_parse_dt(d.get("temporal", {}).get("valid_from")),
        valid_until=_parse_dt(d.get("temporal", {}).get("valid_until")),
        last_verified_at=_parse_dt(d.get("temporal", {}).get("last_verified_at")),
    )
    return BeliefClaim(
        claim_id=claim_id,
        subject=subject,
        predicate=predicate,
        object=obj,
        status=_enum(d.get("status"), ClaimStatus, ClaimStatus.OBSERVED),
        source=_enum(d.get("source"), EvidenceType, EvidenceType.OBSERVATION),
        source_ref=d.get("source_ref"),
        scope=_enum(d.get("scope"), ClaimScope, ClaimScope.USER),
        confidence=float(d.get("confidence", 0.5)),
        tenant_id=tenant_id,
        user_id=user_id if d.get("user_scoped", True) else None,
        claim_format=d.get("claim_format", "triple"),
        provenance=d.get("provenance", "fixture"),
        evidence_ids=list(d.get("evidence_ids", [])),
        contradictions=list(d.get("contradictions", [])),
        superseded_by=d.get("superseded_by"),
        version=int(d.get("version", 1)),
        temporal=temporal,
        metadata=dict(d.get("metadata", {})),
    )


def build_evidence(d: dict[str, Any], tenant_id: str, user_id: str) -> Evidence:
    return Evidence(
        evidence_id=d.get("id") or d.get("evidence_id") or f"ev_{id(d)}",
        type=_enum(d.get("type"), EvidenceType, EvidenceType.OBSERVATION),
        source=d.get("source", "fixture"),
        source_ref=d.get("source_ref"),
        content=d.get("content", ""),
        summary=d.get("summary", ""),
        strength=_enum(d.get("strength"), EvidenceStrength, EvidenceStrength.MODERATE),
        relation=_enum(
            d.get("relation"),
            EvidenceRelation,
            EvidenceRelation.SUPPORTS,
        ),
        confidence=float(d.get("confidence", 0.8)),
        observed_at=_parse_dt(d.get("observed_at")),
        expires_at=_parse_dt(d.get("expires_at")),
        authority=d.get("authority", ""),
        tenant_id=d.get("tenant_id", tenant_id),
        user_id=d.get("user_id", user_id),
        claim_ids=list(d.get("claim_ids", [])),
        metadata=dict(d.get("metadata", {})),
        sensitivity=d.get("sensitivity", "internal"),
        redacted=bool(d.get("redacted", False)),
    )


def build_preference(d: dict[str, Any], tenant_id: str, user_id: str) -> PreferenceRecord:
    now = _parse_dt(d.get("observed_at")) or datetime.utcnow()
    return PreferenceRecord(
        preference_id=d.get("id") or d.get("preference_id") or f"pref_{id(d)}",
        user_id=d.get("user_id", user_id),
        tenant_id=d.get("tenant_id", tenant_id),
        key=d.get("key", ""),
        value=d.get("value"),
        confidence=float(d.get("confidence", 0.5)),
        stability=_enum(d.get("stability"), PreferenceStability, PreferenceStability.SESSION),
        state=_enum(d.get("state"), PreferenceState, PreferenceState.OBSERVED),
        evidence_count=int(d.get("evidence_count", 1)),
        contradiction_count=int(d.get("contradiction_count", 0)),
        first_observed_at=now,
        last_observed_at=now,
        last_confirmed_at=_parse_dt(d.get("last_confirmed")) or now,
        source_types=list(d.get("source_types", d.get("sources", ["explicit_user_statement"]))),
        scope=_enum(d.get("scope"), PreferenceScope, PreferenceScope.GLOBAL),
        version=int(d.get("version", 1)),
        category=_enum(
            d.get("category"),
            PreferenceCategory,
            PreferenceCategory.DOMAIN,
        ),
        metadata=dict(d.get("metadata", {})),
    )


def build_goal(d: dict[str, Any], tenant_id: str, user_id: str) -> Goal:
    now = _parse_dt(d.get("observed_at")) or datetime.utcnow()
    return Goal(
        goal_id=d.get("id") or d.get("goal_id") or f"goal_{id(d)}",
        tenant_id=d.get("tenant_id", tenant_id),
        user_id=d.get("user_id", user_id),
        description=d.get("description", ""),
        goal_type=_enum(d.get("type"), GoalType, GoalType.EXPLICIT),
        origin=_enum(d.get("origin"), GoalOrigin, GoalOrigin.USER_STATED),
        state=_enum(d.get("state"), GoalState, GoalState.ACTIVE),
        priority=_enum(d.get("priority"), GoalPriority, GoalPriority.MEDIUM),
        scope=_enum(d.get("scope"), PreferenceScope, PreferenceScope.GLOBAL),
        confidence=float(d.get("confidence", 0.8)),
        evidence_refs=list(d.get("evidence", [])),
        started_at=_parse_dt(d.get("started_at")) or now,
        last_observed_at=_parse_dt(d.get("last_observed_at")) or now,
        target_date=_parse_dt(d.get("target_date")),
        expires_at=_parse_dt(d.get("expires_at")),
        parent_goal_id=d.get("parent_goal_id"),
        child_goal_ids=list(d.get("child_goal_ids", [])),
        depends_on=list(d.get("depends_on", [])),
        blocks=list(d.get("blocks", [])),
        conflicts_with=list(d.get("conflicts_with", [])),
        completion_evidence_required=[
            _enum(x, CompletionEvidenceSource, CompletionEvidenceSource.USER_CONFIRMED)
            for x in d.get("completion_evidence_required", [])
        ],
        completion_evidence=list(d.get("completion_evidence", [])),
        completion_evidence_sources=[
            _enum(x, CompletionEvidenceSource, CompletionEvidenceSource.USER_CONFIRMED)
            for x in d.get("completion_evidence_sources", [])
        ],
        superseded_by=d.get("superseded_by"),
        metadata=dict(d.get("metadata", {})),
    )


def build_intention(d: dict[str, Any], tenant_id: str, user_id: str) -> Intention:
    now = datetime.utcnow()
    return Intention(
        intention_id=d.get("id") or d.get("intention_id") or f"int_{id(d)}",
        goal_id=d.get("goal_id", ""),
        tenant_id=d.get("tenant_id", tenant_id),
        user_id=d.get("user_id", user_id),
        description=d.get("description", ""),
        state=_enum(d.get("state"), IntentionState, IntentionState.FORMED),
        priority=_enum(d.get("priority"), IntentionPriority, IntentionPriority.MEDIUM),
        trigger_type=_enum(
            d.get("trigger_type"),
            IntentionTriggerType,
            IntentionTriggerType.GOAL_STATE_RELEVANT,
        ),
        trigger_condition=d.get("trigger_condition", ""),
        context=d.get("context", ""),
        evidence_refs=list(d.get("evidence", [])),
        confidence=float(d.get("confidence", 0.5)),
        formed_at=_parse_dt(d.get("formed_at")) or now,
        activated_at=_parse_dt(d.get("activated_at")),
        fulfilled_at=_parse_dt(d.get("fulfilled_at")),
        invalidated_at=_parse_dt(d.get("invalidated_at")),
    )


def build_commitment(d: dict[str, Any], tenant_id: str, user_id: str) -> Commitment:
    now = _parse_dt(d.get("observed_at")) or datetime.utcnow()
    return Commitment(
        commitment_id=d.get("id") or d.get("commitment_id") or f"commit_{id(d)}",
        tenant_id=d.get("tenant_id", tenant_id),
        user_id=d.get("user_id", user_id),
        parties=[_enum(p, CommitmentParty, CommitmentParty.USER) for p in d.get("parties", ["karen", "user"])],
        description=d.get("description", ""),
        source=_enum(d.get("source"), CommitmentSource, CommitmentSource.USER_STATEMENT),
        strength=_enum(d.get("strength"), CommitmentStrength, CommitmentStrength.COMMITTED),
        status=_enum(d.get("status"), CommitmentStatus, CommitmentStatus.ACTIVE),
        confidence=float(d.get("confidence", 0.9)),
        conditions=[
            CommitmentCondition(
                condition_id=c.get("id", "c1"),
                description=c.get("description", ""),
                met=bool(c.get("met", False)),
                evidence_ref=c.get("evidence_ref"),
            )
            for c in d.get("conditions", [])
        ],
        evidence=[
            CommitmentEvidence(
                evidence_id=e.get("id", "ev1"),
                source=_enum(e.get("source"), CommitmentSource, CommitmentSource.USER_STATEMENT),
                source_ref=e.get("source_ref"),
                confidence=float(e.get("confidence", 0.8)),
                observed_at=_parse_dt(e.get("observed_at")) or now,
                strength=_enum(e.get("strength"), CommitmentStrength, CommitmentStrength.COMMITTED),
                tenant_id=d.get("tenant_id", tenant_id),
                user_id=d.get("user_id", user_id),
            )
            for e in d.get("evidence", [])
        ],
        deadline=_parse_dt(d.get("deadline")),
        committed_at=_parse_dt(d.get("committed_at")) or now,
        fulfilled_at=_parse_dt(d.get("fulfilled_at")),
        failed_at=_parse_dt(d.get("failed_at")),
        superseded_by=d.get("superseded_by"),
        metadata=dict(d.get("metadata", {})),
    )


def build_salience_signal(d: dict[str, Any]) -> SalienceSignal:
    rc = d.get("reason_codes", [])
    if isinstance(rc, str):
        rc = [rc]
    return SalienceSignal(
        dimension=_enum(d.get("dimension"), SalienceDimension, SalienceDimension.NOVELTY),
        value=float(d.get("value", 0.0)),
        confidence=float(d.get("confidence", 0.8)),
        source=_enum(d.get("source"), SalienceSource, SalienceSource.ADAPTIVE_SIGNAL),
        reason_codes=[_enum(r, SalienceReasonCode, SalienceReasonCode.PREDICTION_ERROR) for r in rc],
        decay_rate=float(d.get("decay_rate", 0.1)),
        retrigger_count=int(d.get("retrigger_count", 0)),
        last_activated_at=d.get("last_activated_at"),
        persistence_class=d.get("persistence_class", "standard"),
        source_ref=d.get("source_ref", ""),
        metadata=dict(d.get("metadata", {})),
    )


def build_user_emphasis(d: dict[str, Any]) -> UserEmphasisSignal:
    return UserEmphasisSignal(
        emphasis_type=d.get("type", "critical"),
        target=d.get("target", ""),
        strength=float(d.get("strength", 0.5)),
        confidence=float(d.get("confidence", 0.8)),
        source_text=d.get("source_text", ""),
        metadata=dict(d.get("metadata", {})),
    )


def build_prediction_error(d: dict[str, Any]) -> PredictionError:
    return PredictionError(
        expected=ExpectedState(
            description=d.get("expected", {}).get("description", ""),
            confidence=float(d.get("expected", {}).get("confidence", 0.0)),
            source_ref=d.get("expected", {}).get("source_ref", ""),
        ),
        observed=ObservedState(
            description=d.get("observed", {}).get("description", ""),
            confidence=float(d.get("observed", {}).get("confidence", 0.0)),
            source_ref=d.get("observed", {}).get("source_ref", ""),
        ),
        error_magnitude=float(d.get("error_magnitude", 0.5)),
        dimension_affected=_enum(
            d.get("dimension"),
            SalienceDimension,
            SalienceDimension.SURPRISE,
        ),
        metadata=dict(d.get("metadata", {})),
    )


@dataclass
class CognitiveState:
    """Fully materialized cognitive state for a scenario."""

    claims: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    preferences: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    intentions: list = field(default_factory=list)
    commitments: list = field(default_factory=list)
    salience_signals: list = field(default_factory=list)
    user_emphasis: list = field(default_factory=list)
    prediction_errors: list = field(default_factory=list)
    context_candidates: list = field(default_factory=list)
    policy_constraints: dict = field(default_factory=dict)
    deleted_ids: set = field(default_factory=set)
    purged_claims: list = field(default_factory=list)


def build_state(scenario: Any) -> CognitiveState:
    """Materialize a Scenario's raw dict into a CognitiveState of real objects."""
    raw = scenario.raw
    tenant = scenario.tenant_id
    user = scenario.user_id
    state = CognitiveState()

    claims = [build_claim(c, tenant, user) for c in raw.get("memories", []) or raw.get("claims", [])]
    for claim in claims:
        state.claims.append(claim)

    belief = raw.get("beliefs") or {}
    for ev in belief.get("evidence", []):
        e = build_evidence(ev, tenant, user)
        state.evidence.setdefault(e.claim_ids[0] if e.claim_ids else "_global", []).append(e)
    for cl in belief.get("claims", []):
        claim = build_claim(cl, tenant, user)
        if claim.claim_id not in {c.claim_id for c in state.claims}:
            state.claims.append(claim)

    for p in raw.get("preferences", []) or []:
        state.preferences.append(build_preference(p, tenant, user))

    for g in raw.get("goals", []) or []:
        state.goals.append(build_goal(g, tenant, user))
    for it in raw.get("intentions", []) or []:
        state.intentions.append(build_intention(it, tenant, user))

    rel = raw.get("relationship") or {}
    for c in rel.get("commitments", []) or []:
        state.commitments.append(build_commitment(c, tenant, user))

    sal = raw.get("salience") or {}
    for s in sal.get("signals", []) or []:
        state.salience_signals.append(build_salience_signal(s))
    for e in sal.get("emphasis", []) or []:
        state.user_emphasis.append(build_user_emphasis(e))
    for pe in sal.get("prediction_errors", []) or []:
        state.prediction_errors.append(build_prediction_error(pe))

    state.context_candidates = [
        {
            "memory_id": c.get("id", c.get("memory_id", f"m_{i}")),
            "retrieval_score": float(c.get("retrieval_score", 0.5)),
            "confidence": float(c.get("confidence", 1.0)),
            "salience_value": float(c.get("salience_value", 0.0)),
            "persistence_class": c.get("persistence_class", "standard"),
            "content": c.get("content", ""),
            "last_activated_at": c.get("last_activated_at"),
            "decay_rate": float(c.get("decay_rate", 0.1)),
        }
        for i, c in enumerate(raw.get("context_candidates", []) or [])
    ]

    state.policy_constraints = {
        "deny": list(raw.get("policy_constraints", {}).get("deny", [])),
        "tenant_boundary": bool(raw.get("policy_constraints", {}).get("tenant_boundary", True)),
        "max_score": raw.get("policy_constraints", {}).get("max_score"),
    }

    for dm in raw.get("deleted", []) or []:
        state.deleted_ids.add(dm if isinstance(dm, str) else dm.get("id"))
    for pm in raw.get("purged", []) or []:
        state.purged_claims.append(build_claim(pm, tenant, user))
        state.deleted_ids.add(pm.get("id"))

    return state
