# KCOG Sprint Execution Plan

> **Sprint:** KCOG-S1 ("Cognitive Integrity → Executive Control").
> **Stage:** IMPLEMENTING. KCOG-01A1 and KCON-211 are merged; KCOG-01A2 is a separate, unaccepted shadow-evaluation slice.
> **Start baseline:** `272e23c4b5879771294e46c2d205e3b6f3909050`. Rebase/compare against live main before each implementation branch.
> **Order:** audit → contain invalid outputs → prove safety → integrate cognitive state → measure decisions.

## Live S1 execution checkpoint (2026-11-15)

- Wiki #863 merged to main `c18b3dfe3376a02e1c5de51e0195b9be7e0af182`.
- First KCOG-00A containment #864 merged to main `2d8b0171b9f37f4eb1e2b32290b51d3ec36c916d`, all exact-head checks green.
- Documentation checkpoint #866 merged `724edec8ec12425bc193510270e6bdbb04677f30` and post-merge Main Quality green at inspection.
- KCOG-00A2 #868 (**MERGED**) `afa845187151715692ca15a75b93871c7403351f`, exact-head CI green including First-Boot; unsupported causal numerical APIs abstain.
- KCOG-00B1 #869 (**MERGED**) `fd0d2e408e7c2c6cd82bdc1015ea4c030dbf3ea3`, exact-head CI green including First-Boot; unknown calibration and attribution cannot masquerade as zero.
- KCOG-00A3 #871 (**MERGED**) `92ab8a45babc3b271447b3874a10feac99df3085`: verified exact-head gates incl first boot, advertised capability now abstains without pretending causal estimation.
- KCOG-01A1 #875 (**MERGED**) `97fec3ce77639222d439de4c810162a24bad58b0`: governed conflict-to-verification and typed post-policy `CognitiveState`. No measured cognitive improvement claimed.
- KCON-211 #881 (**MERGED**) `5b75fd8576677f14fb5ba635dca05b531dfcd5cc`: all 10 exact-head workflows passed, including authenticated real Ollama Settings save/reload and unforced local model execution. Real-browser CopilotKit consumer acceptance remains separate.
- KCOG-01A2 (**IN DEVELOPMENT, NOT ACCEPTED**): evaluate confidence only against canonical tenant/user-scoped, labelled `GovernedMLLearningEvidence` using the existing Intelligence Brier/ECE metrics. Filter by exact task, model, model version and feature version; exclude fallbacks and unverified labels; return absent scores for insufficient evidence. The first stage is read-only/shadow, never a RuntimePolicy authorization or promotion receipt. Separate, independently labelled evaluation of verification decision utility, calibration drift and consumer impact is still required.
- GitHub Issues are disabled (HTTP 410); this wiki and PR descriptions retain sprint continuity. Verify live CI before acting.
- **No claims yet** of validated causal-effect estimation, calibrated metacognition, specialist competence gain, or cross-task transfer.

## KCOG-01B1: Verification-effort policy evaluation (merged #891)

- **Acceptance:** #891 merged as `29f7f1b0fefb56b53bce46402c9d9f77b663e6ee`, seven exact-head workflows successful. The result is shadow-only, with no measured cognitive improvement.
- **Owner:** canonical `Intelligence ML policy_evaluation` contracts and evidence guard; `OfflinePolicyEvaluator` retains all IPS/SNIPS/DR, overlap and promotion calculations.
- **Input:** a tenant-scoped, independently judged `RESPOND_STRATEGY` observation with versioned baseline and candidate probabilities, independently recorded reward and verification-need labels, separate opaque receipts, a decision-time feature snapshot and versioned utility policy.
- **Denial rules:** reject cross-tenant, duplicate label receipts, missing/made-up propensities, unlabelled results, high-risk or forbidden exploration, incompatible action sets and nonfinite rewards. Never treat response completion as a correct answer.
- **Output:** `shadow` evaluation with observed verification, unnecessary-verification and missed-verification rates, plus canonical overlap/estimator diagnostics if a sufficient verified corpus exists. The observed rates are descriptive, not a counterfactual performance claim.
- **Authority:** `policy_activated=False`, and RuntimePolicy must separately authorize any production change. This branch does not grant permission to turn verification off for high-risk requests or change the model router.
- **Proof:** existing model-routing OPE tests plus new verification-policy adversarial cases under Cognitive Proof CI; Main Quality and first-boot must pass for merge.
- **Remaining evidence:** deployment-independent, prospectively sampled baseline/candidate cases, logged real action propensities, held-out independent correctness and safety reviews, latency/cost and segment-level regression analysis; no verified intelligence improvement is claimed yet.

## KCOG-01B2: Canonical OPE estimator integrity (merged #895)

