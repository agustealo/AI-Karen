# 17 | KCM-01D1: Live dataset evidence preflight

[← Index](README.md) · [Previous](16-development-status.md)

## Decision

Memory retention, independent candidate admission, dataset integrity, and
training-start authorization are **four different gates**. This slice implements
only an inspectable, fail-closed revalidation of a frozen dataset's source
evidence. It does not write a dataset, start training, or promote a model.

## Existing owners and new read path

- Canonical data definitions: `core/memory/types/base.py`.
- Provenance, consent and owner scope: `echocore/postgres_training_evidence.py`,
  using the memory ledger and purpose-specific `consent_scope`.
- Rights, ground-truth labels and quality dimensions: existing EchoCore
  `TrainingEvidenceResolver` contract; missing independently verified
  implementations **cannot be replaced by model self-confidence**.
- Dataset structure and hashes: `learning/kcm_dataset_integrity.py`.
- Dataset-source evidence recheck: `learning/kcm_dataset_preflight.py`.
- Long-lived source-to-checkpoint ancestry and deletion epochs:
  **not yet durably implemented**. No training worker is authorized.

## Required preflight inputs

The trusted caller supplies an exact frozen manifest and actual dataset bytes;
an authenticated tenant/user identity; an explicit bounded member budget; a
host-owned `TrainingEvidenceResolver`; and a host-owned `KcmDeletionEpochReader`.

The inspector:

1. Rejects missing trusted ports, malformed/unsafe budgets, and owner mismatch.
2. Reads an authoritative tenant/user deletion epoch, rejecting unknown state.
3. Verifies frozen manifest structure, dataset bytes, source revisions, ordering
   and leakage-group separation through the existing inspector.
4. Re-fetches each member's source, revision, objective, consent, rights and
   verified-target provenance. All fields and every receipt ID must match its
   manifest record, and the current source must be usable.
5. Reads the deletion epoch again. Any mutation or failure blocks the report.
6. Produces a canonical evidence digest and a non-authorizing audit report.

The report's `training_authorized` field is **always false**, even when all
checks pass. This report cannot become a model invocation or training grant.

## Race conditions, revocation and remaining architecture

Double-reading the epoch detects changes *during* inspection but **does not
create an atomic lock**. A deletion may occur immediately after the second read.
Before a training worker is enabled, the source-ledger lineage owner must
provide a durable, tenant/user-scoped epoch and a transactional lease/fence.
The training executor must recheck under that fence at training start and
model/checkpoint promotion. Revoking a source must locate all derived manifests,
training runs, adapters, quantized/exported checkpoints and deployments. Merely
deleting a JSONL row is not unlearning model weights.

The current PostgreSQL evidence resolver deliberately reports training rights
and independent target verification as unavailable. Hence the current production
composition still **cannot pass this preflight**, even if a manifest includes
nonempty receipt strings. This is the safe outcome until separately governed
rights/label attestations exist.

## Proof and limitations

Local focused tests verify strict owner scope, actual dataset digest, every
receipt identity, verification/rights/privacy vetoes, missing authorities, stale
epochs, concurrent revocation, budget limits and deterministic inspection
fingerprints. They do not substitute for production PostgreSQL RLS, migration
and end-to-end transaction tests.

**Next:** KCM-01D2 must implement a canonical durable deletion epoch, append-only
rights and independently verified target receipts with tenant RLS, lineage
membership storage, revocation propagation, and atomic training/publication
fences. No independent memory database, new router or neural model is needed.
