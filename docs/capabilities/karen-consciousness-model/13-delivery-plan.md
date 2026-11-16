# 13 | Phased implementation and test-proven handoff

[← Index](README.md) · [Previous](12-operations-ui.md) · [Next →](14-decisions.md)

**Current status:** Documentation and design only. No implementation claim, merge, installation or CI pass.

## P0 — Repository audit, ownership and containment

**Objective:** Stop implicit memory->training promotion and establish truthful baseline without changing general memory behavior.

**Do:** Trace EchoCore ingest/worker consumers; audit existing dataset manager and related endpoints; verify current production feature flags. Replace importance-only enqueue with non-promoting `REVIEW` or explicit training-admission gate; fail closed on absent verification. Disable mock-training success in non-test execution. Prevent tenant-facing access to unscoped dataset APIs.

**Reuse:** `echocore/contracts.py`, `production_fine_tuner.py`, `core/memory/types/base.py`, `core/memory/guards.py`, `config/learning.py`, current auth/RLS systems.

**Avoid:** A new memory owner, a replacement router, blind deletion of legacy components, forcing unrelated runtime changes.

**Proof:** Exact-head reference audit, import/compile tests; no-training/poison/tenant gate tests; any production training dependency missing must fail, not mock complete.

**Risk:** Legacy APIs could depend on current quality score or training queue semantics; use explicit compatibility tests and migration warnings.

## P1 — Governed candidate assessment (no training)

**Objective:** Add one EchoCore-owned `TrainingAdmission` service using existing memory artifact interfaces and security contracts.

**Do:** Version purpose, policy/evaluator; add typed assessment result and audit state; pull verified outcome refs; enforce immutable source/version and tenant scope; implement reason-coded decisions and separate objective-specific scores. Use existing LearningSettings with safe `enabled=false` for training runs.

**Proof:** Deterministic fixtures for all states, consent/license/poison/expiry/contradiction/rights, DB/RLS and audit receipts. Verify all existing memory tiers can remain readable when training is blocked.

**Exit:** Only an authorized candidate can become `APPROVED`, and no approved candidate has been used for training yet.

## P2 — Dataset versioning and lineage

**Objective:** Create reproducible, coverage-balanced, safe dataset manifests through the existing dataset owner.

**Do:** Extend metadata schema, tenant RLS, source refs, content hashes, split leakage groups, recipe version, license/consent state and frozen evaluation pool. Integrate revocation ancestry and invalidation.

**Proof:** Random vs quality vs coverage recipe output reproducibility; zero train/test leakage; two-tenant adversarial tests; source revocation invalidates associated dataset; no secret output in logs.

## P3 — KCM operational self-model projection (no weights)

**Objective:** Provide evidence-backed view of Karen's competencies, limitations, Persona state and lessons.

**Do:** Reuse `core/cognitive/state.py`, existing outcome evidence and Persona/user models. Build versioned, rebuildable projection with current verified skills and explicit unknowns. Feed advisory summary to existing CORTEX/PromptRuntime with token and scope budgets.

**Proof:** Stale/unverified evidence never claims mastery, model/provider provenance correct, tenant isolation, no permission escalations, projection cache rebuild and invalidation, expected UX empty/error states.

## P4 — Controlled offline fine-tuning

**Objective:** Evaluate compact SFT/LoRA against no-training baseline.

**Do:** Integrate approved dataset manifests into `ProductionFineTuner` or its strongest canonical successor; pin dependencies and model revisions; train on correct targets with mask; preserve immutable artifacts, training provenance and failure receipts; retain current model if anything fails.

**Proof:** Genuine checkpoint SHA, successful load probe, reproducible SFT smoke test (hardware-appropriate), test-only mocks never in production, sample privacy scan, adversarial held-out benchmark.

## P5 — Independent promotion and operations

**Objective:** Activate only a model with measured benefits and rollback controls.

**Do:** Follow existing model lifecycle governance; independent evaluator, promotion approver, canary, metrics and live exact-model receipt. Build limited admin UX after APIs pass security tests.

**Proof:** Offline+shadow+canary gates, p95 latency and cost measurement, baseline non-inferiority, regression suite, revocation during training/publication, deployment rollback, RLS and UI readiness.

## P6 — Research extensions (not initial release)

Experiment with skill-gap curriculum, per-task adapter sets, model-aware data valuation, continual learning and compact personalization representations only after proven P1-P5. Keep behind feature flags with experimental evaluation datasets; do not change primary architecture on hype alone.

## Suggested implementation touchpoints (audit before editing)

| Responsibility | Existing path(s) |
|---|---|
| Memory artifact + privacy | `src/ai_karen_engine/core/memory/types/base.py`, `guards.py`, `formation/evaluator.py` |
| Candidate types and policy | `src/ai_karen_engine/echocore/contracts.py` |
| Dataset owner | `src/ai_karen_engine/learning/training_data_manager.py`; confirm whether alternate canonical dataset service supersedes it |
| Training worker | `src/ai_karen_engine/echocore/production_fine_tuner.py`; audit actual worker/queue |
| Settings | `src/ai_karen_engine/config/learning.py` |
| Derived cognition | `src/ai_karen_engine/core/cognitive/state.py`, existing outcome and personalization packages |
| Runtime execution | `src/ai_karen_engine/core/runtime/`, `core/cortex/`, `core/expression/` |
| Model lifecycle | Existing registry and `docs/MODEL_LIFECYCLE_ARCHITECTURE.md` |
| Docs | This package at `docs/capabilities/karen-consciousness-model/` |

## Mandatory exact-head proof

1. Compile/import and lints: `python -m compileall src`, `ruff check src tests`, `mypy src`.
2. Unit/integration: `pytest tests/ -q` plus newly added focused candidate, dataset, RLS, deletion and training-worker suites.
3. Security: RBAC/tenant/consent/poison/adversarial data and model-origin tests.
4. Runtime: chat provider routing, fallback and streaming parity; model readiness and actual inference receipt.
5. Full UI if added: frontend lint/typecheck/test/build, responsive/role-specific browser acceptance.
6. `docker compose config`; applicable exact-head CI and production first-boot gates.
7. For deletions, document path purpose, imports/test/config/docs/UI references, replacement, reason, and rollback strategy.

Do not claim all gates passed based on static documentation or historical CI. No merged PR or deployed feature follows merely from accepting this architecture.
