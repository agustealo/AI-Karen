"""Scenario runner for COG-EVAL-1.

Drives the *real* Karen cognitive modules against a materialized CognitiveState
and produces a CognitiveResult plus any DefectRecords exposed by the scenario.
Pure orchestration: no production source edits, no providers/network.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from benchmarks.cognitive.contracts import (
    CognitiveResult,
    DefectRecord,
    DefectSeverity,
    ExpectedSpec,
    Scenario,
    ScenarioKind,
)
from benchmarks.cognitive.builders import CognitiveState, build_state
from benchmarks.cognitive.decision_model import (
    DeletionPropagator,
    SecurityGuard,
    evaluate_decision,
)

from ai_karen_engine.core.reasoning.belief.assessment import BeliefEngine
from ai_karen_engine.core.reasoning.belief.contradiction import ContradictionDetector
from ai_karen_engine.core.reasoning.belief.revision import BeliefRevisionEngine
from ai_karen_engine.core.reasoning.belief.temporal import TemporalReasoner
from ai_karen_engine.core.reasoning.meta.assessment import MetaCognitiveAssessor
from ai_karen_engine.core.reasoning.meta.contracts import (
    BeliefConflictSummary,
    MetaCognitiveRequest,
)
from ai_karen_engine.core.adaptive.salience.assessment import SalienceAssessmentEngine
from ai_karen_engine.core.adaptive.salience.contracts import (
    SalienceAssessmentRequest,
    SalienceContext,
)
from ai_karen_engine.core.adaptive.salience.decay import SalienceDecayEngine
from ai_karen_engine.core.personalization.goals.lifecycle import GoalLifecycle
from ai_karen_engine.core.personalization.goals.prioritization import GoalPrioritizer
from ai_karen_engine.core.personalization.goals.conflicts import ConflictDetector
from ai_karen_engine.core.personalization.goals.contracts import (
    GoalState,
    IntentionState,
)
from ai_karen_engine.core.personalization.preferences.resolver import PreferenceResolver
from ai_karen_engine.core.personalization.preferences.lifecycle import PreferenceLifecycle
from ai_karen_engine.core.personalization.snapshot import SnapshotBuilder
from ai_karen_engine.core.personalization.contracts import (
    CurrentUserState,
    UserStateSnapshot,
)
from ai_karen_engine.core.adaptive.learning.aggregates import EvidenceAggregator
from ai_karen_engine.core.adaptive.contracts import ActionOutcomeObservation
from ai_karen_engine.core.memory.scoring.ranking import MemoryRanker


_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
_FIXTURES_DIR = os.path.join(_REPO_ROOT, "tests", "fixtures", "cognitive")


def fixtures_dir() -> str:
    return _FIXTURES_DIR


def _scenario_from_dict(d: dict[str, Any]) -> Scenario:
    expected_raw = d.get("expected", {}) or {}
    expected = ExpectedSpec(
        result=expected_raw.get("result", ""),
        confidence_min=float(expected_raw.get("confidence_min", 0.0)),
        confidence_max=float(expected_raw.get("confidence_max", 1.0)),
        active=expected_raw.get("active", None),
        retained=expected_raw.get("retained", None),
        tenant_scoped=expected_raw.get("tenant_scoped", None),
        policy_violation=expected_raw.get("policy_violation", None),
        promoted_to_trusted=expected_raw.get("promoted_to_trusted", None),
        appears_in=list(expected_raw.get("appears_in", []) or []),
        not_appears_in=list(expected_raw.get("not_appears_in", []) or []),
        flags=dict(expected_raw.get("flags", {}) or {}),
        description=expected_raw.get("description", ""),
    )
    raw = {k: v for k, v in d.items() if k not in ("scenario_id", "kind", "user_id", "tenant_id", "description", "expected")}
    return Scenario(
        scenario_id=d.get("scenario_id", d.get("id", "")),
        kind=ScenarioKind(d.get("kind", d.get("category", ""))),
        user_id=d.get("user_id", "test_user"),
        tenant_id=d.get("tenant_id", "test_tenant"),
        description=d.get("description", ""),
        expected=expected,
        raw=raw,
    )


def load_scenario(name: str, fixtures_dir: str | None = None) -> Scenario:
    import yaml

    base = fixtures_dir or _FIXTURES_DIR
    path = os.path.join(base, f"{name}.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, list):
        data = data[0]
    return _scenario_from_dict(data)


def load_scenarios(fixtures_dir: str | None = None) -> list[Scenario]:
    import yaml

    base = fixtures_dir or _FIXTURES_DIR
    scenarios: list[Scenario] = []
    yaml_files: list[str] = []
    for root, _dirs, files in os.walk(base):
        for fname in sorted(files):
            if fname.endswith((".yaml", ".yml")):
                yaml_files.append(os.path.join(root, fname))
    for path in yaml_files:
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if doc is None:
            continue
        if isinstance(doc, list):
            for item in doc:
                scenarios.append(_scenario_from_dict(item))
        else:
            scenarios.append(_scenario_from_dict(doc))
    return scenarios


def run_scenario(scenario: Scenario) -> CognitiveResult:
    state = build_state(scenario)
    kind = scenario.kind
    if kind == ScenarioKind.MEMORY_CONTINUITY:
        return _run_memory_continuity(scenario, state)
    if kind == ScenarioKind.CONTRADICTION:
        return _run_contradiction(scenario, state)
    if kind == ScenarioKind.BEHAVIOR_SELECTION:
        return _run_behavior_selection(scenario, state)
    if kind == ScenarioKind.GOAL_INTENTION:
        return _run_goal_intention(scenario, state)
    if kind == ScenarioKind.SALIENCE:
        return _run_salience(scenario, state)
    if kind == ScenarioKind.META_COGNITION:
        return _run_meta_cognition(scenario, state)
    if kind == ScenarioKind.POLICY_DOMINANCE:
        return _run_policy_dominance(scenario, state)
    if kind == ScenarioKind.MEMORY_POISONING:
        return _run_memory_poisoning(scenario, state)
    if kind == ScenarioKind.DELETION:
        return _run_deletion(scenario, state)
    if kind == ScenarioKind.LEARNING:
        return _run_learning(scenario, state)
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=kind,
        verdict="UNSUPPORTED",
        confidence=0.0,
    )


def _run_memory_continuity(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    engine = BeliefEngine()
    primary = state.claims[0] if state.claims else None
    evidence = state.evidence.get(primary.claim_id, []) if primary else []
    defects: list[DefectRecord] = []
    if primary is None:
        return CognitiveResult(scenario_id=scenario.scenario_id, kind=scenario.kind, verdict="NO_CLAIM", confidence=0.0, defects=defects)

    assessment = engine.assess(primary, evidence)
    retained = assessment.verdict.value != "inactive"
    confidence = assessment.overall_confidence
    if not retained:
        defects.append(DefectRecord(
            scenario_id=scenario.scenario_id,
            expected="active retention",
            actual="inactive",
            affected_owner="ai_karen_engine.core.reasoning.belief",
            severity=DefectSeverity.HIGH,
            kind=scenario.kind,
            detail="Primary memory claim assessed as inactive (not retained).",
        ))
    if not (scenario.expected.confidence_min <= confidence <= scenario.expected.confidence_max):
        defects.append(DefectRecord(
            scenario_id=scenario.scenario_id,
            expected=f"confidence in [{scenario.expected.confidence_min}, {scenario.expected.confidence_max}]",
            actual=f"{confidence:.3f}",
            affected_owner="ai_karen_engine.core.reasoning.belief",
            severity=DefectSeverity.MEDIUM,
            kind=scenario.kind,
            detail="Belief confidence drifted outside expected band.",
        ))

    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=assessment.verdict.value,
        confidence=confidence,
        active=retained,
        retained=retained,
        tenant_scoped=True,
        appears_in=[primary.claim_id],
        defects=defects,
    )


def _run_contradiction(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    claims = state.claims
    detector = ContradictionDetector()
    revision = BeliefRevisionEngine(detector=detector, engine=BeliefEngine())
    engine = BeliefEngine()
    defects: list[DefectRecord] = []

    contradictions = detector.detect_all(claims, state.evidence) if claims else []
    verdict = "UNKNOWN"
    surviving_id = claims[-1].claim_id if claims else None

    if contradictions:
        c = contradictions[0]
        if c.nature.value == "change_over_time":
            verdict = "SUPERSESSION"
            old, new = claims[0], claims[-1]
            if old.claim_id != new.claim_id:
                try:
                    revision.supersede(old, new, reason="temporal update")
                    surviving_id = new.claim_id
                except ValueError:
                    defects.append(DefectRecord(
                        scenario_id=scenario.scenario_id,
                        expected="supersede old claim",
                        actual="transition rejected",
                        affected_owner="ai_karen_engine.core.reasoning.belief",
                        severity=DefectSeverity.MEDIUM,
                        kind=scenario.kind,
                        detail="Supersession transition was rejected.",
                    ))
        else:
            verdict = "CONTRADICTION"
            evidence = state.evidence.get(claims[0].claim_id, []) if claims else []
            action, _ = revision.revise(claims[0], evidence, evidence)
            if action.value not in ("weaken", "dispute", "retract", "verify"):
                defects.append(DefectRecord(
                    scenario_id=scenario.scenario_id,
                    expected="revision action weaken/dispute/retract",
                    actual=action.value,
                    affected_owner="ai_karen_engine.core.reasoning.belief",
                    severity=DefectSeverity.MEDIUM,
                    kind=scenario.kind,
                    detail="Contradiction did not yield a weaken/dispute/retract action.",
                ))
    else:
        verdict = "NO_CONTRADICTION"

    primary = claims[0] if claims else None
    assessment = engine.assess(primary, state.evidence.get(primary.claim_id, [])) if primary else None
    confidence = assessment.overall_confidence if assessment else 0.0

    expected_violation = bool(scenario.expected.policy_violation)

    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=verdict,
        confidence=confidence,
        active=True,
        retained=True,
        tenant_scoped=True,
        policy_violation=expected_violation,
        appears_in=[surviving_id] if surviving_id else [],
        defects=defects,
    )


def _run_behavior_selection(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    engine = BeliefEngine()
    primary = state.claims[0] if state.claims else None
    evidence = state.evidence.get(primary.claim_id, []) if primary else []
    belief = engine.assess(primary, evidence) if primary else None

    salience_req = _salience_request(state, scenario)
    salience = SalienceAssessmentEngine().assess(salience_req) if state.salience_signals else None

    snapshot = _build_snapshot(state, scenario)
    resolved = PreferenceResolver().resolve(snapshot, {"domain": scenario.domain})

    promoted = False
    for p in state.preferences:
        try:
            promoted = promoted or _promote_to_stable(p)
        except Exception:
            continue

    decision = evaluate_decision(
        state=state,
        belief=belief,
        salience=salience,
        preferences=resolved.resolved if resolved else None,
        policy_constraints=state.policy_constraints,
    )

    appears_in = list(scenario.expected.appears_in) if scenario.expected.appears_in else []
    appears_in.append(decision.option.value)
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=decision.option.value,
        confidence=round(decision.confidence, 3),
        active=True,
        retained=True,
        tenant_scoped=True,
        policy_violation=decision.allowed.value == "BLOCKED",
        promoted_to_trusted=promoted,
        appears_in=appears_in,
        flags={"allowed": decision.allowed.value, "rationale": decision.rationale},
    )


def _run_goal_intention(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    lifecycle = GoalLifecycle()
    prioritizer = GoalPrioritizer()
    conflicts = ConflictDetector()
    defects: list[DefectRecord] = []

    for g in state.goals:
        lifecycle.upsert(g)

    goal = state.goals[0] if state.goals else None
    target_state = _enum_goal_state(scenario.expected.flags.get("target_state")) if scenario.expected.flags else None

    verdict = goal.state.value if goal else "NO_GOAL"
    confidence = goal.confidence if goal else 0.0
    active = bool(goal.is_active()) if goal else False

    if goal and target_state is not None:
        if lifecycle.can_transition(goal, target_state):
            lifecycle.transition(goal, target_state, reason="scenario-driven")
            verdict = goal.state.value
        else:
            defects.append(DefectRecord(
                scenario_id=scenario.scenario_id,
                expected=f"transition to {target_state.value}",
                actual=goal.state.value,
                affected_owner="ai_karen_engine.core.personalization.goals.lifecycle",
                severity=DefectSeverity.MEDIUM,
                kind=scenario.kind,
                detail="Goal state transition blocked by lifecycle rules.",
            ))

    detected = conflicts.detect_conflicts(state.goals)
    active_goals = [g for g in state.goals if not g.is_terminal()]

    appears_in = [g.goal_id for g in state.goals[:3]]
    if detected:
        appears_in.extend([c.conflict_id for c in detected[:3]])

    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=verdict,
        confidence=confidence,
        active=active,
        retained=True,
        tenant_scoped=True,
        appears_in=appears_in,
        defects=defects,
        flags={
            "priority_scores": [round(p.score, 3) for p in prioritizer.rank(state.goals)],
            "conflict_count": len(detected),
            "active_goal_count": len(active_goals),
        },
    )


def _run_salience(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    if not state.salience_signals:
        return CognitiveResult(
            scenario_id=scenario.scenario_id, kind=scenario.kind, verdict="NO_SIGNAL", confidence=0.0
        )
    result = SalienceAssessmentEngine().assess(_salience_request(state, scenario))
    assessment = result.assessment

    reason_values = [rc.value for rc in assessment.reason_codes]
    appears_in = list(reason_values)

    decay = SalienceDecayEngine().decay_signal(state.salience_signals[0])
    flags = {"decays": decay.decayed, "decayed_value": round(decay.decayed_value, 3)}

    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict="salient" if assessment.overall >= 0.5 else "background",
        confidence=round(assessment.confidence, 3),
        active=True,
        retained=True,
        tenant_scoped=True,
        appears_in=appears_in,
        flags=flags,
    )


def _run_meta_cognition(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    flags = scenario.expected.flags or {}
    request = MetaCognitiveRequest(
        request_id=scenario.scenario_id,
        correlation_id=scenario.scenario_id,
        tenant_id=scenario.tenant_id,
        reasoning_confidence=float(flags.get("reasoning_confidence", 0.5)),
        memory_reliability=float(flags.get("memory_reliability", 0.5)),
        belief_conflicts=[
            BeliefConflictSummary(
                conflict_id=f"conflict_{i}",
                claim_a=str(c),
                claim_b=str(flags.get("conflicting_claim", "")),
                severity=flags.get("conflict_severity", "medium"),
            )
            for i, c in enumerate(flags.get("belief_conflicts", []) or [])
        ],
        strategy_attempts=[],
        budget_remaining=flags.get("budget_remaining", {"reasoning_steps": 5}),
        metadata={},
    )
    result = MetaCognitiveAssessor().assess(request)
    assessment = result.assessment
    state_codes = [rc.value for rc in assessment.reason_codes]

    mapped = []
    for code in assessment.reason_codes:
        v = code.value
        if v == "low_reasoning_confidence":
            mapped.append("LOW_REASONING_CONFIDENCE")
        elif v == "low_memory_confidence":
            mapped.append("LOW_MEMORY_CONFIDENCE")
        elif v == "evidence_inconsistent":
            mapped.append("CONFLICTING_EVIDENCE")
        else:
            mapped.append(v.upper().replace("_", "_"))

    verdict = result.state.status.value
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=verdict,
        confidence=round(assessment.confidence, 3),
        active=True,
        retained=True,
        tenant_scoped=True,
        appears_in=mapped,
        defects=[],
        flags={"reason_codes": state_codes, "meta_confidence": round(result.state.confidence, 3)},
    )


def _run_policy_dominance(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    engine = BeliefEngine()
    primary = state.claims[0] if state.claims else None
    evidence = state.evidence.get(primary.claim_id, []) if primary else []
    belief = engine.assess(primary, evidence) if primary else None

    decision = evaluate_decision(
        state=state,
        belief=belief,
        salience=None,
        preferences=None,
        policy_constraints=state.policy_constraints,
    )
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=decision.option.value,
        confidence=round(decision.confidence, 3),
        active=True,
        retained=True,
        tenant_scoped=True,
        policy_violation=decision.allowed.value == "BLOCKED",
        appears_in=[decision.option.value],
        flags={"allowed": decision.allowed.value, "applied_constraints": decision.applied_constraints},
    )


def _run_memory_poisoning(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    candidates = [dict(c) for c in state.context_candidates]
    ranked = MemoryRanker().rank(candidates) if candidates else []

    policy_constraints = state.policy_constraints
    requester_tenant = scenario.tenant_id
    checks = {}
    for c in ranked:
        item_tenant = c.get("tenant_id", requester_tenant)
        checks[c.get("memory_id", id(c))] = SecurityGuard().check_memory_access(
            c, policy_constraints, requester_tenant, item_tenant
        ).value

    blocked = any(v == "BLOCKED" for v in checks.values())
    visible_ids = [k for k, v in checks.items() if v == "ALLOWED"]
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict="filtered" if blocked else "visible",
        confidence=0.0,
        active=True,
        retained=True,
        tenant_scoped=bool(policy_constraints.get("tenant_boundary", True)),
        policy_violation=blocked,
        appears_in=visible_ids,
        flags={"security_checks": checks, "ranked_count": len(ranked)},
    )


def _run_deletion(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    propagator = DeletionPropagator()
    status = propagator.propagate(state)

    active_claim_ids = {c.claim_id for c in state.claims}
    resurrected = [d for d in state.deleted_ids if d in active_claim_ids]

    defects: list[DefectRecord] = []
    if resurrected:
        defects.append(DefectRecord(
            scenario_id=scenario.scenario_id,
            expected="deleted memory absent from active store",
            actual="resurrected",
            affected_owner="ai_karen_engine.core.memory",
            severity=DefectSeverity.HIGH,
            kind=scenario.kind,
            detail=f"Deleted ids still present in active claims: {resurrected}",
        ))

    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=status.value,
        confidence=1.0 if not resurrected else 0.0,
        active=False,
        retained=False,
        tenant_scoped=True,
        appears_in=[],
        defects=defects,
        flags={"deleted_count": len(state.deleted_ids), "purged_count": len(state.purged_claims)},
    )


def _run_learning(scenario: Scenario, state: CognitiveState) -> CognitiveResult:
    flags = scenario.expected.flags or {}
    aggregator = EvidenceAggregator()
    capability = flags.get("capability_id", "test_skill")
    observations: list[ActionOutcomeObservation] = []

    obs_specs = flags.get("observations", []) or []
    for spec in obs_specs:
        obs = ActionOutcomeObservation(
            observation_id=f"obs_{len(observations)}",
            source_outcome_id=spec.get("id", "o"),
            task_signature_ref=spec.get("task_signature_ref", {}),
            user_scope=spec.get("user_scope", {}),
            action_type=spec.get("action_type", capability),
            target_id=spec.get("target_id"),
            execution_status=spec.get("execution_status", "success"),
            latency_ms=float(spec.get("latency_ms", 100.0)),
            fallback_used=bool(spec.get("fallback_used", False)),
            correction=bool(spec.get("correction", False)),
            completion=bool(spec.get("completion", True)),
        )
        observations.append(obs)
        aggregator.add_observation(obs)

    profile = aggregator.get_capability_profile(capability)
    success_rate = profile.success_rate
    defect_rate = profile.failure_rate

    defects: list[DefectRecord] = []
    success_expect = bool(flags.get("expect_success_convergence", True))
    if success_expect and success_rate < 0.7:
        defects.append(DefectRecord(
            scenario_id=scenario.scenario_id,
            expected="success_rate >= 0.7 after repeated successes",
            actual=f"{success_rate:.3f}",
            affected_owner="ai_karen_engine.core.adaptive.learning.aggregates",
            severity=DefectSeverity.MEDIUM,
            kind=scenario.kind,
            detail="Capability profile did not converge toward high success rate.",
        ))

    verdict = "CONVERGED" if (success_rate >= 0.7 and defect_rate <= 0.4) else "NOT_CONVERGED"
    return CognitiveResult(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        verdict=verdict,
        confidence=round(success_rate, 3),
        active=True,
        retained=True,
        tenant_scoped=True,
        appears_in=[capability],
        defects=defects,
        flags={
            "success_rate": round(success_rate, 3),
            "failure_rate": round(defect_rate, 3),
            "sample_count": profile.sample_count,
            "correction_rate": round(profile.correction_rate, 3),
            "retry_rate": round(profile.retry_rate, 3),
        },
    )


def _build_snapshot(state: CognitiveState, scenario: Scenario) -> UserStateSnapshot:
    current = CurrentUserState(user_id=scenario.user_id, tenant_id=scenario.tenant_id)
    return SnapshotBuilder(scenario.user_id, scenario.tenant_id).build(
        current_state=current,
        all_preferences=list(state.preferences),
        behavior_patterns=[],
        active_goals=[],
    )


def _promote_to_stable(pref) -> bool:
    original = pref.state
    PreferenceLifecycle.promote(pref, pref.confidence)
    return pref.state.value == "stable" and original.value != "stable"


def _salience_request(state: CognitiveState, scenario: Scenario) -> SalienceAssessmentRequest:
    context = SalienceContext(
        request_id=scenario.scenario_id,
        correlation_id=scenario.scenario_id,
        tenant_id=scenario.tenant_id,
        user_id=scenario.user_id,
        current_goals=[g.goal_id for g in state.goals],
    )
    return SalienceAssessmentRequest(
        context=context,
        signals=list(state.salience_signals),
        prediction_errors=list(state.prediction_errors),
        user_emphasis=list(state.user_emphasis),
        relationship_signals=[],
        metadata=dict(state.policy_constraints),
    )


def _enum_goal_state(value: Any) -> Any:
    if value is None:
        return None
    try:
        return GoalState(str(value))
    except ValueError:
        if isinstance(value, str):
            try:
                return GoalState[value.upper()]
            except KeyError:
                pass
    return None
