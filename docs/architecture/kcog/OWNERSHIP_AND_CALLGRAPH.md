# KCOG Canonical Authority and Code Map

> Source-derived snapshot: `272e23c4b5879771294e46c2d205e3b6f3909050`. Confirm paths and call sites on current main before editing.

## Owner map

| Responsibility | Canonical owner | Source starting points | Forbidden duplication |
| --- | --- | --- | --- |
| Auth, request ingress, tenant/session | thin API auth/ingress | `core/runtime/chat_runtime.py`, `api_routes/chat/` | route-level model/cognitive planning |
| Cognitive interpretation, decision and eligibility | Intelligence + CORTEX | `core/intelligence/intelligence_runtime.py`; `core/cortex/executive.py` | CORTEX tool/model execution |
| Execution, planning invocation, telemetry | ChatRuntime | `core/runtime/chat_runtime.py`; `core/runtime/decision_pipeline.py` | persona-owned runtime, secondary orchestrator |
| Policy authorization | RuntimePolicy | `core/runtime/policy/` | UI or unverified model decisions |
| Cognitive envelope | `core/cognitive/state.py` | `CognitiveState`, `MetaSnapshot`, `BeliefSnapshot` | new ad-hoc global state |
| Metacognitive assessments | `core/reasoning/meta/` | `assessment.py`, `calibration.py`, `contracts.py` | self-rated confidence as verified calibration |
| Causal hypotheses | `core/reasoning/causal/` | `engine.py`, `cognitive_causal.py` | correlations cast into causes |
| Episodic/profile/semantic memory | Memory / NeuroVault | `core/memory/`, `core/runtime/evidence_resolver.py` | per-persona extra truth store |
| Experience/strategy learning | `core/adaptive/learning/` | `experience/`, `reflector.py`, `offline_evaluation.py` | duplicated reward and promotion authority |
| Model ML inference/training | `core/intelligence/ml/` | `ml_runtime.py`, `registry.py`, `training/` | model selection in a route or UI |
| Durable outcome and trajectory | Runtime stores | `core/runtime/outcome/store.py`, `core/runtime/trajectory/store.py` | shadow production ledger |
| Persona identity/settings | PersonaService | `docs/architecture/KPERSONA_FIRST_CLASS_IMPLEMENTATION.md` | persona grants provider or tool permissions |

## Canonical request and learning paths

```text
Auth/tenant context -> ChatRuntime -> CORTEX Stage 1
 -> RuntimePolicy authorizes -> RuntimeEvidenceResolver (Memory/Conversation/Goals)
 -> CORTEX Stage 2 decision -> ChatRuntime plan and execution
 -> governed tools / registered provider / explicit graph workflow
 -> TrajectoryStore + OutcomeStore + transcript/memory owners
 -> authorized evaluation/learning projection (offline, shadow)
 -> independent model/policy promotion (if approved)
```

No learned policy may bypass RuntimePolicy. Training does not authorize execution. Runtime model/provider fallback stays centrally configured, and the actual provider/model must appear in result metadata. Existing ML operational signals are advisory; explicitly requested models and security restrictions retain precedence.

## Search-before-add checklist

1. Find the current caller and owner; validate real imports and runtime composition.
2. Look for older and stronger implementations under `core/intelligence/ml`, `core/adaptive`, `core/reasoning`, `core/memory`, `core/cortex`.
3. Inspect tests/docs/config/UI/migrations before moving or deleting code.
4. Preserve existing tenant, user, session, consent, audit, lifecycle and cancellation fencing.
5. When converging duplicates, first move behavior to the strongest owner, update callers/tests, then delete old code only after a reference audit.
6. Surface honest degradation, never a synthetic model response or saved result.

## Source-critical hazards (inspect before activating)

- `CausalReasoningEngine._determine_direction`: defaults to `True` with no temporal evidence; observational correlations create causal graph edges.
- `estimate_causal_effect`: fallback of `0.0` where groups are missing; no verified identification or actual adjustment despite the parameter.
- `generate_counterfactual`: fixed probability placeholder.
- `CalibrationTracker`: process-local observations and accuracy based on a correction flag.
- `AttributionEngine`: fixed numerical weights.
- `MLOutcomeCollector`: process-local observations, though governed durable evidence projection exists separately.
- `LessonMemoryStore` and `ProceduralMemoryStore`: process-local dictionaries; must not be treated as proven durable truth.

These are **source observations, not proof that the code is invoked on the production chat path**. Determine actual call sites before remediation.
