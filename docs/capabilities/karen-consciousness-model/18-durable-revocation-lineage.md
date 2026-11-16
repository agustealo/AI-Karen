# 18 | KCM-01D2A: Durable revocation watermark and source lineage

[← Index](README.md) · [Previous](17-evidence-preflight.md)

**Status: Development slice only.** This schema provides a durable but
**non-promoting** governance projection for KCM. The user and tenant remain
the sole scope. NeuroVault owns original memories; EchoCore owns training
admission; no local model is permitted to train from this feature.

## 1. Ownership

| Responsibility | Existing canonical owner |
|---|---|
| Memory source, consent, deletion | NeuroVault, memory ledger, privacy lifecycle |
| Candidate evaluation | EchoCore training admission |
| Dataset structural integrity and preflight | Existing \`learning/kcm_dataset_integrity.py\` and \`learning/kcm_dataset_preflight.py\` |
| Durable training-related revocation epoch and source ancestry | \`supabase/migrations/20261116190000_58_kcm_training_lineage_revocation.sql\`; read adapter \`learning/kcm_governance.py\` |
| Training execution, model registry, promotion | Existing governed training/model lifecycle (not enabled for KCM) |

There is no new memory store or secondary cognitive orchestrator.

## 2. Database contract

- \`public.kcm_training_scope_state\` is a user/tenant-bound, monotonic
  deletion-epoch record. It **never** grants training. A missing row means
  unprovisioned and is returned as unavailable, never as epoch zero.
- \`public.kcm_dataset_source_lineage\` is an audit index containing immutable
  dataset/source revision references and no raw memory or example payload.
  Lineage is \`quarantined\` or \`revoked\`, never approved for training.
- \`public.kcm_training_source_revocations\` records source identity, digest,
  revocation reason and epoch. Records are append-only under ordinary RLS.
- All three tables have enforced RLS for both \`app.current_tenant_id\` and
  \`app.current_user_id\`, with public/anon/authenticated privileges revoked.
  User and tenant deletions cascade into these derived records.

In the non-exposed \`kcm_internal\` schema, narrowly scoped privileged
functions support idempotent scope provisioning and serialized revocation.
They enforce the exact current transaction-scoped principal, lock the owner's
epoch row, update that epoch monotonically, append the source revocation and
mark matching dataset lineage revoked in **one database transaction**.
No public or authenticated execution grants are provided. A trusted host
execution role requires separate reviewed provisioning.

## 3. Read-only repository contract

\`PostgresKcmGovernanceReader.current_epoch(tenant_id, user_id)\` implements
the existing \`KcmDeletionEpochReader\` protocol; it reads actual PostgreSQL
data with tenant **and** user scope set through \`async_transaction_scope\`.
Absent, invalid or unprovisioned epochs return \`None\`; the preflight blocks.

\`affected_datasets(tenant_id, user_id, source_event_id, source_revision)\`
returns only source/dataset identity and quarantined/revoked status. Scope
must exist, source revisions must be exact SHA-256 digests, and reads have a
bounded result budget. The result is diagnostic, not a deletion-completed
receipt or an unlearning guarantee.

## 4. Deliberate blockers and security boundary

**The revocation function is NOT yet wired to all canonical memory deletion,
consent-revocation, supersession, erasure, or rights/verification-withdrawal
paths.** Therefore the epoch is not yet a complete watermark for production
training. Turning this function on without that integration would be unsafe.

**There is no durable training admission/rights/target-verification approver
yet.** A source record, a successful chat run, a receipt-shaped string, or
a consent scope alone must never advance KCM into training.

There is no capability to claim an atomic training-start or model-promotion
lock. The preflight checks epoch before/after inspection but cannot prevent a
revocation immediately afterwards. Every future training worker must acquire
a durable transactionally fenced execution lease or use an equivalent
proof-backed atomic revocation check.

This migration intentionally does not create a privileged training job,
enable weights, grant user-facing RPC access, or install a model.

## 5. Acceptance and tests

- Schema applies cleanly to the canonical migrated PostgreSQL baseline.
- Tables and privileged routines are **not exposed** through the Data API.
- Two-tenant and two-user RLS tests reject cross-owner reads and writes.
- Wrong authenticated principal cannot call private scope functions.
- Source revocation is serialized, idempotent for the exact revision, bumps
  epoch once and marks all matching source lineage as revoked atomically.
- A nonexistent owner scope fails closed.
- New model/data-trainability checks remain invariantly false.
- User or tenant erasure cascades to derived lineage/receipts, without
  blocking the existing canonical memory deletion workflow.
- Unit/static tests are not a substitute for live Postgres assertions or
  confirmation that canonical lifecycle hooks are wired.

## 6. Next workstream

**KCM-01D2B:** connect all NeuroVault/consent/rights/erasure invalidation
paths to the trusted transactional revocation authority; add real PostgreSQL
RLS and concurrency tests, verified training-rights and label attestation
owners, and source-to-checkpoint ancestry before any training permit exists.
