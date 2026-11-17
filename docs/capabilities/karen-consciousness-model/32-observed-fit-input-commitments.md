# 32 | KCM-02B3C3B3B: Keyed observed-fit input snapshot concordance

[← Developer wiki](README.md) · [Previous](31-frozen-assessment-to-sklearn-jsonl.md)

## Exact proof level

A completed sklearn executor writes a keyed, canonical HMAC receipt containing
the **actual row commitments observed at `model.fit`** and its holdout. Its
existing verifier validates the full scoped receipt, but has not independently
joined the source snapshot to those row commitments.

`inspect_sklearn_fit_input_snapshot` is a **pure, bounded comparison** in
`core/intelligence/ml/training/consumption_evidence.py`. It reuses the
existing HMAC domains, row serialization, and receipt integrity verifier.
It compares the union of recorded train and holdout
`(member_hmac, content_hmac)` pairs against the commitments recomputed
from the supplied `TopologyTrainingExample` snapshot. It rejects a missing
row, extra row, changed ID, target, feature value, feature name, feature
version, duplicate identifier, malformed receipt or incorrect key/tenant/
job/model/dataset identity.

The comparison returns counts, the receipt digest and key identifier only.
It never returns original assessment IDs, supervised labels, raw features,
source text or key bytes.

## Authority and explicit limits

The **supplied snapshot is not authenticated** by this function. The caller
is responsible for independently proving that it read the exact immutable,
tenant-bound dataset bytes relevant to the job. The method does not open
paths, inspect the model registry or ledger, derive training labels, or
resolve owner rights. A key supplied to the helper is not itself evidence
that the host's current authority still trusts it.

A matching receipt can therefore establish only
`receipt_matches_supplied_snapshot=true` for that supplied copy. It does
not establish that the copy was the file consumed during training, that
its features/targets derive from the reviewed assessment source, that the
receipt belongs to a succeeded owner-scoped registered model, or that its
holdout was a genuinely independent benchmark.

The following always remain false:

- `independently_attested_input_bytes`
- `source_to_feature_transformation_verified`
- `source_ancestry_verified`
- `actual_model_artifact_bound`
- `training_example_inventory_verified`
- `training_evaluation_disjointness_verified`
- `independent_oracle_verified`
- `training_authorized`, `execution_authorized`,
  `general_skill_certified`

The existing [owner-bound artifact reconciliation](30-owner-scoped-fit-artifact-binding.md)
and [frozen assessment join](31-frozen-assessment-to-sklearn-jsonl.md) are
distinct prior gates. This helper is **not** a new provenance registry,
router, authorization controller, model runner or persistence engine.

## Adversarial proof

`tests/core/intelligence/test_training_fit_input_snapshot.py` exercises
canonical fit receipts and complete row snapshots, importer-produced tenant
JSONL readback, record reordering, forged labels/features/IDs, duplicate
or incomplete membership, missing or extra records, NaN/unserializable
features, mismatched identities, invalid keys, malformed receipts, and
unbounded input.

The existing real KCM PostgreSQL governance workflow runs these tests
alongside its scoped RLS/epoch proof. Synthetic test IDs and keys do not
constitute production source verification.

## Follow-on mandatory gates

The subsequent stage must implement a governed immutable transformation
attestation binding `assessment_id`, source artifact/revision/content
digest, and actual features/target to an authorized training snapshot,
then verify the exact file byte digest consumed by the worker. Combine
that trusted snapshot with the successful tenant/owner job, registered
artifact, current key authority and observed fit receipt under a
durable revocation and training-job lease. Verification must fail closed
on source deletion, rights/consent revocation, changed source revision,
registry/ledger drift and model-promotion fencing.

Independent benchmark-group/source disjointness needs its own objective
and held-out oracle evidence. No claim of training permission or general
skill certification is permitted before those gates exist.