- **Owner:** `core/intelligence/ml/policy_evaluation/estimators.py`. Do not add a duplicate estimator to KCOG or model/provider routing.
- **Audit finding:** the previous effective sample size computed mean squared divided by variance, not Kish effective sample size; the overlap diagnostic counted eligible actions as though they had actually been observed; the default `DoublyRobustEstimator` used the observed outcome as a missing reward-model substitute. These defects can exaggerate causal support and evidence for promotion.
- **Remediation:** implement Kish ESS `(sum weights)^2 / sum(weights^2)`, bounded by the sample count. Measure action support from observed chosen actions and flag target actions never observed. DR now requires an action-conditioned reward estimator; it calculates expected target-policy reward across actions plus the importance-weighted residual for the logged action. Missing, invalid or failed nuisance-model predictions must fail closed rather than copy the logged reward.
- **Promotion safety:** `OfflinePolicyEvaluator` has no validated nuisance reward model wired by default. It will therefore omit DR evidence, and the existing promotion gate's `require_dr` protection blocks eligibility. Production policy changes still require separate authorization and a verified held-out study.
- **Proof:** synthetic exact arithmetic and negative support tests, missing/invalid reward model, returned estimator evidence, and no false automatic promotion. Gate under Cognitive Proof CI and verify the exact head before merge.
- **Remaining acceptance:** separately validated and registered action-conditioned nuisance model, held-out label provenance, effective overlap and non-inferiority on correctness/safety, latency and cost. No automatically activated verification change.

## KCOG-01B3: Observational-policy report provenance (draft, not accepted)

- **Base:** KCOG-01B2 #895 merged as `219889ed5c032652230eeb1bf24fb1cc6a93e3a6`. Subsequent unrelated voice changes may land on live main before PR creation.
- **Owner:** existing `OfflinePolicyEvaluator` in `core/adaptive/learning/offline_evaluation.py`; keep the Intelligence/ML canonical estimators and policy contracts unchanged.
- **Audit finding:** the evaluator labelled the overall behavior-policy success fraction as `candidate_success_rate` even when no candidate decisions had been executed. It also divided baseline successes by the entire mixed-policy corpus rather than by the actual baseline behavior cohort. Completion-only legacy dict rows were presented as baseline evidence.
- **Fix:** report an explicit overall observed reward-threshold rate, and split baseline/candidate observed rates by **exact logged behavior policy ID and version**. A never-executed candidate or missing baseline has a `None` rate and zero observed count, not fabricated success. The legacy status path reports only an unattributed observed completion fraction; empty corpora expose nullable fields. Include a `rate_source` qualifier to prevent treating the threshold as verified answer correctness or a counterfactual estimate.
- **Proof:** synthetic exact-cohort tests, no-candidate execution, wrong version, no-baseline, mixed-policy corpus, legacy completion, empty outcome, and existing adaptive learning regression. Added to Cognitive Proof CI.
- **Limits:** descriptive logged reward thresholds do not measure causal benefit or independently judged correctness, and cannot authorize a policy change. An independently reviewed held-out prospective dataset remains necessary.

## Scope, product acceptance and exit

Demonstrate a real runtime path in which (a) a false or unidentifiable causal claim is never promoted as fact, (b) confidence is not misrepresented as calibration, (c) an authenticated task receives a structured cognitive assessment via existing CORTEX/RuntimePolicy, (d) extra deliberation is requested only when risk/uncertainty justifies it, and (e) a real, stable benchmark compares correctness, latency, tools and abstention against baseline.

**Exit requires:** passing source-level safety tests, exact-head CI, real local execution under the registered runtime, PostgreSQL tenant-negative tests where persistence changes, consumer-visible degraded truth, and no unacceptable regression. If deployment credentials or models are unavailable, record the gate as BLOCKED, never passed.

## Ticket 00A: Inventory, reproduce, quarantine

**Objective:** Record and reproduce every claim of causal discovery, interventions, calibrated confidence, attribution and lesson transfer that source cannot support.

**Do:** inspect `core/reasoning/causal/engine.py`, `causal/cognitive_causal.py`, `reasoning/meta/calibration.py`, `adaptive/learning/experience/attribution.py`, `intelligence/ml/online_learning.py`, `intelligence/ml/durable_outcomes.py`, `adaptive/learning/reflector.py`. Build call-site/reference matrix from all production imports, public routes and tests. Classify ACTIVE / ADVISORY / EXPERIMENTAL / DEAD and record risk. Audit existing regression tests before changing a return type.

**Reuse:** `CognitiveState`, `OutcomeStore`, `TrajectoryStore`, current evaluation and telemetry contracts. **Avoid:** new causal registry or parallel learning pipeline.

