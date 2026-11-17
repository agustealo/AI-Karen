# 16 | Karen Consciousness-Model development status

[← Index](README.md) · [Previous](15-research.md) · [Next →](17-evidence-preflight.md)

**Feature:** `karen-consciousness-model` (KCM)

**Architecture:** CORTEX decides, RuntimePolicy authorizes, ChatRuntime executes.
NeuroVault/NeuroRecall govern memory; EchoCore evaluates potential training
evidence. Memory promotion is never model-training permission.

## Merged foundations

| Slice | Repository evidence | Status |
|---|---|---|
| KCM-01A/B: memory-to-training containment, read-only admission, tenant-scoped memory/consent verification | [PR #915](https://github.com/agustealo/AI-Karen/pull/915), merge `9a1ee696ddaa7b6d2d36ad3cac632033e1c1a757` | Merged; exact-head 13/13 checks passed |
| KCM-01C: immutable frozen-manifest/dataset integrity inspection and schema alignment | [PR #924](https://github.com/agustealo/AI-Karen/pull/924), merge `8821b72c53a101555567349ba941563c5359daf0` | Merged; exact-head 6/6 GitHub Actions checks passed |
| KCM-01D1: fresh provenance and rights/target receipt revalidation | [PR #930](https://github.com/agustealo/AI-Karen/pull/930), merge `b1baefb781de9d7eaa2fd446d570ab6e42a64397` | Merged; 6/6 exact-head GitHub checks passed |
| KCM-01D2A: durable owner-scoped revocation epoch and source ancestry | [PR #931](https://github.com/agustealo/AI-Karen/pull/931), merge `ee4629f666fa291df9081f95d5979a363e88f568` | Merged; 12/12 exact-head checks passed, real PostgreSQL proof |
| KCM-01D2B: canonical memory, consent and privacy SQL revocation hooks | [PR #938](https://github.com/agustealo/AI-Karen/pull/938), merge `99a7ee5e4c6445496c8584d80ddc3ef355b20580` | Merged; 12/12 exact-head checks passed, live PostgreSQL proof |
| KCM-02A: canonical evidence-gated SelfModel projection | [PR #940](https://github.com/agustealo/AI-Karen/pull/940), merge `edc5ce785f25f6727a6c96ab13890aaad26ca44d` | Merged; 8/8 exact-head checks passed |
| KCM-02B1: current built-in Persona configuration and exact claim bindings | [PR #946](https://github.com/agustealo/AI-Karen/pull/946), merge `b10e27d030c4ab35438af9917b6521371fcbfd41` | Merged; 8/8 exact-head checks passed |
| KCM-02B2: scoped independently reviewed verification-policy decision evidence | [PR #951](https://github.com/agustealo/AI-Karen/pull/951), merge `c8544ef54afbebfd8ed99bccbbf76c8527ec1b67` | Merged; 8/8 exact-head checks passed |
| KCM-02B3A: exact ML task benchmark artifact and evaluated case projection | [PR #953](https://github.com/agustealo/AI-Karen/pull/953), merge `7abce8006c973906ba3e90aa3b4915cfb8550a2a` | Merged; 11/11 exact-head checks passed |
| KCM-02B3B: conditioned curated-oracle source and assessment expiry | [PR #956](https://github.com/agustealo/AI-Karen/pull/956), merge `a1188e594201e0713cc6a16833a5acc1f4ae40ae` | Merged; 19/19 exact-head checks passed; source integrity and issuer freshness only |
| KCM-02B3C1: runner-observed inference window and receipt replay fencing | [PR #961](https://github.com/agustealo/AI-Karen/pull/961), merge `69d62965550f79f964cc9850283dfcb868cc1f4f` · [25 — Runner observation](25-run-observation-and-freshness.md) | Merged; 18/18 exact-head checks passed; runner observation is not signed production attestation |
| KCM-02B3C2A: owner-scoped curated-oracle reviewer observation | [PR #963](https://github.com/agustealo/AI-Karen/pull/963), merge `25ee6b58a38e4f49049db201072f1a588cf77705` · [26 — Reviewer observations](26-reviewed-curated-oracle-observations.md) | Merged; 24/24 exact-head checks passed, no independent group/ground truth/execution claim |
| KCM-02B3C2B: append-only original-reviewer withdrawal and revocation-aware reads | [PR #968](https://github.com/agustealo/AI-Karen/pull/968), merge `24621fccd0f7d5b065408f406ecc0f82d02d8573` · [27 — Reviewer withdrawal](27-reviewer-withdrawal-and-revocation.md) | Merged; 25/25 exact-head checks passed; no administrative override or training permission |
| KCM-02B3C3A: owner-scoped training-job to model artifact verification | [PR #973](https://github.com/agustealo/AI-Karen/pull/973), merge `c300198f1eee6b6775ed46f1eb51c51a8ba9b5c4` · [28 — Model/job provenance](28-model-training-job-lineage.md) | Merged; 11/11 exact-head checks passed; no example-inventory or benchmark-independence claim |
| KCM-02B3C3B1: keyed sklearn fit-membership observation | [PR #981](https://github.com/agustealo/AI-Karen/pull/981), merge `c2025a5abb7d9246b9853e7f1a4989d19ef5a67d` · [29 — Sklearn fit observation](29-sklearn-fit-observation.md) | Merged; 18/18 exact-head checks passed; bounded default-off worker assertion only, no KCM training inventory |
| KCM-02B3C3B2: owner-scoped model-job-bound fit receipt | [PR #984](https://github.com/agustealo/AI-Karen/pull/984), merge `7b1cf8d78e402fe32c14029dccd521f6aa05af7b` · [30 — Owner-scoped fit binding](30-owner-scoped-fit-artifact-binding.md) | Merged; 11/11 exact-head checks passed; no verified KCM inventory or source ancestry |
| KCM-02B3C3B3A: frozen assessment to sklearn row alignment | [PR #987](https://github.com/agustealo/AI-Karen/pull/987), merge `26c6d76ac51a0dd69a6d5d2dfd836c698bbf322b` · [31 — Frozen assessment-to-JSONL alignment](31-frozen-assessment-to-sklearn-jsonl.md) | Merged; 9/9 exact-head checks passed; structural train UUID alignment with current rights/epoch evidence only |
| KCM-02B3C3B3B: keyed fit-to-input commitment concordance | [PR #989](https://github.com/agustealo/AI-Karen/pull/989), merge `e1fdd64503bfb5997ed846fc725ef4b12d17c576` · [32 — Fit input commitments](32-observed-fit-input-commitments.md) | Merged; 12/12 exact-head checks passed, clean review; supplied snapshot HMAC concordance only |
| KCM-02B3C3B4A: canonical tenant import byte readback | [33 — Canonical import readback](33-canonical-tenant-training-readback.md) | Candidate; nofollow, bounded, exact file SHA-256 and input row readback; no independently signed expected digest, actual worker-byte or source lineage proof |

## Configuration

The single source of learning configuration is
`src/ai_karen_engine/config/learning.py`.

| Environment variable | Default | Meaning |
|---|---|---|
| `KCM_TRAINING_ADMISSION_ENABLED` | `false` | Opt into **read-only assessment**, not model training |
| `KCM_TRAINING_MIN_QUALITY` | `0.82` | Experimental overall quality floor |
| `KCM_TRAINING_MIN_CORRECTNESS` | `0.90` | Experimental verified-target correctness floor |
| `KCM_TRAINING_MIN_PROVENANCE` | `0.80` | Experimental provenance floor |
| `KCM_BENCHMARK_MAX_EVIDENCE_AGE_SECONDS` | `2592000` (30 days) | Read-only benchmark evidence expiry; range 1..31536000 |

Neither these settings nor a successful evidence inspection can trigger model
training, model installation, parameter updates or checkpoint promotion.

## Uncompleted acceptance requirements

1. **Authoritative rights and outcome receipts:** The existing memory consent
   table proves only purpose-scoped consent; it is not a training license.
   Ordinary runtime tool success and user feedback do not establish correct
   supervision targets. Governed rights and independent target review must be
   introduced with actual approval and revocation receipts.
2. **Dataset-to-model ancestry:** Tenant-RLS source-to-dataset ancestry is
   merged. Immutable manifest persistence, checkpoint ancestry, independent
   signed attestations and model lineage remain unimplemented.
3. **Training-start and promotion fencing:** Durable deletion epochs and source
   revocation exist. Canonical lifecycle hooks are in development, but a
   transactionally fenced training-start and model promotion lease remains
   unimplemented; preflight epoch reads are not an atomic training lock.
4. **Operational self-model projection:** The canonical SelfModel contract
   and KCM-02A read-only evidence projector are merged. KCM-02B1 adds
   canonical built-in Persona configuration reads and property-bound receipts.
   No production user-scoped model, skill certification reader, or KCM runtime
   integration has been activated.
5. **Model training/evaluation:** No KCM neural weights or Persona adapters
   were trained, approved or deployed.

## Required proof

Every PR requires exact-head CI, unit tests, source-reference audit and
appropriate PostgreSQL RLS integration tests. Any training release further
requires data-rights verification, immutable source-to-model lineage, verified
held-out evaluation, rollback and erasure/unlearning governance. Do not treat
documentation, tool mocks, or independently verified subset tests as live
database or production readiness proof.

**Next controlled slice:** Read the canonical tenant-scoped JSONL
import through a bounded nofollow file descriptor, compare the exact
stored bytes with a separately expected SHA-256 and feed a snapshot into
the existing keyed fit-row HMAC comparison. This is a snapshot read, not
proof of the expected hash's independent authority or proof that sklearn
loaded those bytes during its actual fit. Separately governed source
revision-to-feature/target transformation receipts, worker-observed file
digest binding, and a durable rights/deletion-epoch training/promotion
lease remain unimplemented. Independent benchmark exclusion, training
authorization and general-skill certification stay disabled.
