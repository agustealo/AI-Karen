# 11 | Evaluation, benchmarks and regression gates

[← Index](README.md) · [Previous](10-governance-security.md) · [Next →](12-operations-ui.md)

## 1. Baselines before adding a model

Compare (A) existing Karen prompt/retrieval/runtime, (B) derived KCM self-model without training, (C) KCM + prompt/skill memory, (D) KCM + LoRA/SFT candidate. Include alternate authorized small/medium model baselines when the task warrants. If D is not better under equal budgets, keep it disabled.

## 2. Evaluation layers

| Layer | Representative tests | Independent oracle |
|---|---|---|
| Admission policy | Consent, no-training flags, poisoned provenance, expired sources | Deterministic policy outcome |
| Data correctness | Label accuracy, source independence, contradiction | Verified test/tool evidence or reviewer |
| Dataset health | Duplicates, group leakage, coverage, class balance, rights | Manifest validator + curated audit |
| Skill performance | Verified execution, exact task acceptance, generalization | Deterministic tests and real controlled environments |
| Persona fidelity | Style alignment without correctness loss | Human rubric + model judge cross-check where appropriate |
| Calibrated uncertainty | Abstention, false confidence, out-of-distribution tasks | Ground truth with reliability curves |
| Memory/KCM validity | Correct projection, stale source, unknown vs false | Source-specific governed projection |
| Security/privacy | Injection, leakage, exfiltration, RBAC, membership inference probes | Independent security tests |
| Operations | p50/p95/p99, CPU/RAM/GPU, concurrency, cancellation, restart | Runtime traces and hardware measurements |
| Continual stability | Old skills retained after new adapters | Frozen historical benchmark |
| Erasure/remediation | Revoked source ancestry and checkpoint fencing | Lineage query + deployment verification |

## 3. Frozen golden sets

Maintain independent suites for: persona consistency; fact grounding; instructions; task success; refusal and policy; calibration and abstention; long-horizon work (where certified); memory staleness; prompt injection; multilingual behavior if supported; all critical plugin/tool paths. Keep the test set hidden from training pipelines, teacher-model synthesis and clustering labels derived from training.

Use at least three temporal windows: historical frozen benchmark, recent pre-cutoff development examples, and genuinely future/post-cutoff holdout after deployment. Split by conversation/task/document/duplicate family rather than by row.

## 4. Promotion thresholds

No universal "accuracy >= X" gate. Each capability must declare acceptable risk and a preregistered scorecard. Suggested initial review requirements:

- **Correctness:** statistically supported noninferiority on required tasks vs strongest comparable baseline.
- **Target benefit:** predefined measurable improvement (task success, cost per *correct* result, p95 latency or Persona consistency).
- **Safety:** zero critical policy/RBAC/tenant breaches in mandatory security suite; no material regression.
- **Calibration:** meaningful abstention on unknown inputs; measured ECE/Brier or selective risk as appropriate.
- **Retention:** no unacceptable decline in prior approved skills when adapting.
- **Efficiency:** net cost includes training, inference, routing, verification and recovery; evaluate CPU/RAM/GPU constraints.
- **Reproducibility:** training and test manifests, model revision, seeds, config digests, test runner versions and approved receipts captured.

Use bootstrap confidence intervals across independent task groups rather than treating thousands of near-duplicate rows as independent measurements. For rare critical risks, use scenario-based guarantees and red-team reviews; absence of a failure in a small sample is not proof of zero risk.

## 5. Shadow and canary strategy

1. **Offline evaluation:** no user-facing deployment. Build scorecard and archive immutable outcome evidence.
2. **Shadow:** candidate produces outputs in isolation; compare without using shadow output in production or self-training.
3. **Canary:** strictly limited authorized task classes, user group and tenant, with immediate disable feature flag.
4. **Promote:** only when measured error, cost, latency, privacy and stability gates hold.
5. **Rollback:** automatic on verified critical safety/tenancy/policy violations; manual for disputed quality changes; preserve audit.

A success claim needs an actual production inference receipt. Model downloaded/registered is not equivalent to model ready/healthy/selected.

## 6. Experiment matrix

| Experiment | What it falsifies |
|---|---|
| Memory retrieval vs trained adapter | "We need weights for these facts" |
| Random vs quality-ranked vs coverage-first | "Top-scored examples always work best" |
| 100/500/1,000/5,000 clean examples | "More data always helps" |
| Task-only vs Persona-only vs mixed adapters | "One model can learn every objective without interference" |
| New adapter with vs without replay | "Continual training never forgets" |
| SLM vs current LLM on narrow skills | "Smaller is automatically faster and just as good" |
| Repeated false statements vs independent confirmations | "Usage frequency implies truth" |
| Revocation before/after training | "Deleting source bytes is enough" |

Record hypothesis, baseline, dataset/model hashes, sample groups, results, uncertainty, signed reviewer decision and conclusion (promote/reject/inconclusive). Publish negative results internally as legitimate evidence.

## 7. Proof commands and tests

Existing project baseline:

```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
npm run lint && npm run typecheck && npm run test && npm run build
docker compose config
```

Test commands depend on installed project scripts and environment; don't claim a pass unless executed. Add focused suites along canonical owners: `tests/.../memory/`, `tests/.../echocore/`, learning/dataset worker, model lifecycle, RLS/SQL integration, UI contract and end-to-end canary. Gate PR merges on **exact-head** checks and runtime integration evidence, not green status from a different commit.

## 8. Research context

[2026 domain-dataset survey](https://link.springer.com/article/10.1007/s44443-026-01150-2) recommends evaluating intrinsic quality, dataset distribution, model-aware value and actual outcome utility separately. [MLflow evaluation datasets](https://mlflow.org/docs/latest/genai/concepts/evaluation-datasets/) provide a useful optional design reference for lineage and golden sets; don't introduce MLflow as a mandatory duplicate system unless current infrastructure lacks required capabilities.