**Proof:** tests showing unknown edge direction does not become causal truth; missing treatment or control does not become a zero effect; fixed intervention/counterfactual guesses do not masquerade as identified probability; no assumptions silently labeled as evidence. Import/reference audit and CI.

**Risk:** changing legacy APIs could affect consumers. First make explicit non-authoritative states/guards, preserve safe signatures when possible. Ownership follows [the callgraph](OWNERSHIP_AND_CALLGRAPH.md).

## Ticket 00B: Calibration and attribution integrity

**Objective:** Make epistemic uncertainty testable without inventing measurements.

**Do:** project verified prediction/outcome pairs from the existing tenant-scoped outcome evidence; support proper scores (Brier/ECE on specified binary tasks) with sample count, version and data provenance; leave unverified predictions as `uncalibrated`. Remove numeric causal-contribution claims without identifiability evidence; retain categorical, provisional hypotheses where useful. Do not create a duplicate source of truth.

**Reuse:** `core/intelligence/ml/calibration.py`, `GovernedMLLearningEvidence`, existing `core/reasoning/meta` contracts. **Avoid:** promoting `CalibrationTracker.accuracy()` into calibrated probability or using response success as a label.

**Proof:** perfect/worst calibration fixtures, missing labels, wrong-tenant rows, duplicate outcomes, distribution shift, empty/low-sample handling, replay and restart. Human review or held-out evaluation must originate from verifiable records.

## Ticket 01A: Authenticated cognitive state through the canonical decision path

**Objective:** Connect existing state contracts to observable runtime decisions.

**Do:** inspect `core/cognitive/state.py`, `core/cortex/executive.py`, `core/runtime/decision_pipeline.py`, `core/reasoning/meta/assessment.py`, `core/runtime/chat_runtime.py`; unify only missing fields and references. Build authorized state from verified evidence, goals, conflict summaries and meta assessment, with versioned prompt/runtime execution policy. Keep CORTEX decision-only.

**Reuse:** RuntimeEvidenceResolver, RuntimePolicy, `CognitiveState`, MetaCognitiveAssessor, decision/feature snapshots. **Avoid:** new executor, UI-made confidence, tenant scope from untrusted payload.

**Proof:** identical request under low risk stays direct; conflict or high risk requests verification without unauthorized tool use; policy denial blocks evidence; exhaustion/deadline bounded; source receipts tie state to outcome.

## Ticket 01B: Adaptive effort policy and head-to-head evaluation

**Objective:** Demonstrate useful improvement, not "more thinking".

**Do:** compare fixed baseline with the candidate policy over an immutable task corpus; record reasoning depth, verification decisions, accuracy, groundedness, latency, compute and abstentions. Run canary/shadow only after validation and approval.

**Reuse:** existing cognitive benchmark runner, ML registry/promotion services, telemetry and runtime decision contracts. **Avoid:** changing provider selection inside routes, benchmark leakage, success judgments from the same generating model.

**Proof:** held-out improvement with predeclared evaluation thresholds and segment-level regressions. Report confidence intervals and evaluation sample sizes. Evidence review required before enabling.

## Future-sprint dependency queue (NOT part of S1 implementation)

| Workstream | Must exist first | Required evidence |
| --- | --- | --- |
| KCOG-02 world prediction | 01A typed state, verified outcomes | predicted vs observed transitions, stale state fencing, intervention assumptions, out-of-distribution abstention |
| KCOG-03 transfer learning | 00A/B integrity, durable evidence | separate source/target tasks, negative transfer, retention and replay tests |
| KCOG-04 skill/competency | governed datasets + 03 | proficiency proved on unseen tasks with domain-appropriate evaluators |
| KCOG-05 multimodal | grounded world-state contract | modality-specific provenance, consent and alignment tests |
| KCOG-06 self-improvement | 03/04 evidence + lifecycle | authorized promotion, catastrophic-forgetting guard, retirement/revocation |

## Required handoff per ticket

**Task# / Title / Objective / Current owner / Current main SHA / Do / Reuse / Avoid / Exact files / Tests / Evidence link / CI exact head / Risk / Open questions / Next authorized action.** No "completed" until supported by a specific check or runtime receipt.

## Acceptance commands

```bash
python -m compileall src
pytest tests/core/reasoning tests/core/adaptive tests/core/intelligence/ml tests/architecture/cognitive_contracts tests/benchmarks/cognitive -q
pytest tests/cognitive -q
ruff check src tests
mypy src
docker compose config
# If a frontend contract changes, also run the established frontend lint/typecheck/test/build gates.
```

CI: `.github/workflows/cognitive-proof-ci.yml`, `reasoning-smoke.yml`, `main-quality-gate.yml`, `production-first-boot-smoke.yml`. Validate actual workflow applicability; never infer that a skipped job passed.
