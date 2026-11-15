# KCOG Evaluation Matrix and CI Gates

> This document specifies **required proof**, not completed evidence.

## Baseline/evaluation discipline

Freeze a commit, model identifiers, runtime config, permitted tools, evaluation code, data snapshot and resource budget before comparing candidates. Use train/validation/held-out splits grouped by user/project/task family where appropriate. No overlapping paraphrases, previous answer templates, or hidden held-out feedback in training. Blind human review for subjective results. Report confidence intervals and sample counts; do not turn statistically uncertain differences into promotion.

### Benchmark dimensions

| Capability | Objective evaluation | Failure test |
| --- | --- | --- |
| Causal inference | known synthetic DAGs + real intervention datasets with justified assumptions | correlated unrelated variables, hidden confounders, collider bias, nonidentifiability |
| Metacognition | probability calibration (Brier, ECE), selective risk, verification value | confident hallucination, empty labels, out-of-distribution shifts |
| Situation model | state reconstruction, predicted versus actual transitions, stale-state rate | concurrent revisions, revoked source, tool failure |
| Adaptive effort | correct decision per latency/compute; escalation precision/recall | unnecessary deliberation, hard deadlines, budget exhaustion |
| Long horizon | resumed goals, actions, state through restart/context reset | stale commitments, contradiction, non-idempotent replay |
| Transfer | separate held-out domains, positive/negative transfer rates | copied answer, wrong task generalization |
| Continual learning | performance on earlier task cohorts after update | catastrophic forgetting, dataset revocation |
| Persona skill | independent output-specific quality, not text fluency alone | fake mastery, unauthorized source, cross-persona leakage |
| Governance | zero policy violations in adversarial corpus | tenant spoofing, plugin escalation, redaction failure |

## CI and runtime validation order

1. **Static integrity:** imports, ruff, mypy, reference audit, contract invariants.
2. **Focused unit:** each unsafe behavior has a failing-before/passing-after test.
3. **Integration:** CORTEX → authorized evidence → runtime → durable outcome, with real PostgreSQL when persistence changes.
4. **Benchmark:** baseline and candidate share fixtures and recorded versions.
5. **Model/runtime acceptance:** actual registered local model where required, not test doubles.
6. **Consumer acceptance:** real signed-in browser if UI/stream contract changes, screenshot and correlation ID evidence.
7. **Release:** exact-head checks, merge, post-merge gates, rollback evidence, runbook updated.

```bash
python -m compileall src
pytest tests/core/reasoning tests/core/adaptive tests/core/intelligence/ml -q
pytest tests/architecture/cognitive_contracts tests/benchmarks/cognitive tests/cognitive -q
ruff check src tests
mypy src
docker compose config
# Frontend changes also require the relevant package's lint, typecheck, test, build and browser gates.
```

Relevant workflows: `.github/workflows/cognitive-proof-ci.yml`, `reasoning-smoke.yml`, `main-quality-gate.yml`, `production-first-boot-smoke.yml`. Confirm actual workflow run and exact commit. A skipped workflow does not count.

## Minimum security and observability evidence

Log bounded structured fields: `correlation_id`, `request_id`, authenticated `tenant_id`/`user_id`, `conversation_id`, `decision_id`, `intent`, `cognitive_status`, `evidence_count`, `policy_version`, `model_id`, `provider_id`, `effort_tier`, `fallback_level`, `latency_ms`, `outcome_status`, `evaluation_id`, `error_code`. Do not log secrets, raw prompts, sensitive user traits or unredacted learning examples. Fail closed on authorization, degrade honestly on optional learning evidence.

## Proof recording contract

Every result includes: task ID, base SHA, head SHA, exact command, outcome, CI run URL when available, test corpus version/hash, model and policy versions, measured statistics, limitation, next action. Screenshots and benchmark plots, when used, must correspond to the executed revision.

A fabricated baseline, synthetic replay claimed as live, or unsupported production-ready designation fails this gate.
