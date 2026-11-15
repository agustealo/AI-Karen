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
| 2026-11-15 | KCOG-00A initial safety guard | PR #864; `de689975a1fb661bb92df5fd1bbf4cdc6b0e5d25` | Cognitive Proof + Reasoning Smoke green at initial inspection; remaining CI and runtime proof pending | IMPLEMENTING / NOT MERGED |

Do not overwrite evidence when an earlier claim is corrected. Add a dated reconciliation entry with links and reason.
