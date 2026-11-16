# 16 | Development progress and acceptance

[← Index](README.md) · [Previous](15-research.md)

**Feature name:** `karen-consciousness-model` (**KCM**).

## First code slice: containment + non-promoting admission

The initial pull request is intended to add:

- Containment of legacy `EchoPolicyEngine` importance/retention-only training queueing. `DefaultEchoCoreManager` must reject unsafe `should_queue_training` requests even from legacy or injected policy engines.
- `echocore/training_admission.py`, a deterministic, side-effect-free evaluator that produces policy-blocked, needs-verification, review, or approved decisions, **but never queues or executes training**.
- Purpose-scoped, source-version-bound evidence resolved through a **trusted host-owned port**, not through user-controlled `metadata["verified"]` or an LLM's confidence.
- Fail-closed checks for training consent, rights, tenant/user binding, privacy/taint, source validity, target verification, provenance, and independent quality dimensions.
- Focused regression tests for high-importance LTM, privacy vetoes, disabled-by-default admission, forged metadata, cross-tenant evidence, missing verification, poor quality, and resolver failure.

**Not included:** model training, LoRA, KCM runtime self-projection, dataset manifests persisted to PostgreSQL, UI, or automatic model promotion.

## Proof ledger

| Proof item | Status |
|---|---|
| Independent admission evaluator: isolated local tests | 12 passing in development sandbox; not full-repo CI |
| Legacy ingest containment regression suite | Authored; requires repository test/CI execution |
| `python -m compileall src` on live repository | Not run |
| Full `pytest tests/ -q` on live repository | Not run |
| `ruff check`, `mypy` | Not run (not available in isolated sandbox) |
| Runtime provider/routing/fallback parity | Not run |
| Security/RBAC, RLS, deletion, lineage | Not yet implemented or verified |
| Live first boot / full GitHub checks | Not yet verified |

## Follow-up development

1. Wire the evaluator to trusted tenant-scoped consent/evidence/outcome stores and emit immutable decision audit receipts.
2. Extend canonical dataset owner with source-version/consent ancestry, immutable manifests and RLS.
3. Implement KCM operational self-model projection from current cognitive, memory and skills evidence with *no weight training*.
4. Benchmark compact adapters offline only after the dataset and governance gates pass.

Approval is not proof of training. Only an independently authorized and lineage-backed training job may consume an approved dataset.
