# KCOG Cognitive and Learning Contracts

> Logical contract specification. Map onto existing typed contracts before implementing new classes, tables, registries or endpoints.

## CognitiveState: one request-scoped, immutable evidence view

Reuse `core/cognitive/state.py::CognitiveState`. Maintain authenticated `tenant_id`, `user_id`, `session_id`, `conversation_id`, `request_id`, `correlation_id`, schema/policy version, verified source refs, status and age. Use existing `BeliefSnapshot`, `ContextSnapshot`, `ReasoningSnapshot`, `MetaSnapshot`, `PolicySnapshot` and goal contracts. Avoid dumping raw private text into structured telemetry.

New fields only after proving a missing data semantic; prefer a versioned projection/extension of the current model over duplicating a state container.

### CognitiveDecision (logical additions)

- `decision_id`, `state_id`, `intent`, `policy_decision_id`, `eligible_actions` and a `reason_code`.
- `effort_tier` (direct/verify/deliberate/graph), `verification_requirement`, budget, expected value of evidence/compute.
- `epistemic_status` (supported / uncertain / conflicted / unidentifiable / unavailable).
- `evidence_refs`, `assumption_refs`, `model_version`, `policy_version` and `evaluation_version`.
- All execution authorization still comes from RuntimePolicy. CORTEX recommends, ChatRuntime executes.

### SituationTransitionPrediction (future KCOG-02)

- observed `state_ref` and `state_version`, proposed `authorized_action_ref`, explicit predicted effects and horizon.
- prediction `prediction_kind` (deterministic contract / statistical forecast / causal intervention / hypothetical).
- support `supporting_evidence_refs`, `assumptions`, `identifiability_status`, uncertainty kind and calibration record.
- reconciliation references actual post-action observations and discrepancies; stale revision cannot mutate the projection.
- graph facts are memory-governed evidence; predictive hypotheses are not persisted as verified user facts.

### LearningObservation (reuse durable runtime lineage)

Use `TrajectoryStore` feature snapshots, decision observations, and `OutcomeStore` outcomes. Every observation has actor/tenant scope, chosen eligible action, exact model/policy version, authentic outcome source, label verification status, sample independence and idempotency.

Separate **operational outcome** (tool/process succeeded) from **task outcome** (independent correctness) and **personal preference** (explicit user declaration). A generic thumbs-up alone is weak feedback, not a globally reusable label.

### CompetencyEvidence (future KCOG-04)

Logical references: persona ID, task family, allowed skills, model/adapter version, dataset/evaluator hashes, held-out metrics, evaluation sample size, regressions, approval status, revocation lineage, known limitations. Persona defines identity/purpose; shared competency model is owned by Intelligence and training/evaluation authority. Persona does not grant model/tool access.

## Multiscale update cadences

| Cadence | May evolve | Proof and control |
| --- | --- | --- |
| Turn-time | working context, attention, verification plan | bounded, transient, RuntimePolicy-checked |
| Session-time | explicit user corrections and task-state proposals | authenticated provenance; persist only through governed owner |
| Offline periodic | contextual ranking, retrieval policies, procedural candidates | immutable evaluation corpus, independent labels, shadow |
| Model lifecycle | adapters, trainable model versions | immutable dataset/job/artifact, held-out retention, review, registry approval |

A single conversation correction must not update globally deployed weights. Training source authorization and retrieval authorization are separate permissions.

## Learning evidence and safety laws

1. No unauthorized tenant/user/persona transfer or training-data reuse.
2. A prediction is not a fact; hypothesis is not causality; success is not correctness.
3. Unknown results and persistence failures are explicit, never represented as zero or success.
4. Every learned behavior is attributable to a versioned approved policy.
5. Model changes cannot bypass provider registry or central fallback configuration.
6. Training revocation can retire affected models; do not promise exact machine unlearning.
7. Versioned prompt assembly remains under the prompt/runtime authority.
8. `CORTEX` decides, `ChatRuntime` executes, `RuntimePolicy` authorizes.
