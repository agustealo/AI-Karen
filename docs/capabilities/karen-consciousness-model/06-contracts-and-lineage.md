# 06 | Data contracts, provenance and lineage

[← Index](README.md) · [Previous](05-quality-selection.md) · [Next →](07-datasets-and-curation.md)

## 1. Contract rules

Use the canonical memory types and existing EchoCore training candidate as the upstream adapters. Do not introduce another `MemoryEntry` or a second `ArtifactTrainingEligibility` that silently disagrees with `core/memory/types/base.py`.

A **training-candidate assessment** is a new downstream *derived record*, scoped to an objective and source version. It should be immutable per evaluation version, with state transitions captured in an append-only auditable lifecycle log.

Mandatory IDs: `assessment_id`, `source_artifact_id`, `source_revision`, `tenant_id`, `owner_user_id`, `objective_id`, `objective_version`, `policy_version`, `evaluator_version`, `created_at`. No implicit tenant defaults. All unknown/missing evidence must remain unknown, not coerced to passing.

## 2. Proposed candidate assessment (typed logical contract)

| Field | Type | Meaning |
|---|---|---|
| `assessment_id` | UUID | Idempotency identity for assessment |
| `tenant_id`, `owner_user_id` | UUID/string | Scope and access owner |
| `source_artifact_id`, `source_revision` | string/int | Durable evidence pointer; no mandatory duplicate payload |
| `source_kind`, `source_tier` | enums | Existing memory/outcome/doc source classification |
| `objective_id`, `objective_version` | strings | Purpose-limited learning objective |
| `target_type` | enum | `sft_completion`, `preference_pair`, `skill_procedure`, `classification_label`, `evaluation_only` |
| `admission_state` | enum | Discovered, blocked, needs verification, review, approved, selected, consumed, rejected, revoked |
| `consent_scope`, `license_ref` | strings | Explicit training right and data license provenance |
| `privacy_flags`, `trust_class` | enums/arrays | Existing guards are authoritative |
| `source_valid_at`, `verified_at` | timestamps | Temporal and source verification evidence |
| `ground_truth_refs`, `outcome_refs` | arrays | Immutable verified proof IDs |
| `quality_dimensions` | decimal map | Six recorded dimensions; no single opaque score |
| `aggregate_score`, `scorer_version` | decimal/string | Rank only within declared objective |
| `decision_reason_codes` | string[] | Explain blocks, reviewer needs, approval |
| `lineage_fingerprint` | SHA-256 | Stable source + objective + content-revision digest |
| `review_receipt_id` | string/null | Approved reviewer or independently verifiable rule |
| `created_at`, `evaluated_at` | timestamps | UTC timestamps |

`schemas/kcm_training_candidate.schema.json` provides the detailed design schema. Schema validation is necessary, not sufficient: real DB authorization and consent validation must occur server-side.

## 3. Provenance contract

A candidate must be linked to **both** source and derived label:

```
source memory/version (NeuroVault) ──┐
verified outcome/test evidence ─────┼──> candidate assessment
consent/license/policy version ─────┤         ↓
training objective + evaluator ─────┘   dataset manifest and recipe
                                            ↓
                            dataset immutable content digest
                                            ↓
                        training job / base model / adapter
                                            ↓
                        evaluation evidence / approval receipt
                                            ↓
                         active capability and deployment ref
```

A model's answer is not a trustworthy provenance root for factual correctness; link to real-world independent evidence or mark unverified.

## 4. Dataset manifest and immutability

Every dataset release records:

- `dataset_id`, monotonic dataset revision, tenant and authorized purpose.
- `selection_recipe_id`, version, parameters and code/config digests.
- Source/assessment identities, content hashes, stratification and per-source counts.
- Train/dev/test membership and **leakage-group IDs**; no same underlying conversation/task/template/fact cluster across splits.
- Content redaction policy version, license manifest and current consent snapshot.
- Dataset bytes SHA-256 and reproducible ordering/seed.
- Base model compatibility, tokenizer/template version, allowed training objectives.
- Revoked source checks performed immediately before training and again before promotion.

