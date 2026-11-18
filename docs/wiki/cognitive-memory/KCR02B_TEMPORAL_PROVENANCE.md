# KCR-02B | Temporal truth, source deletion, and decision lineage

**Status:** source-inspected with reproducible research-only temporal fixtures; **not live accepted**.  
**Snapshot:** KAREN `dd2b674d8e9e24e93d251c31c0dad6a10966e766` (2026-11-18), pinned upstream commits recorded below.  
**Scope:** Graphiti + Cognee + Semantica reverse engineering, no additional runtime dependencies or graph databases.

## 1. Executive comparison

| Feature | Upstream mechanism | KAREN's owner today | Actual gap to prove | Strategy |
| --- | --- | --- | --- | --- |
| Episode-linked fact invalidation | Graphiti `EntityEdge.episodes` + `valid_at`, `invalid_at`, `expired_at`, `reference_time` | MemoryTemporalEvolutionService + BeliefResolution + ledger | Differentiating world validity, observation, and supersession records end-to-end | Complete KAREN contracts |
| Historical as-of truth | Semantica `TemporalTruthMaintenanceAdapter.query_at(valid_at, known_at)` with detached snapshots | NeuroRecall + governed ledger/graph projections | As-known-at historical retrieval, late corrections, audit replay | Prototype query semantics natively |
| Multi-source derived deletion | Cognee `execute_source_ref_removal` partitions unowned/surviving artifacts, retry-safe removal | NeuroVault consent/revocation, PostgreSQL projections | Shared-derived ownership, cache/vector/edge invalidation and recovery | Audit existing lifecycle first |
| Decision evidence lineage | Semantica provenance and decision recorder | Runtime OutcomeRecorder + CORTEX policy receipts + NeuroVault | Queryable chain from decision to actual policy/source/outcome evidence | Read-only reconstruction only |

## 2. Graphiti source inspection

**Pinned SHA:** `4ef979c74e1e68d08217cf0af4022ddbc89c257f`.

