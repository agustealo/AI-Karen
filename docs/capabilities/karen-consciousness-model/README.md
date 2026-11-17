# Karen Consciousness-Model (KCM) | Developer Wiki

**Status:** Governed learning-admission, memory revocation and self-model foundations merged. KCM benchmark provenance, task conditioning and runner-time freshness are merged through PR #961. Scoped curated-oracle reviewer acknowledgment is merged in PR #963. Reviewer withdrawal is merged in PR #968. Owner-scoped model-to-training-job provenance is under review in PR #973; independently verified training-example inventory, ground truth, held-out task-group separation, production environment certification and neural training remain disabled.  
**Research cutoff:** 2026-11-16  
**Repository baseline audited:** `agustealo/AI-Karen` `main` at `24621fccd0f7d5b065408f406ecc0f82d02d8573` (read-only model/job provenance branch base)  
**Target documentation location:** `docs/capabilities/karen-consciousness-model/`  
**Primary decision:** Memory retention **does not** confer training eligibility.

## Executive decision

KCM is Karen's **operational self-model**: a governed, evidence-backed projection of identity/persona configuration, demonstrated skills, lessons, capabilities, limitations and knowledge provenance. It is not a consciousness claim, a second memory store, a new reasoning router, or a replacement for LLMs. The existing CORTEX/RuntimePolicy/ChatRuntime/MemoryRuntime remain authoritative. EchoCore selects training evidence and may train optional small model adapters. The live KCM state is sourced from current authoritative systems, not reconstructed from neural weights.

### Invariants

1. **One owner per responsibility:** `core/memory` owns memory semantics and governed writes; EchoCore owns training admission and dataset assembly; model registry owns published model identity; CORTEX decides, RuntimePolicy authorizes, ChatRuntime executes.
2. **Separate the three questions:** (a) Keep this memory? (b) Is this evidence sound? (c) Is it useful and authorized for a *specific* training objective?
3. **Never train automatically from LTM, repeated recall, importance, or a model's own confident answer.**
4. **Use current user state as retrieval, not baked-in user weights by default.** Personal memories can be revoked; parameter influence is much harder to remove.
5. **No autonomous model promotion.** Training, assessment, approval, deployment and rollback have distinct receipts.
6. **No cross-tenant aggregation without an explicit, separately authorized and technically enforced data-sharing policy.** Default is isolation.
7. **No silent success:** Failed memory writes, dataset creation, training, evaluation, or checkpoint installation remain failed/unavailable, never mock success.
8. **Operational self-model is not subjective consciousness.** Evaluate self-knowledge and metacognitive calibration empirically.

## Navigation

