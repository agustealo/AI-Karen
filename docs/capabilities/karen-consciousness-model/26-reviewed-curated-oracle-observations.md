# 26 | KCM-02B3C2A: Governed curated-oracle reviewer observation

[← Index](README.md) · [Previous](25-run-observation-and-freshness.md)

## Objective

Record a separately authorized **reviewer observation** tied to the exact current canonical ML task cohort, rather than accept user-authored skill assertions, unscoped review labels or independent-group assumptions. This slice creates no neural weights, execution route or model authority. The source remains `core/intelligence/ml/evaluation`.

## Canonical ownership

- `MLModelRegistry`: source of truth for current model/artifact and tenant-prefixed identity.
- `EvaluationEvidenceStore`: source of truth for exact model/dataset/feature, case verdicts and canonical curated-oracle source fingerprint.
- `BenchmarkRunner`: measured inference time and unique run identity (PR #961).
- `KcmBenchmarkTaskProjector`: required current, scoped, exact per-case outcomes in canonical `OutcomeStore`.
- `GovernedCuratedOracleReviewEvidence`: a new, **narrow review adapter** using the SAME `OutcomeStore`, not a second review database or policy router.
- `Permission.BENCHMARK_ORACLE_REVIEW`: distinct dedicated reviewer RBAC right; not a training or model-promotion permission.

## Reviewer contract

A trusted, non-expired reviewer principal must be in the exact subject tenant, have a valid session identifier and the dedicated benchmark-oracle-review permission, and must not be the benchmark subject. A separate authenticated subject principal is required. The reviewer cannot supply case IDs, labels, group names, hashes, model architecture, benchmark scores or promotion flags.

Before issuing a unique append-only receipt, the adapter recomputes the current canonical source and exact evaluation receipt, requires a runner-observed measurement window, checks freshness from current learning settings, and requires the existing user-scoped benchmark outcome projector to report a complete measured cohort. It binds each case's SHA-derived reference and curator-declared group membership, original verdicts, model artifact and inference run to one deterministic snapshot SHA-256. After awaited reads or writes, current provenance is checked again; drift invalidates consumption.

The reviewer uses the existing `OutcomeStore.save_unique_outcome_async` to append **two deterministic records** per subject/run: a non-consumable `proposed` record, then a `confirmed` record after a fresh subject/reviewer authorization fence. All readers require the exact matching pair. An expired reviewer during proposal persistence may leave a pending record, but it never qualifies as an acknowledged review. A retry against the same run remains fail-closed until a separately governed recovery workflow exists. Canonical store validation admits only the exact redacted reviewer schema. A specialized owner- and schema-filtered numeric query is applied **before** bounded cohort reads, preventing reviewer receipts from crowding out numeric benchmark outcomes. Reviewer permission/session claims are rechecked after awaited cohort reads and the tentative proposal append, immediately before the final confirmation append. The confirmation commit is the authorization linearization point; no post-commit permission denial can leave a completed record falsely reported as rejected. Subject identity is independently checked after the final awaited consumer read. Atomic identity revocation during database commit still requires a separate trusted authorization lease; these observations do not grant any capability. A second issuance conflicts instead of changing the original reviewer opinion. Reads require the original subject scope, exact canonical dataset and model/receipt, and a matching stored review fingerprint.

## No independence or external attestation claim

This is evidence that a separately authenticated, permitted reviewer **acknowledged the exact source snapshot**. It is *not* proof that the human personally inspected raw examples, that expected answers are independent ground truth, that the reviewer differs from the original evaluator or dataset author, that training and evaluation sets are disjoint, or that task-group declarations imply independence. These additional proofs require separately bound author/evaluator identities, audited held-out split provenance and an independent leakage review.

All such flags remain false: `independent_trial_groups_verified`, `independent_ground_truth_verified`, `training_data_disjointness_verified`, `production_environment_verified`, `general_skill_certified`, `execution_authorized` and `training_authorized`.

Local append-only integrity and SHA-256 are not off-host digital signatures against a privileged database or filesystem administrator. A later slice must add independently governed revocation and rights checks before any proficiency policy can consume review evidence.

## Adversarial proof

The scoped KCM test suite exercises real `BenchmarkRunner` output, the current registry artifact, canonical SQLite benchmark receipt, actual scoped numeric `OutcomeStore` cases, reviewer acknowledgment, duplicate review replay denial, subject mismatch, unauthorized reviewer, self-review, session absence, expiry, tampered receipt hash, record deletion, artifact drift and legacy receipt rejection. Real PostgreSQL RLS and final exact-head CI remain mandatory for merge.

**Not released:** No public API, user interface, autonomous task, model training or capability certification.