- [EntityEdge fields](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/graphiti_core/edges.py#L228-L257) distinguish `valid_at` (world-time start), `invalid_at` (world-time end), `expired_at` (graph knowledge invalidation) and `reference_time` (episode clock). `episodes` retain supporting episode IDs.
- [Edge resolution](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/graphiti_core/utils/maintenance/edge_operations.py#L429-L598) performs typed-endpoint checks, scoped candidate search, duplicate filtering, and invalidation-candidate retrieval; resolution still depends on its configured LLM/embedding clients.
- [SearchFilters](https://github.com/getzep/graphiti/blob/4ef979c74e1e68d08217cf0af4022ddbc89c257f/graphiti_core/search/search_filters.py#L55-L216) expose `valid_at`/`invalid_at` predicates and source-node filters. **A group ID is not a substitute for KAREN tenant/RBAC enforcement**.
- A documented upstream [FalkorDB point-in-time bug](https://github.com/getzep/graphiti/issues/1625) exemplifies why backend implementations need explicit tests against future-episode leakage, even when the API promises historical filtering. Do not infer the bug affects KAREN.

**KAREN overlap:** [MemoryTemporalEvolutionService](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/temporal/service.py) already supports reinforce, coexist, supersede and contradict with recorded time; [PostgresGraphRepository](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/graph_repository.py) stores `valid_from`, `valid_to`, `observed_at`, `recorded_at`, source IDs.

**Finding:** KAREN has the temporal vocabulary, but its graph neighbor query currently filters by **CURRENT_TIMESTAMP**, not both independently requested world-time and known-time coordinates. This is NOT historical point-in-time retrieval proof.

## 3. Cognee source inspection

**Pinned SHA:** `5870f15d2488b99e80f71dd6e8e146b228749356`.

- [GraphDBInterface](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/infrastructure/databases/graph/graph_db_interface.py#L95-L145) has capability flags for source-referenced graph writes and explicit detach/delete operations.
- [Provenance deletion planner](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/infrastructure/databases/unified/provenance_delete_planner.py#L1-L160): derive unowned vs still-shared artifacts, delete unowned vector references, detach source references on surviving artifacts, then delete unowned nodes/edges. It retains ownership references on unowned artifacts until hard deletion to make a failure discoverable and retryable.
- [Delete receipt observation](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/api/v1/datasets/datasets.py): checks a record is actually absent before emitting success. **Not equivalent to cross-store atomicity**, and we have not independently tested failure injection.

**KAREN overlap:** [PostgresEventSource](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/event_source.py) and [recallable_memory_event](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/platform/memory/postgres/consent_filter.py) recheck current scoped consent on ledger reads. NeuroVault governs durable mutation; projections must not outlive revocation in retrieval.

**Important boundary:** Raw graph traversal checks `memory_event.consent_state='granted'` and current validity but does **not** itself include the later scope-revocation subquery. `HybridRetrievalRouter._query_graph` subsequently expands IDs through **PostgresEventSource**, which uses `recallable_memory_event` to filter revoked content. This is a **two-stage safeguard in the inspected composition**, not a reason to assume direct callers of graph traversal are safe to display. Any new graph retrieval API must preserve the final consent gate or enforce it at the graph read.

**Proposed tests:** shared derived node with two sources, first source revoked (survive), last source revoked (purge); failure after vector removal; retry after process death; stale cache rebuild; unknown source IDs; cross-tenant references; source-revocation updates before ranking. No new deletion planner will be imported.

## 4. Semantica source inspection

**Pinned SHA:** `4d83266ca0d7f70185906bfce7c96ec71c6ebc04`.

- [Temporal truth maintenance](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/reasoning/temporal_truth_maintenance.py#L27-L168) supports `sync`, `advance`, `snapshot` and `query_at` over independent `valid_at` and `known_at` coordinates. Historical `query_at` constructs a detached closure without mutating the current live session.
- The adapter's stated semantics require **half-open intervals**, explicit snapshot revisions and serialized mutation. It is **not** a drop-in distributed store/authorization layer.
- [DecisionRecorder](https://github.com/semantica-agi/semantica/blob/4d83266ca0d7f70185906bfce7c96ec71c6ebc04/semantica/context/decision_recorder.py#L206-L252) writes its own decision graph and optionally uses embeddings and a provenance manager. Reusing it directly would duplicate KAREN OutcomeRecorder and graph/persistence ownership.
- [Grounded Context docs](https://docs.getsemantica.ai/reference/grounded_context/) document replaying earlier evidence despite later correction. Vendor documentation is **not** evidence KAREN satisfies that contract.

**KAREN overlap:** Runtime [OutcomeRecorder](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/runtime/outcome/recorder.py) and ledger support real receipts, but explanation must be **evidence reconstruction**, not asserted model causality. Existing `MemoryTemporalEvolutionService.version()` separates valid time from recorded time.

**New verified discrepancy to triage:** `TemporalInterval` and PostgreSQL predicates use half-open intervals (`end` excluded), while `MemoryClaim.is_valid()` currently checks `at > valid_until`, thereby **including** the exact `valid_until` instant. A strict expected-failure test in [temporal research contract](../../../tests/benchmarks/memory/test_temporal_research_contract.py) records this gap rather than manufacturing a green historical-query claim. Audit all callers before a separate production fix.

## 5. Research test protocol

[`test_temporal_research_contract.py`](../../../tests/benchmarks/memory/test_temporal_research_contract.py):
- Exercises the **real KAREN temporal service** for valid-time/recorded-time preservation, backdated contradiction, cross-user fail-closed evolution and interval semantics.
- Includes an **independent synthetic two-clock oracle** on a fixed evidence set to define `valid_at` versus `known_at` acceptance for later backend implementation.
- Models revoked source eligibility as externally supplied truth; it does **not** call real RLS, source-ACL checks, actual Postgres as-of SQL, or restored projections.
- Records a **strict XFAIL**, not a passing assertion, for `MemoryClaim.is_valid(valid_until)` half-open mismatch.
- Does not install Semantica, Graphiti, or Cognee.

**Security gates:** A historical as-known query may reconstruct formerly true facts only if the caller is **authorized at query time**. Deletion and current revocation always override temporal reconstruction. Historical record evidence does not grant permission.

## 6. Next real proof

1. Trace every caller of `MemoryClaim.is_valid` and graph traversal APIs. Audit and fix the interval boundary under its canonical owner in a separate scoped PR.
2. Build a **real PostgreSQL** two-clock dataset where world-valid time and record time differ; compare historical knowledge at T1 vs T2 without altering the current snapshot, then test erasure and restart.
3. Verify the graph/source-ID two-stage consent gate under direct API and NeuroRecall entry points; no cross-tenant IDs or revoked content may pass.
4. Exercise shared-derived deletion with failure injection, idempotent retries and read-after-delete proof. Preserve canonical ledger history as required by policy.
5. Reconstruct a decision receipt from stored policy version, signed/source event IDs, outcome and identity; do not infer unrecorded causes.
6. Review exact dependency graph, license/SPDX and Python compatibility independently. The initial version-pinned manifest cost alone does not justify installing these three frameworks.

**Decision:** Source-study complete for KCR-02B mechanics. No production replacement. Continue proof and native consolidation before any dependency consideration.
