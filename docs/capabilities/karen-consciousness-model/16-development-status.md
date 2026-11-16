# 16 | Development progress and acceptance

[← Index](README.md) · [Previous](15-research.md)

**Feature name:** `karen-consciousness-model` (**KCM**).

## First code slice: containment + non-promoting admission

Draft implementation: [PR #915](https://github.com/agustealo/AI-Karen/pull/915). The pull request is **not merged**.\n\nThe initial pull request adds:

- Containment of legacy `EchoPolicyEngine` importance/retention-only training queueing. `DefaultEchoCoreManager` must reject unsafe `should_queue_training` requests even from legacy or injected policy engines.
- `echocore/training_admission.py`, a deterministic, side-effect-free evaluator that produces policy-blocked, needs-verification, review, or approved decisions, **but never queues or executes training**.
- Purpose-scoped, source-version-bound evidence resolved through a **trusted host-owned port**, not through user-controlled `metadata["verified"]` or an LLM's confidence.
- Fail-closed checks for training consent, rights, tenant/user binding, privacy/taint, source validity, target verification, provenance, and independent quality dimensions.
- Focused regression tests for high-importance LTM, privacy vetoes, disabled-by-default admission, forged metadata, cross-tenant evidence, missing verification, poor quality, and resolver failure.

**Not included:** model training, LoRA, KCM runtime self-projection, dataset manifests persisted to PostgreSQL, UI, or automatic model promotion.

## Proof ledger

| Proof item | Status |
|---|---|
| Independent admission evaluator: isolated local tests | 13 passing in development sandbox; not full-repo CI |
| Legacy ingest containment regression suite | Authored; requires repository test/CI execution |
| `python -m compileall src` on live repository | Not run |
| Full `pytest tests/ -q` on live repository | Not run |
| `ruff check`, `mypy` | Not run (not available in isolated sandbox) |
| Runtime provider/routing/fallback parity | Not run |
| Security/RBAC, RLS, deletion, lineage | Not yet implemented or verified |
| Live first boot / full GitHub checks | Not yet verified |

## Canonical configuration (default fail-closed)

The existing `src/ai_karen_engine/config/learning.py` owns KCM admission switches. Environment overrides are validated and startup fails on malformed values:

| Environment variable | Default | Purpose |
|---|---|---|
| `KCM_TRAINING_ADMISSION_ENABLED` | `false` | Activate **read-only assessment**, not model training |
| `KCM_TRAINING_MIN_QUALITY` | `0.82` | Proposed overall quality minimum |
| `KCM_TRAINING_MIN_CORRECTNESS` | `0.90` | Independent target correctness floor |
| `KCM_TRAINING_MIN_PROVENANCE` | `0.80` | Independent provenance quality floor |

Enabling admission does not enable training, dataset creation, or checkpoint promotion. No live training path is connected by this slice. Thresholds remain experimental until calibrated on held-out evidence.

## Follow-up development

1. Wire the evaluator to trusted tenant-scoped consent/evidence/outcome stores and emit immutable decision audit receipts.
2. Extend canonical dataset owner with source-version/consent ancestry, immutable manifests and RLS.
3. Implement KCM operational self-model projection from current cognitive, memory and skills evidence with *no weight training*.
4. Benchmark compact adapters offline only after the dataset and governance gates pass.

Approval is not proof of training. Only an independently authorized and lineage-backed training job may consume an approved dataset.


## KCM-01B: Governed PostgreSQL source and consent verification (draft)

- A read-only resolver verifies canonical memory-event UUID, payload SHA-256 revision, owner tenant/user scope, active retention and no superseding event.
- Requires the newest current grant of the purpose-specific scope named kcm.training.<objective>. General memory-write consent is insufficient.
- Performs source and consent reads under one transaction with both tenant and user RLS context and explicit query predicates.
- Does NOT infer data rights or target correctness from LTM admission, execution success or consent. Their receipts are absent; this resolver cannot approve training.
- Unit tests cover valid source reference, consent missing/denied/revoked, sensitive and superseded events, stale digest, malformed scope and no accidental approval.
- Local isolated SQLAlchemy-compatible test doubles pass; real PostgreSQL RLS and full exact-head CI are separate acceptance requirements.
- No user-facing API, database migration, model training, or provider/runtime changes. Admission remains default-disabled.

**Follow-up:** independently verified rights and target receipts, dataset manifest lineage, retraining/revocation fencing, and live PostgreSQL RLS tests before any promotion.