| Page | What it establishes |
|---|---|
| [01 — Mission, scope and terminology](01-mission-scope.md) | KCM semantics and non-goals |
| [02 — Live repository audit](02-repository-audit.md) | What exists, duplicate hazards, specific defects |
| [03 — Architecture and ownership](03-architecture.md) | Components, read/write/train flows, trust boundaries |
| [04 — Memory eligibility vs. learning eligibility](04-admission-policy.md) | Hard gates and states |
| [05 — Quality scoring and selection](05-quality-selection.md) | Objective-specific metrics, weights, coverage, outcomes |
| [06 — Data contracts, provenance and schema](06-contracts-and-lineage.md) | Typed contracts, records, dataset manifests and lineage |
| [07 — Data curation and dataset building](07-datasets-and-curation.md) | Splits, deduplication, positive/negative examples |
| [08 — Training, adapters and model lifecycle](08-training-and-models.md) | SFT/LoRA, model selection, checkpoint promotion |
| [09 — Operational self-model and capability mastery](09-self-model.md) | Persona, knowledge and skill assessments |
| [10 — Security, privacy, revocation and unlearning](10-governance-security.md) | RBAC, poisoning defense and lineage-aware deletion |
| [11 — Evaluation and regression prevention](11-evaluation.md) | Benchmarks, gates, calibration, adversarial tests |
| [12 — Observability, operations and developer UX](12-operations-ui.md) | Metrics, audit events, Admin surfaces, failure modes |
| [13 — Implementation phases and proof](13-delivery-plan.md) | Release slices, file touchpoints, CI and go/no-go |
| [14 — Architecture decisions and trade-offs](14-decisions.md) | ADRs, rejected designs, outstanding choices |
| [15 — Research and references](15-research.md) | Primary literature, standards and implementer sources |
| [16 — Development progress and acceptance](16-development-status.md) | Actual merged PRs, exact-head verification, outstanding gates |
| [17 — Dataset evidence preflight](17-evidence-preflight.md) | Fresh rights/outcome/consent receipt checks and revocation constraints |
| [18 — Durable revocation and source lineage](18-durable-revocation-lineage.md) | Owner-scoped epoch, source ancestry and incomplete integration gates |
| [19 — Memory, consent and erasure lifecycle hooks](19-memory-consent-erasure-hooks.md) | Atomic revocation on canonical source changes; live PostgreSQL acceptance |
| [20 — Operational self-model projection](20-operational-self-model-projection.md) | Canonical SelfModel, evidence verification, skill/identity separation and health |
| [21 — Canonical system Persona evidence](21-canonical-persona-evidence.md) | Real built-in Persona configuration, exact claim binding, drift and limits |
| [22 — Reviewed decision evidence](22-reviewed-decision-evidence.md) | Scoped independent decision review, no skill mastery or training grant |
| [23 — Task-specific benchmark assessment](23-task-specific-benchmark-assessment.md) | Exact model/feature/case provenance, observed test accuracy and uncertainty |
| [24 — Conditioned benchmark and expiry](24-conditioned-task-evidence.md) | Canonical curated oracle integrity, group limits, environment truth and required freshness |
| [25 — Runner observation and evidence age](25-run-observation-and-freshness.md) | Runner-observed inference window, receipt replay fencing, freshness-bound diagnostics |
| [26 — Reviewed oracle observations](26-reviewed-curated-oracle-observations.md) | Tenant-scoped authorized reviewer acknowledgment, exact source snapshot, no independent group certification |
| [27 — Reviewer withdrawal](27-reviewer-withdrawal-and-revocation.md) | Append-only reviewer withdrawal and revocation-aware task evidence without permission grants |
| [28 — Model/job artifact provenance](28-model-training-job-lineage.md) | Exact owner-scoped training job and registry hash link, explicitly not held-out evidence |
| [29 — sklearn fit observation](29-sklearn-fit-observation.md) | Keyed tenant-scoped observation of actual sklearn fit members, explicitly not verified KCM source inventory |

### Machine-readable proposed contracts

- [`schemas/kcm_training_candidate.schema.json`](schemas/kcm_training_candidate.schema.json)
- [`schemas/kcm_dataset_manifest.schema.json`](schemas/kcm_dataset_manifest.schema.json)
- [`examples/kcm_training_candidate.example.json`](examples/kcm_training_candidate.example.json)
- [`examples/kcm_dataset_manifest.example.json`](examples/kcm_dataset_manifest.example.json)

Schemas/examples are **design contracts**, not evidence that database tables or APIs exist.

## Reading order for implementation

Read 02 -> 03 -> 04 -> 05 -> 06 -> 10 -> 11 -> 13. Use 07/08 for training, 09 for runtime self-model projection, and 12 for operations/UI. Nothing in this package authorizes a code modification or deployment by itself.

## Minimal build acceptance

- A high-value `NO_TRAINING` LTM is never trainable.
- An unknown, contested, expired or poisoned memory cannot become a positive supervision label.
- A correctly verified but low-importance procedural correction can be considered for an appropriate skill objective.
- A negative example never becomes an unqualified positive target.
- Tenant-A data cannot be listed, exported, scored or trained under Tenant-B credentials.
- Deleting a memory prevents future training and identifies all affected artifacts/checkpoints. Production model usage is fenced until remediation.
- Dataset and model promotion use independent, frozen evaluation suites and explicit human/authorized policy approval.

> **Non-production notice:** The code foundation is merged but only supplies read-only inspection and training admission gates. No model was trained or approved, and there is no deployed KCM consciousness runtime. Exact-head security and integration gates remain mandatory for each subsequent change.
