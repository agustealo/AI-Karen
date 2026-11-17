# 28 | KCM-02B3C3A: Exact model to training-job artifact provenance

[← Developer wiki](README.md) · [Previous](27-reviewer-withdrawal-and-revocation.md)

## Objective

Before Karen can verify that benchmark tasks were held out from training,
the runtime must identify **which actual governed job produced which registered
model artifact**. This slice establishes only that first, narrower link.
It does **not** claim access to training examples, immutable sample inventory,
train/test non-overlap, independent oracle correctness, general skill mastery
or permission to execute/train models.

## Canonical owners

- `TrainingJobLedger` is the durable canonical training state owner. Its
  optional `user_id` filter narrows existing `get` queries with an exact
  tenant+owner predicate; existing internal tenant-scoped worker calls do not
  change.
- `MLModelRegistry` remains the model manifest and artifact-hash owner.
- `TrainingArtifactReconciler` remains the sole job-to-artifact reconciliation
  service. Its new `inspect_exact_model_lineage` is a read-only,
  user-scoped diagnostic; there is no new KCM store, training execution path,
  route-level model selector or policy router.
- `AuthenticatedPrincipal` must come from the trusted auth boundary, contain
  an active session, and remain non-expired.

## Positive evidence requirements

An exact current model-to-job diagnostic is available only when all the
following are proved from those owners:

1. The tenant model namespace matches the SHA-256-derived tenant key.
2. The manifest contains a training job ID and recorded tenant key, explicit
   tenant scope and training dataset version.
3. The **owner-scoped ledger row** identifies that same job and reports a
   completed `SUCCEEDED` state, not a pending or failed training attempt.
4. Persisted job metadata and approved configuration both select the tenant
   dataset scope. The task, exact dataset version, artifact path and artifact
   SHA-256 agree with the current registered model.
5. The artifact directory is inside the configured registry root. The bounded,
   non-symlink `training_metadata.json` identifies the same job, model,
   version, tenant key and dataset version. No pickle, model weights, arbitrary
   Python modules or downloaded code are executed to read it.
6. `MLModelRegistry.validate_artifact` re-hashes actual artifact bytes.
   The ledger and registry are read again and the artifact is re-hashed before
   producing a diagnostic. Missing, inconsistent or changed evidence is
   unavailable, never assumed successful.

The response identifies only the exact owner, tenant, job, model, revision,
dataset **version** and artifact digest. It contains no raw prompts, labels,
training samples or sensitive dataset rows.

## Explicitly false claims

Every positive `ScopedTrainingArtifactLineage` result still has:

- `training_example_inventory_verified=false`
- `training_evaluation_disjointness_verified=false`
- `independent_oracle_verified=false`
- `general_skill_certified=false`
- `training_authorized=false`
- `execution_authorized=false`

A dataset *version string* and a runner-reported test sample count cannot prove
which examples trained a model or whether benchmark cases leaked into the
training set. A version is only a lookup key.

The current canonical spaCy executor does not embed a comparable immutable
`training_metadata.json` identity contract and therefore cannot pass this
positive diagnostic yet. Legacy artifacts without owner scope or exact
training-job metadata also remain unavailable.

## Limits

This is a read-only, process-local reconciliation and not an atomic PostgreSQL
training-start lock or a cryptographically independent attestation. A trusted
administrator could mutate files and metadata between reads; KCM may never
treat this result as source rights, consent, revocation clearance or capability
certification.

## Test and release gate

The dedicated KCM proof and existing training tests must cover owner-scoped
ledger reads, real successful transactional job-state transitions, matching
registry model and actual hashed file metadata, wrong owner/tenant/session,
expired principal, tampered model bytes, tampered job ID, and post-verification
artifact drift.

This slice is ready for acceptance only after **exact-head CI and code review**
pass. No runtime API or consumer UI displays a generalized proficiency score.

## Next evidence boundary

Prove the *exact actual training-example membership* of that job, including
canonical per-item source/content hashes and immutable split assignments,
then compare it to benchmark input/source ancestry with governed independent
review and withdrawal support. `kcm_dataset_integrity.py` already validates
frozen manifest membership but does not itself establish a model trained on
that manifest. Avoid creating a second store or assuming catalog labels prove
disjointness.
