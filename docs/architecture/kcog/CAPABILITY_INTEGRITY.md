# Cognitive Capability Integrity Register

> **Scope:** first-pass source audit, 2026-11-15, baseline `272e23c4b5879771294e46c2d205e3b6f3909050`.
> **Proof status:** STATIC SOURCE REVIEW ONLY. No performance, production invocation or import/CI pass is inferred.
> **Status vocabulary:** VERIFIED_SOURCE / UNVERIFIED_RUNTIME / QUARANTINE_REQUIRED / ADVISORY_ONLY / EVALUATED / APPROVED. These are evidence states, not marketing labels.

| ID | Capability/implementation | Observed source behavior | Integrity risk | Next verification and disposition |
| --- | --- | --- | --- | --- |
| CI-001 | `core/reasoning/causal/engine.py:learn_from_observations` | strong correlation + `_determine_direction` can add causal edge; fallback direction `True` | CRITICAL if relied upon | find callers, reject unsupported causal claims, test insufficient evidence |
| CI-002 | `engine.py:estimate_causal_effect` | treatment-control mean difference; missing group returns `0.0` | HIGH | no identified effect without assumptions and actual confounder adjustment; distinguish unknown vs true zero |
| CI-003 | `engine.py:generate_counterfactual` | fixed probability 0.5, downstream strength heuristic | HIGH | segregate hypothetical scenario from calibrated prediction; do not assert probability |
| CI-004 | `core/reasoning/meta/calibration.py` | process-local history, correction-flag accuracy | HIGH | use verified labelled outcomes and proper calibration metrics; preserve accuracy for its defined use only |
| CI-005 | `core/adaptive/learning/experience/attribution.py` | fixed numerical weights and uncertainty | HIGH | mark unknown/unidentifiable unless attributable via validated design |
| CI-006 | `core/intelligence/ml/online_learning.py` | process-local bounded collector | MODERATE | use `durable_outcomes.py` + scoped `OutcomeStore` for production comparisons |
| CI-007 | `core/adaptive/learning/reflector.py` | candidate reflection from experiences, no direct persistence | MODERATE | verify cross-task held-out transfer and memory promotion boundaries |
| CI-008 | `core/memory/neuro/lesson_memory.py`, `procedural_memory.py` | process-local dictionaries | MODERATE | audit consumers; route durable lessons through existing governed memory owner |
| CI-009 | `core/cognitive/state.py` | typed envelope with scope, belief/goals/meta | INTEGRATION UNKNOWN | verify real runtime use, completeness, cancellation/tenant provenance |
| CI-010 | `core/intelligence/ml/training/transformer_executor.py` | local governed text LoRA executor | CAPABILITY LIMITED | require actual worker/adapter proof; never call this image-generation expertise |

## Remediation status and new reachability finding

- **CI-001 guarded:** #864 merged with all exact-head gates passing. Correlational data no longer auto-adds causal graph edges; existing edges remain unvalidated until provenance is established.
- **CI-002 and CI-003 containment merged:** #868 merged as `afa845187151715692ca15a75b93871c7403351f` after all exact-head checks passed. `CausalIdentificationError` rejects unidentified effects and counterfactuals. It does **not** implement an estimator.
- **CI-004 and CI-005 containment merged:** #869 merged as `fd0d2e408e7c2c6cd82bdc1015ea4c030dbf3ea3` after all exact-head checks passed. Missing calibration targets and unidentifiable outcome contributions now have explicit unknown semantics; verified calibration still requires durable independent labels.
- **CI-011 merged:** #871 on `main@92ab8a45babc3b271447b3874a10feac99df3085` after all exact-head gates passed; default causal strategy explicitly abstains, no fake completed inference. Real-model causal inference remains unimplemented.
- **CI-012 in progress:** #875 projects existing `CognitiveState` after final policy and requests verification for policy-authorized, same-user/tenant, source-reported conflicting context. `MetaCognitiveAssessor` is not yet integrated because existing numeric confidence inputs lack verified calibration; no measured improvement claimed. Source owner remains CORTEX Stage 2 and RuntimePolicy.
- **CI-013 recorded:** ChatRuntime suppresses reasoning when explicit preferred provider and model are both set (non-stream and stream), potentially negating verification. KCON-211 owns correction and exact route/receipt proof. Until that gate is repaired, KCOG-01A1 cannot claim all-user execution parity.
- **Important:** exact-head passing checks do not prove that production cognitive reasoning invokes these paths, nor that a validated causal model exists. Do not conflate release-safety containment with intelligence evaluation.

## No misleading probability, causality, or competence claims

**Association:** may express correlation and sample/segment limits; cannot produce a directed causal edge without validated identifying assumptions or an independently established causal mechanism.

**Temporal order:** a necessary ingredient in many causal hypotheses, not proof of causality.

**Intervention:** must identify variables, assumptions, target population, estimand, adjustment strategy, uncertainty, and whether the effect is identifiable. An illustrative scenario must say so.

**Calibration:** requires ground truth, recorded prediction probabilities, sufficient samples, proper scoring, versioned corpus and reliability breakdown. A numeric model confidence is not automatically a calibrated probability.

**Attribution:** do not return manufactured numeric causal contributions. Use `unknown`, observational association, or a separately identified causal estimate with assumptions.

**Competence:** a persona name, access to documents, completed training job, successful tool invocation or a persuasive answer does not prove proficiency.

## Audit protocol and risk response

For every row:
- Identify all source consumers and reachable runtime paths at the exact main SHA.
- Create reproducing tests for source-level defect, including nonidentifiable/empty cases.
- Determine whether the component is active, misplaced, compatibility-only, experimental, or dead.
- If it is dangerous and reachable, guard/disable first; preserve security conditions; no silent fallbacks.
- If replaced, document replacement path, references audited, tests, and deletion risk.
- Record objective benchmark and observed CI evidence in [decisions ledger](DECISIONS_AND_EVIDENCE.md).

No unverified claim is marked fixed because a guard exists in a unit-test-only path.
