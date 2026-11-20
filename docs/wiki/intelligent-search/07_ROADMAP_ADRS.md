# 07 | Roadmap, architecture decisions, risks and maintenance log

**Snapshot date:** 2026-11-20, source `main@f9ff898f036b071d38bee9fafe43cf458e2e2bd4`. PR status must be refreshed before work. This document is a living index, not a scheduling or release promise.

## 1. Current development slices

| ID | Work | Status at snapshot | Authoritative evidence |
| --- | --- | --- | --- |
| **SR-01** | Consumer routing, cited synthesis, live provider and authenticated deployment acceptance | **RED**, not consumer-certified | [Consumer Release SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md) |
| **KIS-GRAPH-01A** | Graph-native UX, ownership, safety contract | **Merged** | [PR #1117](https://github.com/agustealo/AI-Karen/pull/1117), `f9ff898` |
| **KIS-GRAPH-01B** | Draft vs completed search, stale labeling, retained tabs, race/cancel tests | **Open PR**, review correction committed | [PR #1118](https://github.com/agustealo/AI-Karen/pull/1118) |
| **KIS-GRAPH-01C1** | Source-backed passage graph plus accessible Graph lens | **Open PR**, not deployed/certified | [PR #1119](https://github.com/agustealo/AI-Karen/pull/1119) |
| **KIS-GRAPH-01C2** | Authorized cognitive memory graph projection via NeuroRecall selected results | **Design/ownership audit only** | [03](03_GRAPH_MEMORY_AND_INVESTIGATION.md) |
| **KIS-GRAPH-01D** | Synchronized Answer/Graph/Timeline/Evidence panes, accessible selection | **Proposed** | [04](04_CONSUMER_UX_AND_ACCESSIBILITY.md) |
| **KIS-GRAPH-01E** | Durable investigation session, source-bound followups, governed workflow receipts | **Proposed** | [02](02_SEARCH_RUNTIME_AND_CONTRACTS.md), [03](03_GRAPH_MEMORY_AND_INVESTIGATION.md) |
| **KIS-GRAPH-01F** | Live target-host E2E, real graph/source authorization, responsive and release proof | **Proposed, blocking consumer claim** | [06](06_DEVELOPER_WORKFLOW_AND_RELEASE.md) |

## 2. Architectural decisions (ADRs within existing ownership)

### ADR-IS-001: Reuse canonical PostgreSQL cognitive memory graph
**Decision:** No new graph database or independent graph memory store. Existing `LeanGraphService`, `PostgresGraphRepository` and governed event models are the only durable graph projection authority pending a separately benchmarked/approved ADR. **Rationale:** preserve source truth, migrations, tenant isolation, temporal semantics and recovery. **Risk:** visualization-friendly projection and graph scaling need measured performance work.

### ADR-IS-002: Search plugin is a governed capability, not a new chat runtime
**Decision:** Plugin retrieves/extracts; CORTEX decides eligibility; runtime authorizes, builds prompts, routes provider/model and synthesizes; React displays output. **Rejected:** separate plugin LLM router, model selection in handler, keyword intent fallback in UI.

### ADR-IS-003: Distinguish retrieval evidence from synthesized answers
**Decision:** Source excerpts and retrieval overviews remain explicitly evidence. Only actual runtime generation with citations can be labeled an answer. **Risk:** consumers may perceive an evidence-only result as less polished; truthful degradation takes priority.

### ADR-IS-004: Graph edges must be attributable, scoped and typed
**Decision:** Each visible relationship needs source lineage, verification state, relationship allowlist and scope check. **Rejected:** client-inferred “related” lines, raw private traversal payload and graph score as confidence-of-truth.

### ADR-IS-005: LangGraph only for genuine multistep workflows
**Decision:** Quick search doesn't instantiate graph workflows by default. Complex research and actions use runtime-authorized LangGraph checkpoints, task receipts, audit and approvals.

### ADR-IS-006: Search continuity separates editable draft from completed evidence
**Decision:** Editing a question/mode/advanced control must not erase successful evidence; a stale indicator and completed-mode lenses preserve context. **Evidence:** PR #1118 (open at snapshot). **Risk:** don't present the prior result as answering the new query; do not claim persistence beyond in-memory UI.

### ADR-IS-007: A published graph view is not hidden reasoning
**Decision:** Show inspectable evidence, source-backed claims, relationship paths, status and workflow receipts. Never render hidden model chain-of-thought or privileged reasoning prompts.

## 3. Known gaps and adversarial audit queue

**P0 correctness/security**
- Verify all active mode overrides and the auto default run through CORTEX/runtime eligibility.
- Resolve frontend camelCase crawl settings versus backend snake_case parse contract.
- Confirm source-lineage ACL and revocation rechecks before any selected memory graph node is public.
- Audit `InternetCapabilityService` query logging for privacy/retention concerns.
- Prove graph URL matching, source completeness and domain/egress controls with real provider data.
- Establish actual provider/model synthesis/answer provenance before “answer first” rollout.
- Verify only one canonical mounted plugin tree controls users, and packaged copies are generated or audited.

**P1 consumer features**
- Search composer / answer-first layout; improved typography and progressive controls.
- Real read-only Graph lens, evidence inspector and accessible adjacency list.
- Preserve research snapshots, query history and explicit server save acknowledgments.
- Temporal lens and contradiction evidence, scoped source-bound followup.
- Responsive 390/768/1024/1440 browser acceptance with keyboard support.

**P2 advanced capabilities**
- Authorized context comparison, research graph filtering, multi-entity relationship investigation.
- Graph ranking experiments after labeled benchmarks, high-degree distractors and p95 assessment.
- Monitoring/subscriptions, plugin action handoffs, multimodal extraction only under runtime policy.

## 4. Risk register

| Risk | Priority | Evidence required to close |
| --- | --- | --- |
| Source-to-memory graph data leak | Critical | Real cross-tenant, revocation, source ACL and cursor replay tests |
| Untrusted content promoted to instructions | Critical | Prompt-injection and tool-permission tests across search/synthesis |
| Graph connects unsourced claims | High | Exact provenance, source completeness and unknown-edge rejection tests |
| Source snapshots mislabeled after mode edit | High | PR #1118 continuity tests and real browser run |
| Config/options silently dropped | High | End-to-end payload/handler/request-model contract tests |
| Provider success confused with model synthesis | High | Per-claim citation, model/provider execution and degraded-path receipts |
| Vercel-only preview treated as target-host acceptance | High | Real authenticated deployment origin and backend revision attestation |
| Multiple plugin copies drift | Medium | Import/bundler and shipped-artifact comparison |
| Expensive graph traversal / fanout attack | High | Depth, resource/timeout/cycle denial tests, p95/p99 benchmarks |
| Future graph visual UI inaccessible | Medium | Keyboard, list alternative, reduced-motion, screen reader acceptance |

## 5. Proposed next Kiro-style handoff

**Task KIS-GRAPH-01C2: Governed cognitive graph read model**

**Objective:** Expose selected and authorized cognitive graph provenance for consumer investigation without bypassing NeuroRecall or leaking raw graph rows.

**Do:** identify runtime-approved recall entrypoint; add typed read-only projection over final eligible memories, preserving source/event IDs only where authorized, temporal fields, relationship evidence and degradation. Put output into existing response composition or one clearly owned runtime read service. Add cross-tenant, source revocation, ambiguity, timeout and absent-graph tests.

**Reuse:** existing memory graph repository/service, `HybridRetrievalRouter`, `NeuroRecall`, source-lineage authorizer, runtime auth and correlation; existing search types and plugin UI.

**Avoid:** new Neo4j/Kuzu database, raw graph-to-client RPC, new independent memory ranking, React-built edges, hidden chain-of-thought, direct unapproved memory persistence.

**Files to inspect:** `core/memory/retrieval/neuro_recall.py`, `retrieval/retrieval_router.py`, `core/memory/graph/`, `platform/memory/postgres/graph_repository.py`, `core/runtime/`, `services/tooling/internet_capability_service.py`, consumer `types/index.ts`, `ResultsWorkspace.tsx`.

**Proof:** exact-head CI; tenant/source ACL denial; no pseudo-memory; bounded graph; selected-memory-only output; existing search unaffected; live PostgreSQL acceptance; runtime and UI schema tests.

**Risk:** live source authorization may be unavailable for some legacy-derived memories. **Fail closed** and expose a truthful graph-unavailable state; never display a private edge because it was present in an intermediate retrieval result.

## 6. Wiki maintenance policy

- Source changes and this wiki are updated together in the same PR.
- Do not revise status to green because tests exist; cite exact-head runs and real deployment.
- Add an ADR for any change introducing a new backend, graph schema, persistence authority, routing owner, plugin execution boundary or external dependency.
- Retire dead/duplicate docs only after GitHub/code references, CI scripts and release links are audited. Historical summaries can be marked archived rather than rewritten to falsely match current implementation.
- On each major milestone, update the status table, security matrix, test commands, source diagram and consumer acceptance results.
