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
| KCM-02A: canonical evidence-gated SelfModel projection | [20 — Self-model projection](20-operational-self-model-projection.md) | Development; no production reader or API exposure |

## Configuration

The single source of learning configuration is
`src/ai_karen_engine/config/learning.py`.

| Environment variable | Default | Meaning |
|---|---|---|
| `KCM_TRAINING_ADMISSION_ENABLED` | `false` | Opt into **read-only assessment**, not model training |
| `KCM_TRAINING_MIN_QUALITY` | `0.82` | Experimental overall quality floor |
| `KCM_TRAINING_MIN_CORRECTNESS` | `0.90` | Experimental verified-target correctness floor |
| `KCM_TRAINING_MIN_PROVENANCE` | `0.80` | Experimental provenance floor |

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
   exists and KCM-02A introduces a read-only verified-evidence projector.
   Trusted read adapters, live runtime wiring and measured skill proficiency
   remain unavailable; no self-model runtime has been activated.
5. **Model training/evaluation:** No KCM neural weights or Persona adapters
   were trained, approved or deployed.

## Required proof

Every PR requires exact-head CI, unit tests, source-reference audit and
appropriate PostgreSQL RLS integration tests. Any training release further
requires data-rights verification, immutable source-to-model lineage, verified
held-out evaluation, rollback and erasure/unlearning governance. Do not treat
documentation, tool mocks, or independently verified subset tests as live
database or production readiness proof.

**Next controlled slice:** Prove KCM-02A's no-rival-model, tenant-scoped,
independently verified read contract in exact-head CI. KCM-02B must wire real
source adapters and revocation awareness before any UI can claim readiness.
Training rights, outcome labels, checkpoint ancestry and atomic trainer
start/promotion fencing remain separately blocked.
