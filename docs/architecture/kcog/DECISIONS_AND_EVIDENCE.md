# KCOG Architecture Decision and Evidence Ledger

> Source of truth for decisions, deviations, and reproducible proof within this sprint. Evidence must always name exact SHA and artifact.

| ID | Decision / observation | Basis | State |
| --- | --- | --- | --- |
| AD-001 | Keep CORTEX decision-only and ChatRuntime execution-authoritative | current architecture and developer authority | ACCEPTED |
| AD-002 | Reuse typed `CognitiveState`; no second cognitive executive | `core/cognitive/state.py`, `core/runtime/decision_pipeline.py` | ACCEPTED |
| AD-003 | Reuse durable OutcomeStore + TrajectoryStore for training/evaluation evidence | existing RLS-scoped stores | ACCEPTED |
| AD-004 | Reject heuristic causal confidence as identified causal truth | observed `causal/engine.py` defaults | ACCEPTED |
| AD-005 | Real data-use authorization differs from retrieval authorization | memory, training and tenant governance | ACCEPTED |
| AD-006 | Retain separate baseline and candidate evaluation with held-out/retention tests | continual learning risk | ACCEPTED |
| OBS-001 | `_determine_direction` defaults to `True` on missing temporal evidence | static source inspection at `272e23c4b5879771294e46c2d205e3b6f3909050` | SOURCE_CONFIRMED, runtime reachability UNVERIFIED |
| OBS-002 | `CalibrationTracker` computes correction-based fraction from local list | static source inspection | SOURCE_CONFIRMED, runtime reachability UNVERIFIED |
| OBS-003 | `AttributionEngine` uses numeric fixed contribution values | static source inspection | SOURCE_CONFIRMED, runtime reachability UNVERIFIED |
| OBS-004 | existing `TransformerLoRAExecutor` is text JSONL-focused | static source inspection | SOURCE_CONFIRMED, multimodal expertise UNPROVEN |

## Open architecture questions

- Which causal-engine functions are reachable in the active user-facing chat path and which remain experimental? Need import/call/feature-flag audit.
- Which verified label sources can support metacognitive calibration without introducing non-consensual personal training?
- Which existing cognitive state fields are actually consumed by CORTEX stage two?
- Which evaluation corpus and user-visible acceptance environment are reproducible with the present registered local model?
- What thresholds and sample sizes should a governance owner pre-register for each task family rather than use arbitrary global values?

## Sprint evidence log

| Date | Task | SHA / PR | Evidence | Status |
| --- | --- | --- | --- | --- |
| 2026-11-15 | KCOG wiki foundation | PR #863; main `c18b3dfe3376a02e1c5de51e0195b9be7e0af182` | Main Quality green at wiki exact head; GitHub merge reported success | MERGED; postmerge proof separate |
| 2026-11-15 | KCOG-00A initial safety guard | PR #864; merged `2d8b0171b9f37f4eb1e2b32290b51d3ec36c916d` | All exact-head CI green including Cognitive Proof, Main Quality, Reasoning Smoke, Production First-Boot | MERGED, cognitive runtime acceptance still separate |

| 2026-11-15 | KCOG S1 continuity checkpoint | PR #866; merged `724edec8ec12425bc193510270e6bdbb04677f30` | Exact-head and post-merge Main Quality green at inspection | MERGED |
| 2026-11-15 | KCOG-00A2 causal identification containment | PR #868; merged `afa845187151715692ca15a75b93871c7403351f` | All exact-head CI green incl. first-boot | MERGED, future estimator still unimplemented |
| 2026-11-15 | KCOG-00B1 calibration and attribution truth | PR #869; merged `fd0d2e408e7c2c6cd82bdc1015ea4c030dbf3ea3` | All exact-head CI green incl. first-boot | MERGED, validated calibration still unimplemented |

| 2026-11-15 | KCOG-00A3 causal strategy wiring | PR #871; head `b05942395f328533dc3990cb6a24bc1d0535950a` | Exact-head Cognitive Proof, Reasoning Smoke and Main Quality green; first-boot pending at checkpoint | OPEN, not merged |
| 2026-11-15 | KCOG-01A state integration source review | main `fd0d2e408e7c2c6cd82bdc1015ea4c030dbf3ea3` | `CognitiveState` and `MetaCognitiveAssessor` not referenced directly in inspected decision_pipeline, ChatRuntime and CORTEX executive; `ContextSnapshot` already referenced in context contracts | SOURCE-LEVEL GAP, integration not claimed |

**Non-closure:** these safety slices do not implement causal identification, independently verified calibration or cross-domain transfer. A future real-model runtime trial is still required.

Do not overwrite evidence when an earlier claim is corrected. Add a dated reconciliation entry with links and reason.
