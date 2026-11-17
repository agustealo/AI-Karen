# 31 | KCM-02B3C3B3A: Frozen assessment to sklearn JSONL alignment

[← Developer wiki](README.md) · [Previous](30-owner-scoped-fit-artifact-binding.md)

## Purpose and current proof level

KCM-02B3C3B2 established the owner-scoped successful training job, registered
artifact, and keyed worker-observed fit receipt. This step introduces an
independent **structural assessment membership check** between an existing
frozen KCM manifest and canonical sklearn JSONL input rows.

It is not source-to-feature ancestry. A row's `example_id` can claim a
matching frozen `assessment_id` without proving that its features or target
were derived from the reviewed source. It is also not proof that sklearn
consumed that row. These two missing links must not be inferred from
matching identifiers or dataset versions.

## Canonical authority and source locations

The read-only function
`ai_karen_engine.learning.kcm_sklearn_assessment_join.inspect_kcm_sklearn_assessment_join`
is in the existing learning/dataset governance domain.

It delegates fresh rights, consent, verified-target and tenant/owner deletion
epoch checks to **`inspect_kcm_dataset_evidence`**, which itself reuses the
frozen manifest inspector and governed `TrainingEvidenceResolver`. The
existing sklearn JSONL importer owns canonical row serialization; no new
database, authorization path, model loader, scheduler, or source-of-truth
registry is introduced.

The caller must provide a trusted `AuthenticatedPrincipal`, exact bytes
read through independently authorized storage ports, a host-owned evidence
resolver, and the canonical tenant/user deletion-epoch reader. The function
does not accept arbitrary filesystem paths or client-provided authorization
flags, and it has no side effects.

## Structural verification procedure

1. Enforce a nonexpired authenticated principal and bounded input: no more
   than 10,000 manifest members and 32 MiB per byte buffer.
2. Run the existing frozen-manifest integrity and current evidence preflight,
   verifying consent/rights/target receipts for **every** manifest member,
   using the principal's tenant and owner and the live deletion epoch.
3. Read JSONL bytes only in the canonical normalization written by the
   tenant-scoped immutable importer. Each example must contain exactly
   `example_id`, `feature_version`, `features`, and `target`. Require a
   canonical, non-nil assessment UUID in `example_id`, finite numeric
   features, nonempty target/version, and unique IDs.
4. Match the **exact set** of JSONL example IDs with the manifest members
   whose `split=train`. Reject missing/extra assessment rows and any
   `dev`/`test` member in the training input. This checks declarations
   only; a later step must compare these rows with the actual keyed fit
   receipt and canonical import file readback.
5. Run full live preflight again after parsing, including fresh source
   receipts and deletion epoch. Reject revoked/missing evidence, changed
   manifest/dataset/evidence digests or principal drift.
6. Return only counts and SHA-256 digests. No raw private example IDs,
   supervised labels, features, rights receipts or source text are returned.

## Required false claims

A successful result sets
`frozen_assessment_membership_consistent=true` and
`evidence_current_at_inspection=true` only for this inspection window.

The following remain **false**:

- `training_rows_independently_attested`
- `source_to_feature_transformation_verified`
- `source_ancestry_verified`
- `actual_fit_membership_verified`
- `training_example_inventory_verified`
- `training_evaluation_disjointness_verified`
- `independent_oracle_verified`
- `training_authorized`, `execution_authorized`,
  `general_skill_certified`

Even a completely successful read-only preflight is not an atomic
training-start or model-promotion fence. It cannot guarantee ongoing rights
or revocation clearance after return.

## Proof and limits

`tests/core/learning/test_kcm_sklearn_assessment_join.py` covers canonical
data, exact train partition, dev/test contamination, missing or duplicate
IDs, malformed/nested JSON, nonnumeric features, forged feature/target data
with matching IDs, cross-owner scope, lost sessions, rights revocation,
epoch change during the second preflight and stale manifest hashes.

The canonical KCM PostgreSQL governance workflow runs these portable tests
alongside its real RLS and deletion epoch tests. Its fake test authorities are
test fixtures, not evidence that production rights approval has been granted.

## Next stage

The next gate requires a governed, immutable transformation receipt proving
exact assessment/source revision/content to feature/target derivation and
an independently controlled training dataset byte identity. Then compare
all observed fit HMAC member/content commitments to the trusted snapshot
using the existing `consumption_evidence` hash algorithm and the owner-scoped
model/job/artifact reconciliation result. Recheck actual source rights and
deletion epochs within a durable training-job lease at training start and
promotion. Only independent benchmark source/group disjointness checks can
later establish held-out independence.

Do not activate KCM training, model promotion or autonomous execution on
the strength of this structural join.