`schemas/kcm_dataset_manifest.schema.json` is a proposed external format. The stored SQL rows and object-store layout must reuse the canonical dataset owner; do not create extra JSONL directories as an authoritative database.

## 5. SQL integration strategy (not a deployable migration)

Before modifying schema, inspect existing migrations and dataset/outcome models. Prefer extending them with **foreign keys and RLS** rather than creating parallel tables. If migration is justified, it must provide the following relationships and constraints:

- `training_candidate_assessment`: composite tenant/source/objective identity; uniqueness for `(tenant_id, source_artifact_id, source_revision, objective_id, evaluator_version)`; valid enum state; `0<=score<=1`; immutable evaluator evidence.
- `training_candidate_decision`: append-only versioned transition log, actor, reason code, timestamp, previous/new state and policy hash.
- `training_dataset_membership`: `(tenant_id, dataset_version_id, assessment_id, split, leakage_group_id)` with foreign keys and uniqueness.
- `model_dataset_lineage`: `model_artifact_id -> training_run_id -> dataset_version_id`; append-only and deleted-source query index.
- `training_source_revocation`: tenant-scoped source ID/revision and revocation epoch; membership/build/activation fencing.

**RLS:** deny by default; authorize each operation using trusted transaction-scoped tenant claims and role permissions; test connection-pool reuse. A shared model trained on multiple tenants is forbidden by default. Global research datasets require wholly separate policy and authorization.

Store sanitized content in existing authorized dataset artifact storage with integrity digest; keep raw memory payload under its original memory authority.

## 6. Event semantics and idempotency

Events should be structured and versioned:

- `kcm.training_candidate.discovered`
- `kcm.training_candidate.gated`
- `kcm.training_candidate.verified`
- `kcm.training_candidate.reviewed`
- `kcm.dataset.frozen`
- `kcm.training.started|failed|completed`
- `kcm.model.evaluated|approved|activated|revoked`
- `kcm.training_source.revoked`
- `kcm.lineage.fenced|remediated`

Each event includes `tenant_id`, `user_id` where applicable, `correlation_id`, `request_id`, `objective_id`, assessment/run IDs, `policy_version`, event sequence and reason code. Never include raw prompts, secrets or personal training examples in logs.

## 7. Content lineage invariants

- No training run may reference a mutable dataset alias; it must cite a manifest digest.
- Every manifest member must be valid at *training admission* and *training start*.
- Every model must declare its source training set and artifact SHA.
- Revoking a source produces an ancestry query identifying affected datasets, runs, adapters, merges, exported/quantized checkpoints and deployments.
- Never claim that deleting a JSONL record unlearns parameters. See [governance](10-governance-security.md).

## 8. API contracts (internal first)

Avoid adding public routes until job/assessment storage and RLS exist. Suggested internal ports to attach to the existing owners:

- `assess_training_candidate(scope, artifact_ref, objective_ref) -> AssessmentReceipt`
- `list_candidate_assessments(scope, objective_ref, filters) -> Page[AssessmentProjection]`
- `review_candidate(scope, assessment_id, adjudication) -> ReviewReceipt`
- `freeze_dataset(scope, objective_ref, recipe_ref) -> DatasetManifestReceipt`
- `start_training(scope, manifest_sha, model_ref, training_config) -> JobReceipt`
- `evaluate_checkpoint(scope, checkpoint_ref, benchmark_manifest_sha) -> EvaluationReceipt`
- `promote_checkpoint(scope, approval_ref, checkpoint_sha) -> ModelPromotionReceipt`
- `revoke_training_source(scope, source_ref, reason) -> RevocationReceipt`

These are **proposed signatures**, not functions verified in the repository. Extend current API/service ownership and return actual durable receipts, never fake success.
