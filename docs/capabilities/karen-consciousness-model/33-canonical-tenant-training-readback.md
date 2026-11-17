# 33 | KCM-02B3C3B4A: Canonical tenant sklearn dataset readback

[← Developer wiki](README.md) · [Previous](32-observed-fit-input-commitments.md)

## Objective

Read the **actual stored canonical JSONL import bytes** for a named
tenant-scoped sklearn dataset version and verify their SHA-256 against an
expected digest, without following symlinks or accepting arbitrary filenames.

This adds an input-evidence prerequisite for the previously merged
[fit-row HMAC comparison](32-observed-fit-input-commitments.md) and
[frozen KCM assessment join](31-frozen-assessment-to-sklearn-jsonl.md).
It **does not** prove that the worker trained from these bytes or that
the feature values/labels were independently derived from verified
source revisions.

## Authority and API

The canonical storage owner
`ai_karen_engine.core.intelligence.ml.training.dataset_import` now exposes
`read_tenant_sklearn_dataset_snapshot`, alongside the existing immutable
import/listing functions. The source had two identical definitions of
`list_tenant_dataset_versions`; the duplicate was removed after
comparing the bodies, preserving exactly one implementation.

An internal, authenticated caller provides:

- a nonexpired `AuthenticatedPrincipal` with explicit tenant, user and
  session identity, all rechecked after I/O and audit logging
- a **host-owned** canonical import root, never an arbitrary user path
- a dataset version matching the existing importer version grammar
- a 64-character lower-case SHA-256 expected from a separately governed
  snapshot/admission record, **not invented by the reader**
- optional bounded limits, no more than 32 MiB and 10,000 examples

The caller remains responsible for RBAC, proof that the expected digest
came from a reliable authority, current rights/consent and deletion epoch,
and all training/promotion authorization. The method itself cannot
authenticate those facts from caller-supplied parameters.

## File-integrity guarantees

The reader uses the existing tenant directory resolver but **does not
trust a check-then-open pathname**. It walks the absolute host-owned root
from the filesystem anchor, opening **every ancestor component** with
`O_DIRECTORY | O_NOFOLLOW` relative to the prior pinned descriptor.
It then opens the tenant directory relative to that secured root FD and the
named file relative to the tenant FD, also with `O_NOFOLLOW`. This defeats
an intermediate-ancestor symlink swap after the initial ancestor check.
It rejects nonregular or hardlinked files, enforces a bounded read and
compares device/inode/mode/link count/size/timestamps before and after.
It then resolves the filename through the **already-open tenant directory
descriptor** and rejects atomic replacements or modifications during the read.

The SHA-256 is computed over the *actual bytes read*, not an application
supplied row list. Parsing uses LF-only record boundaries, rejects oversized
records, noncanonical importer serialization, invalid or repeated example
IDs, missing/extra schema fields, nonfinite or nonnumeric features,
and incomplete examples. The bytes and private in-memory row objects are
excluded from the result's representation and never logged.

The readback result can be supplied as data to
`inspect_sklearn_fit_input_snapshot` and, separately, its raw bytes to
`inspect_kcm_sklearn_assessment_join`. These are distinct checks that
must be composed by a future trusted coordinator with fresh authoritative
source receipts and owner/job model reconciliation.

## Exact nonclaims

`canonical_tenant_file_read_verified=true` and
`supplied_expected_digest_matches=true` mean the canonical tenant file
matched the **supplied** expected digest during the read window.

They **do not** establish the external authority of the expected digest,
immutability after return, or which snapshot the actual training worker
loaded. All higher-privilege flags remain false:

- `independently_attested_input_bytes`
- `source_to_feature_transformation_verified`,
  `source_ancestry_verified`
- `actual_worker_input_verified`,
  `actual_model_artifact_bound`
- `training_example_inventory_verified`
- `training_evaluation_disjointness_verified`,
  `independent_oracle_verified`
- `training_authorized`, `execution_authorized`,
  `general_skill_certified`

## Proof and next stage

`tests/core/intelligence/test_tenant_dataset_readback.py` uses the actual
tenant importer and stored files. It verifies exact hash/readback,
an observed-fit HMAC comparison using rows from the file, wrong tenant
or owner session, wrong hashes, path traversal, symlinked directories/files,
hard links, **ancestor symlink swaps between check and open and
between individual dirfd opens**, in-place mutation, atomic rename races,
principal drift, malformed row/feature payloads, Unicode line separators,
byte/row budgets and preservation of the canonical listing behavior after
deduplication.

The real KCM PostgreSQL proof workflow runs the tests alongside its
existing tenant/RLS, consent and deletion-epoch cases.

**Next:** independently governed source-to-feature/target transformation
receipts, worker-recorded input byte identity **at actual fit time**, and
durable training-start/promotion revocation leases. No capability described
here enables model training, autonomous execution or certification.
