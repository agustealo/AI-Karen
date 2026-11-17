# 29 | KCM-02B3C3B1: Recorded sklearn fit membership (partial)

[← Developer wiki](README.md) · [Previous](28-model-training-job-lineage.md)

## Objective and boundary

This first part of the consumed-training-inventory project observes **which
loaded sklearn examples were selected for the actual `model.fit` partition**.
It is a bounded, optional worker assertion, not an independently attested
training example inventory or any proof of independent evaluation.

The existing `SklearnTrainingExecutor` now carries original list indices
through the same stratified `train_test_split` used by `model.fit`. After fit
succeeds, it can write a keyed, canonical, non-plaintext
`training_consumption.json` receipt into the *existing artifact directory*.
`training_metadata.json` records its SHA-256 and key ID. The canonical
`MLModelRegistry` hashes both files into the model artifact. No new job
ledger, registry, orchestrator, evaluator, route, or UI is introduced.

## Explicit opt-in configuration

Both credentials and a true feature toggle must be provided to the existing
canonical `LearningSettings` authority:

| Environment | Default | Contract |
|---|---|---|
| `KCM_SKLEARN_FIT_OBSERVATION_ENABLED` | `false` | Enable recording only for explicit tenant-scoped sklearn jobs |
| `KCM_SKLEARN_FIT_OBSERVATION_KEY_ID` | unset | Nonempty 1–64 character ASCII identifier with letters, digits, `._-` |
| `KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY` | unset | Host-managed 32-byte secret, encoded as exactly 64 hexadecimal characters |

A missing or invalid key when enabled fails closed; the secret is retrieved
when needed, never serialized into the learning settings object, logged,
included in the job metadata, or copied into the model artifact. Key rotation
requires keeping older authorized keys available to validate earlier receipts;
until that exists, old receipt verification is unavailable when the key changes.
Never treat failure to configure this feature as training authorization.

## Observation contract

`training_consumption.json` uses exact schema
`kcm-sklearn-fit-observation-v1`. It contains:

- Owner-independent tenant namespace key, model/job IDs and versions, dataset
  lookup version, feature version, split seed, key ID, and fit/holdout counts
- Sorted, unique HMAC-SHA256 identities of the **actual selected example IDs**
  and separate HMAC-SHA256 content commitments over selected example ID,
  feature version, numeric feature values and supervised target
- A domain-separated HMAC-SHA256 seal for the entire canonical JSON receipt
- All skill, permissions, source ancestry, independent execution, and
  evaluation-disjointness claims permanently false

Raw `example_id`, original features, target labels, prompts, or source text
are not included. Receipt size is bounded to 4 MiB and 10,000 examples, with
nonempty fit and holdout partitions. Duplicate sample IDs, incomplete
partitions, invalid keys, cross-tenant/job/model/version reads, malformed JSON,
HMAC tampering, noncanonical encoding and unexpected positive grant flags
fail closed. Existing non-KCM jobs run without these receipts.

The `inspect_sklearn_fit_observation` helper validates the keyed receipt and
returns only counts, key ID and digest, while keeping
`training_example_inventory_verified=false`. It does not independently
replay the trainer or authenticate a source dataset. It is not yet exposed
as a user-facing KCM diagnostic. A signed local assertion is not an off-host
attestation against a malicious privileged worker or host administrator.

## Proof

`tests/core/intelligence/test_training_fit_observation.py` exercises the
real sklearn executor and independently reconstructs the exact fit/holdout
partition, verifies the artifact hash includes the observation, and checks
legacy default-off behavior. Additional tests cover duplicate IDs, wrong
scope/job/key, old key rotation, incomplete partition, malformed/nested JSON,
tampering, and attempted grant-flag forgery.

The KCM PostgreSQL proof runs the portable keyed-receipt tests; the Training
Engine Proof runs the real sklearn integration using the existing worker
dependencies. Merge only after exact-head CI, independent review, and live
main reconciliation.

## What remains blocked

This slice does **not** prove that `example_id` is globally unique,
originated from a verified source revision, or cannot be fabricated by the
loader. A training job can load a preexisting dataset without KCM consent,
rights, deletion epoch, group ancestry or immutable source manifest evidence.
The receipt alone therefore cannot be used to assert exact KCM training
example inventory, benchmark holdout independence, independent oracle
correctness, environment attestation, general-skill mastery or permission
to train/promote/execute.

**Next stage:** join the private observed membership to independently governed
frozen KCM source ancestry, using the existing `kcm_dataset_integrity`,
`kcm_dataset_preflight`, revocation/epoch owner, `TrainingJobLedger`,
`TrainingArtifactReconciler` and model registry. Extend supported engines
individually at their real consumption boundaries (spaCy updates, temporal
input/target windows, and LoRA optimizer steps). Require immutable owner-scoped
readback and revocation checks before any stronger verified-inventory flag.
