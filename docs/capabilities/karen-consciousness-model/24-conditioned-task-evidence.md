# 24 | KCM-02B3B: Task conditions, curated oracles and evidence expiry

[← Developer wiki](README.md) · [Previous](23-task-specific-benchmark-assessment.md)

## Operating contract

KCM can describe only what was actually measured under a verified task and model revision. This slice extends the **existing** canonical ML benchmark receipt and KCM task projector. It does not create a benchmark runner, policy router, memory store, reviewer authority or model. It introduces **no general-skill certificate**.

The canonical owner remains `core/intelligence/ml/evaluation`; KCM only reads the resulting bounded evidence. `CapabilityRegistry`, CORTEX, RuntimePolicy, ChatRuntime and EchoCore retain their existing execution, access and training boundaries.

## Source-attested evaluation conditions

New benchmark receipts continue to bind the exact registered model, artifact SHA-256, task, dataset, feature revision, hashed case membership and *per-case* correctness verdict. If the evaluated prediction feature version does not match the registered model, the historical benchmark receipt remains usable for its original purpose, but KCM's stricter case projection is unavailable.

When every evaluated case belongs to the actual `CanonicalEvaluationCorpus` at the recorded dataset version, the issuing evaluator additionally records:

- The SHA-256 fingerprint of the **current canonical curated case content**: hashed input, expected oracle label/value, tags, difficulty, source, feature inputs and declared task group.
- The exact model's registered artifact architecture at issuance.
- The number of distinct **declared** task groups, not a claim that those groups are statistically independent.
- The canonical SQLite benchmark receipt's UTC creation time.

The **actual evaluated case** is fingerprinted by the canonical `BenchmarkRunner` at evaluation time. The issuance adapter requires that fingerprint to match the canonical case's full input/features/oracle contract; reusing a canonical ID with altered input never qualifies. The score of each matching case is also recomputed through the existing `BenchmarkRunner._is_correct` rule before issuing curated-oracle source evidence. Caller-provided `correct=True` on a demonstrably incorrect prediction does not create a verified curated-oracle claim. No prompts or expected labels are written into the new receipt. KCM re-hashes the **current** corpus when reading that receipt; a subsequently edited expected label, input, group or source invalidates it. Legacy and synthetic cases absent from the canonical corpus remain eligible only for existing narrow observed-benchmark reporting, **not** curated-oracle verification.

### Critical distinction

A curated expected-answer set is not automatically independent ground truth. A case group's name or tag is not proof that examples are non-correlated, held out from training, leak-free, or independently reviewed. KCM returns `curated_oracle_source_verified` separately from `independent_trial_groups_verified=false` and `general_skill_certified=false`. This release does **not** issue external oracle attestations or calibrate general proficiency.

## Mandatory freshness gate

KCM uses the **existing centralized learning configuration**, not a scattered route-level threshold:

| Setting | Safe default | Valid range | Function |
|---|---|---|---|
| `KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS` | `2592000` (30 days) | Integer `1..31536000` | Expire benchmark self-assessment evidence before reporting a current score |

The reader verifies timestamp freshness **after** the awaited scoped outcome load and after re-reading the current artifact/receipt. Future-dated or expired benchmark receipts fail closed. The TTL is configurable for trusted composition using the same validation; malformed settings fail configuration validation. A missing or expired receipt produces `health=unavailable` and absent measurements, never fictitious 0% accuracy.

The reported evaluation and expiry timestamps are immutable issuer facts and a deterministic policy-derived boundary. The separate diagnostic lineage fingerprint binds tenant, user, model, version, case verdicts and curated oracle digest.

## Truthful operational environment

The model's recorded architecture is a verified artifact-registry property; it is **not** a proof of the host's current CPU/GPU, installed tools, plugins, execution engine, live external API availability or deployment readiness. Therefore `production_environment_verified=false` always holds in this release. Similarly, absence of task-family independence keeps all Wilson score bounds descriptive rather than a statistically certified proficiency guarantee.

Nothing in these reports can authorize execution, training, checkpoint promotion or external actions. No runtime API/UI has been activated.

## Tests and proof

The dedicated KCM gate includes isolated registry + SQLite benchmark issuance and read, canonical scoped OutcomeStore, source-corpus drift, custom-corpus input substitution under reused case IDs, altered curated digest, false correctness claims, unreviewed grouping, expired and future timestamps, centrally configured TTL and malformed environment values, along with existing artifact drift, tenant isolation, duplicated/altered case verdicts and no-store-create reads. Existing CI still proves PostgreSQL RLS, memory revocation, cognitive authority and the first-boot release contract.

This is **integrity against normal application mutations**, not cryptographic proof against a privileged machine administrator who can rewrite both data and receipts.

## Unfinished acceptance: KCM-02B3C

Before any true certified skill or production-condition claim, Karen needs separately governed, reviewer-backed held-out oracle approval; independently justified task-family split membership; runtime/environment/version attestation; source revocation/expiry lineage and measurement against preregistered coverage, failure and confidence thresholds. Do not derive these from case tags, ordinary execution success, curator-authored text, user feedback or the model's own self-rating.
