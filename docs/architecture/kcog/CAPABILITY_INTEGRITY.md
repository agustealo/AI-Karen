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
