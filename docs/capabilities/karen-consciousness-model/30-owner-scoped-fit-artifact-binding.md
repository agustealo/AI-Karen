# 30 | KCM-02B3C3B2: Owner-scoped observed-fit artifact link

[← Developer wiki](README.md) · [Previous](29-sklearn-fit-observation.md)

## Purpose

KCM-02B3C3A proved the owner-scoped successful training-job to model-artifact
link. KCM-02B3C3B1 added a keyed, private `sklearn` worker observation of
which input rows it passed to `model.fit`. This stage reconciles **both
facts** through the existing `TrainingArtifactReconciler`, rather than
creating a second ledger or treating any unbound receipt as evidence.

**This is not governed source ancestry.** No immutable KCM source manifest,
source rights, consent evidence, current deletion epoch, or benchmark family
disjointness is verified here. The result never sets the KCM
`training_example_inventory_verified` flag to true.

## Canonical owner

`src/ai_karen_engine/core/intelligence/ml/training/artifact_reconciliation.py`
now exposes `inspect_exact_sklearn_fit_artifact`, requiring an actual
`AuthenticatedPrincipal` from the trusted authentication boundary and an
exact `model_id`. The method delegates both its initial and final job/model
proofs to the existing `inspect_exact_model_lineage`. It never executes
a model, reads pickle, updates model status, creates a job, trains, or writes
a receipt.

The same `LearningSettings` key toggle from Chapter 29 governs whether the
keyed observation can be read. A missing, invalid, or rotated host key fails
closed and is never logged.

## Read-only acceptance criteria

The observer returns a private, frozen summary only if all steps succeed:

1. Original owner- and tenant-scoped `SUCCEEDED` job, registered model,
   artifact path and full artifact content hash match.
2. The canonical training job explicitly identifies the `sklearn` engine
   and the existing tenant-scoped dataset selection. Registry and job metrics
   agree on the declared receipt SHA-256 and key ID.
3. Bounded `training_metadata.json` contains the same receipt digest,
   key ID, job ID, model ID, model version and dataset version.
4. Bounded `training_consumption.json` is read only as an ordinary
   non-symlink file, under the already verified artifact directory. The
   bytes match the declared digest and the original keyed, canonical
   `inspect_sklearn_fit_observation` contract verifies them.
5. A second canonical job/model/artifact check succeeds after receipt read.
   The original owner-scoped job record, registry snapshot, and authenticated
   session are unchanged when the result is returned.

This is a bounded non-atomic filesystem diagnostic, not a durable transactional
training-start fence or independent remote witness. A privileged host administrator
can still tamper or race with local files. Never use the result as a policy
grant or source-rights attestation.

## Returned information

`ScopedSklearnFitArtifactObservation` exposes only scoped IDs, model and
dataset versions, model hash, fit-receipt hash, key ID, aggregate train and
holdout counts, and inspection time. No raw sample identifiers, labels,
features, source content, or HMAC secrets are returned.

The result explicitly and permanently reports:

- `model_training_job_link_verified=true`
- `fit_observation_artifact_bound=true`
- `worker_observation_integrity_verified=true`
- `source_ancestry_verified=false`
- `independent_fit_verified=false`
- `training_example_inventory_verified=false`
- `training_evaluation_disjointness_verified=false`
- `independent_oracle_verified=false`
- `training_authorized=false`
- `execution_authorized=false`
- `general_skill_certified=false`

No KCM runtime score, general capability, or user-facing readiness badge is
changed. Missing data yields `None`, not a misleading success value.

## Proof and adversarial cases

`tests/core/intelligence/test_training_artifact_reconciliation.py` now
builds real canonical job/registry/hashed artifacts with valid keyed receipts
without requiring a GPU or a live external model. It checks the owner/tenant
scope, actual counts, read-only state, absent receipt/default-off key,
rotated/missing key, altered artifact bytes, symlinked receipt, mutated
registry digest, failed ledger status, principal expiry during a final artifact
hash, and session swap between the two lineage inspections.

The existing `KCM Governed PostgreSQL Proof` workflow compiles and runs
these contract tests, alongside real governance RLS and revocation tests.
The general exact-head release and security review must also pass before merge.

## Required next evidence stage

The frozen KCM manifest provides assessment UUIDs, source revision hashes,
content digests, group labels, split labels, and receipt references. The
`TopologyTrainingExample` / sklearn JSONL provider carries an unrelated,
untrusted `example_id` and feature/target pair, **without a trusted join
contract** to the KCM assessment/source row.

Matching strings or comparing a training dataset version to an immutable
manifest version does **not** establish that the actual training row came
from the claimed source, was consented/rights-cleared, or was not revoked.

Build the next source-join contract in the existing KCM dataset/worker domain:
require a deterministic authenticated example-to-assessment mapping and
per-row digest normalization; verify it against the canonical immutable
manifest's source revision/content/leakage group and fresh
`inspect_kcm_dataset_evidence` preflight through the tenant/owner-scoped
revocation epoch reader. Then bind that approval and a repeatable job lease to
the exact observed fit, checked both at training start and promotion.
Absent this complete proof, `training_example_inventory_verified` remains
false. Benchmark-source disjointness and independent oracle verification are
additional separate later stages.
