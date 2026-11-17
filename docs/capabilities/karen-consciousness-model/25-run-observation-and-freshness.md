# 25 | KCM-02B3C1: Actual runner observation and freshness provenance

[← Developer wiki](README.md) · [Previous](24-conditioned-task-evidence.md)

## Why this slice exists

The timestamp from KCM-02B3B is the canonical SQLite **receipt-issuance time**, not necessarily when any model inference happened. Reissuing old evaluation outcomes into a newly dated receipt must not be mistaken for fresh task performance.

This stage reuses the existing `BenchmarkRunner`, `BenchmarkResult`, `EvaluationEvidenceStore`, scoped `OutcomeStore`, and KCM read-only projector. No second evaluator, database, tool router, model registry, API, UI, or learner is introduced.

## Runner-observed window

For an actual nonempty `BenchmarkRunner.run`, record:
- one new UUID4-format evaluation run identifier;
- a timezone-aware UTC evaluation start, immediately before the first case;
- a timezone-aware UTC evaluation finish, immediately after the final case;
- the exact canonical model/task/dataset/case-identity checks already enforced by benchmark issuance.

`EvaluationEvidenceStore` persists those values in the **existing** benchmark receipt, rejects missing/partial/non-UTC/future or inverted windows, and revalidates the timestamp fields when inspecting the same current artifact and receipt.

For new runner-attributed receipts, the run ID is also the SQLite receipt primary key. Persisting the *same run* a second time raises an integrity error instead of minting a new receipt date. This is a local replay fence, **not** an off-host cryptographic signature. A privileged writer able to forge benchmark results or rewrite the local database remains outside this proof.

Legacy and directly constructed `BenchmarkResult` records lacking a runner window keep existing narrow receipt behavior. They must never be relabeled as real inference-timestamp evidence.

## What freshness means

- With a runner-observed execution window, KCM computes the configured TTL from **inference completion**.
- Without the window, KCM preserves the B3B issuer-time gate but reports `freshness_basis=receipt_issuance_only` and `runner_execution_window_recorded=false`.
- `evidence_sha256` is a **diagnostic** digest now also bound to the policy version, configured maximum age and expiry. It is not an externally signed approval, capability license, or substitute for a revocation lookup.
- An old measured run recorded in a new receipt is expired when measured inference completion lies outside the configured time window, even if the SQLite receipt itself is recent.

## Scope and remaining unsolved contracts

These are **runner-declared in-process observations**, not independently certified production environment attestation. Host CPU/GPU, provider engine, installed plugin/tools, actual model execution runtime, and externally verifiable measurement have not been attested. Timestamps and case IDs alone cannot establish a training-data holdout, independent groups, independent ground truth, or meaningful general proficiency.

All KCM task evidence keeps these attributes false:

- `independent_trial_groups_verified`
- `production_environment_verified`
- `general_skill_certified`
- `execution_authorized`
- `training_authorized`

No CORTEX or RuntimePolicy access changes, model promotion, memory write, neural training or public API is enabled.

## Proof and forward handoff

Tests run the real canonical evaluator over a curated case with a typed predictor, issue the original canonical SQLite receipt, and verify the exact runner window and duplicate-run rejection. Adversarial tests reject partial/future windows, deny an old inference with a new receipt, and confirm the policy-specific digest changes with TTL while historic issuer-only receipts remain honestly labelled.

The next KCM-02B3C slice must establish separately authorized reviewer admission, exact held-out oracle/task-family provenance, split-leakage checks and immutable environment/runtime attestation. Even those receipts may not activate general-skill or model-execution authority without independent policy admission.
