# 05 | Quality matrix, selection and learning utility

[← Index](README.md) · [Previous](04-admission-policy.md) · [Next →](06-contracts-and-lineage.md)

## 1. Design: gate -> score -> select -> train -> measure

A single blended score is **not** truth. The score ranks *eligible* examples within a specific objective; it must never serve as evidence of permission or correctness. Use separate:

- **Evidence soundness:** source provenance, label correctness, temporal/contradiction status.
- **Learning utility:** relevance to a named skill, underrepresented capability, or demonstrated failure.
- **Dataset utility:** coverage, balance, diversity, redundancy, leakage and generalization.
- **Actual training utility:** counterfactual measured improvement over frozen baselines.

## 2. Proposed v0.1 candidate matrix

| Dimension | Initial weight | Measurements |
|---|---:|---|
| Verified label correctness | 30% | External test receipt, approved reviewer, executable proof, calibrated source reliability |
| Outcome evidence | 20% | Verified task success/failure, invariant checks, reproducible procedure |
| Objective relevance | 20% | Declared skill taxonomy fit, specific weakness/coverage target |
| Provenance quality | 15% | Complete chain, trust class, source independence, verification age |
| Instruction-target clarity | 10% | Unambiguous user/task input, target output, valid format |
| Novelty and coverage | 5% | Distinct semantic cluster, rare task type, not redundant |

**Proposed score:** `quality_v0_1 = .30*correctness + .20*outcome + .20*relevance + .15*provenance + .10*clarity + .05*novelty`, where each field is a validated `[0, 1]` value. Store individual scores, evidence, assessor IDs and scorer version; do not store only the aggregate. Weights are starting hypotheses, **not research-proven optimal constants**.

### Critical correction

For **knowledge/factual accuracy** objectives, a correctness minimum should be a hard gate, not merely 30% of an additive score. For **Persona style** training, the label may be a reviewed style exemplar; objective-specific evaluators replace generic factual metrics. An `unverified` source cannot pass by being excellent in every other dimension.

## 3. Frequency and use

- **Access count** increases *confidence in relevance* at most, not truth, source independence or label correctness.
- **Verified repeat success** can improve outcome evidence only across genuinely independent executions/conditions.
- **Repeated failed attempts** increase *learning priority for correction*, never the quality of the failed target.
- Count **unique independent sources** rather than repetitions of one underlying claim.
- Limit one conversation, task trajectory, or synthetic template to its allowed weight; prevent self-reinforcing feedback loops.

## 4. Novelty and coverage

**Do not simply take the top-N scored rows.** Use grouped/clustered selection over task signatures, persona styles, error classes, modalities, risks and time windows. Deduplicate exact hashes and near-duplicates; cap per-source and per-user contribution; preserve balanced high-value long-tail cases. Construct a representative **random/stratified baseline** for comparison.

Research: [Pandia et al., Nov 2026](https://arxiv.org/abs/2611.07323) found coverage more predictive than naive difficulty scores in studied fine-tuning setups. [Wu et al., EMNLP 2026](https://aclanthology.org/2026.emnlp-main.1877/) show that recipe operations (filtering, mixing and dedup) matter beyond per-row rank. [Zhang et al., ACL 2026](https://aclanthology.org/2026.acl-short.49/) demonstrate skill-aware sample selection in a particular reasoning-distillation setting. These are research-supported design directions, **not guaranteed improvements on Karen**.

## 5. Selection recipe (versioned and reproducible)

1. Freeze training objective, evaluator rubric, tenant/purpose scope and data cutoff.
2. Apply security/consent/deletion hard gates.
3. Verify content-target validity and evidence source independence.
4. Deduplicate by exact content fingerprint and grouped semantic family.
5. Score eligibility and objective-specific learning value.
6. Cluster tasks and allocate coverage quotas; include long-tail and documented failure categories.
7. Allocate train/dev/test by leakage group; lock test before exploration.
8. Materialize and hash a deterministic dataset manifest.
9. Compare quality-ranked, random, diversity-first and skill-gap-weighted recipes under identical budgets.
10. Select recipe only if frozen, externally verified evaluation improves and safety/forgetting do not regress.

## 6. No deceptive score thresholds

Proposed preliminary review bands **only for design experiments**:

- `<0.65`: require manual review or reject depending on objective.
- `0.65–0.84`: approved candidate possible with all gates and verified label; evaluate coverage contribution.
- `>=0.85`: high-ranked candidate, still conditional on dataset composition and independence.

Do **not** configure those numeric bands as production defaults until scored examples have been calibrated to actual training gains and error rates. The true admission rule may be per-task categorical with no scalar threshold at all.

## 7. Anti-gaming

Test popular-but-false claims; duplicated errors; mislabeled positive outcomes; wrong tenant; synthetic generation loops; rating feedback from a compromised source; rare but crucial safety examples. Track how often high score candidates fail independent adjudication; if elevated, freeze model training and investigate scorer drift.
