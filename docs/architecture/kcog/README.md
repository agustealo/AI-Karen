# KCOG: Cognitive Intelligence Convergence Wiki

> **Program:** KCOG, the advanced cognitive intelligence engineering program for Karen/KARI.
> **Wiki revision:** 1 (2026-11-15).
> **Repository baseline at creation:** `272e23c4b5879771294e46c2d205e3b6f3909050` (read-only observation, not a claim that later commits are covered).
> **Delivery status:** PROPOSED / documentation in review. No cognitive capability is marked production-ready merely because this document exists.
> **Canonical authority:** existing CORTEX + ChatRuntime + RuntimePolicy, not an independent "brain" or orchestrator.
> **Primary sprint:** KCOG-S1, capability integrity and bounded executive-control convergence.

## Mission and non-goals

Build a local-first cognitive runtime that can construct grounded situation models, generate falsifiable predictions, plan safely, calibrate uncertainty, learn reusable competence from verified outcomes, and prove transfer without forgetting. Preserve strict RBAC, tenant/user scope, provenance, revocation, audit and fallback truth.

**Non-goals:** claiming AGI/human consciousness; renaming heuristics as causal inference; uncontrolled model self-editing; per-persona memory silos; shadow data stores; a secondary task router; fake training, learning, or evaluation results; automatic cross-tenant transfer.

## Read this wiki in order

1. [Sprint plan](SPRINT_PLAN.md): scope, dependency order, ticket handoffs and acceptance.
2. [Source-of-truth ownership](OWNERSHIP_AND_CALLGRAPH.md): exact runtime authority and reuse map.
3. [Capability integrity register](CAPABILITY_INTEGRITY.md): source-confirmed risks and dispositions.
4. [Cognitive contracts and learning timescales](COGNITIVE_CONTRACTS.md): typed envelopes, model/skill boundaries, provenance.
5. [Evaluation and CI](EVALUATION_AND_CI.md): benchmarks, invariants, failure modes, proof commands.
6. [Continuity runbook](CONTINUITY_RUNBOOK.md): how to resume across PRs, sessions and incidents.
7. [Decisions and evidence ledger](DECISIONS_AND_EVIDENCE.md): accepted constraints, unresolved questions, observed proof.

Companion authorities: [Developer Manifest](../../development/PROJECT_DEV_MANIFEST.md), [CORTEX Runtime](../../development/CORTEX_RUNTIME.md), [Memory](../../development/MEMORY.md), [Persona Studio](../KPERSONA_FIRST_CLASS_IMPLEMENTATION.md), [Persona Learning Data](../PERSONA_SKILLS_LEARNING_DATA_GUIDE.md), [Cognitive Contract Ledger](../cognitive-contracts/CONTRACT_LEDGER.md).

## Program phases and release semantics

| Phase | Capability target | Status | Gate |
| --- | --- | --- | --- |
| KCOG-00 | truthful capability integrity and safety containment | IN REVIEW / NOT VERIFIED | unsupported causal and calibration claims cannot affect authoritative decisions |
| KCOG-01 | executive state and metacognitive effort | NOT STARTED | typed, authorized decision changes beat baseline without regression |
| KCOG-02 | predictive, temporal and causal situation model | NOT STARTED | falsifiable action-conditioned predictions, reconciliation, identifiability/abstention |
| KCOG-03 | multiscale, continual and transferable learning | NOT STARTED | verified transfer and retention across held-out tasks |
| KCOG-04 | versioned evaluated specialist competencies | NOT STARTED | persona-bound skill proof, no unverified mastery claims |
| KCOG-05 | active multimodal evidence acquisition | NOT STARTED | permissions + measurable benefit from selected evidence |
| KCOG-06 | authorized self-improvement lifecycle | NOT STARTED | immutable candidates, shadow, independent promotion, canary, rollback |

This is a multi-sprint roadmap. **Sprint S1 explicitly delivers KCOG-00, then the smallest defensible KCOG-01 vertical integration.** Do not mark later phases implemented ahead of evidence.

## Definition of intelligence advancement

For every claimed cognitive improvement: immutable baseline, versioned task corpus, verified ground truth, recorded decision/action/outcome lineage, held-out evaluation, latency and cost accounting, cross-scope security checks, regression/forgetting checks, independent promotion decision, reproducible results. A green unit test does not establish real-world cognitive improvement.

## Implementation constraints

**One responsibility, one owner, one registry, one config, one runtime path.** Audit before adding. Graph execution only for true graph workflows. User intent and persona instructions are not permission. Semantic memory is not a learning reward. Operational success is not independent answer correctness. Unsupported causal effects and probabilities must be `unknown` / `unidentifiable`, not arbitrary zero or numeric confidence.

## Sprint update protocol

The PR description is the implementation record; [the continuity runbook](CONTINUITY_RUNBOOK.md) is the stable handoff. After each merged slice, refresh: baseline commit, changed files, tests/CI links, observed evidence, unresolved defects, next exact handoff, and status. Never mark proof as green without exact-head evidence. Merges require normal branch protection and post-merge verification.
