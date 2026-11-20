# KIS-GRAPH-01A | Graph-native Intelligent Discovery: source and UX contract

**Status:** architecture baseline only, **not** a shipped graph search or consumer release.  
**Repository base:** `main@3b342d4b02d9a836aa5f58fcc53d9a05c745e7e1` (2026-11-19).  
**Product thesis:** search is an entrypoint to an authorized, evidence-grounded investigation; graph, timeline, evidence, conversation, and workflow are synchronized views over the **same** research context.

## 1. Audited owners on main

| Function | Existing owner | Observed source | Boundary |
| --- | --- | --- | --- |
| Consumer search UI | Mounted plugin repo | `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/` | Present backend evidence only; no independent intelligence |
| Search request hook | `useIntelligentSearch` | `hooks/useIntelligentSearch.ts` | Draft controls, abort transport, display verified results |
| Plugin execution | Existing intelligent-search dispatcher | `src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py` | Delegate to canonical `InternetCapabilityService`; accept typed kernel context |
| Web retrieval | Canonical internet/search services | `src/ai_karen_engine/services/tooling/internet_capability_service.py` | Retrieval/crawl and grounded source payload, not second answer authority |
| Intent, auth, synthesis | CORTEX and canonical runtime | Existing CORTEX and runtime modules | Only backend can select capability, authorize sources/tools, assemble prompts and generate |
| Durable memory graph | `LeanGraphService` + `PostgresGraphRepository` | `core/memory/graph/service.py`, `platform/memory/postgres/graph_repository.py` | PostgreSQL projection over governed records; no new graph DB |
| Memory retrieval | `NeuroRecall` | `core/memory/retrieval/neuro_recall.py` | Final scoped fusion/ranking, provenance, abstention |
| Complex workflow | Existing LangGraph runtime path | `core/langgraph_orchestrator/` | Only truly multistep work; runtime gates execution |
| Legacy/other graph client | `KnowledgeGraphClient` | `services/knowledge/knowledge_graph_client.py` | Neo4j-oriented code exists; **active status unproven**, not selected as canonical |
| Bundled copies | Plugin packaging | `free_plugins/essential/intelligent-search/`, `src/ai_karen_engine/extensions/plugins/intelligent-search/ui/` | Audit build/install process before copy consolidation |

The memory graph configuration permits `postgres` (default) and explicit `in_memory`, with legacy `kuzu` rejected. The repository already enforces scoped PostgreSQL traversal and stored temporal relationship fields. Neither fact proves a generic research graph endpoint exists.

## 2. Observed UX debt

- `IntelligentSearchPage.tsx` has left-side search controls, a tabbed result workspace and optional technical details. This is a retrieval-tool presentation, not a unified research surface.
- `ResultsWorkspace.tsx` prioritizes passages/sources and technical tabs; source text is explicitly **not** a synthesized AI answer.
- `useIntelligentSearch.ts` sets default mode `auto` and aborts current requests, yet `setQuery` and `setMode` clear completed evidence while `updateOptions` retains it. Preserve completed searches as immutable snapshots with draft-controls-differ indicators; never label old evidence as answering the edited query.
- The current source-to-chat bridge dispatches a bounded `karen:inject-message` user request. It does not establish durable session-bound, authorization-checked source-reference followups.
- Graph/timeline/workflow are **not** documented as current consumer search result lenses. Do not market them as shipped.

## 3. Experience principles

1. **Search-first composer:** natural language, file/media attachments only where permitted, optional scope/mode overrides. Mode `auto` remains the default.
2. **Answer-first, evidence-always:** verified generated answer when runtime synthesis succeeds; otherwise clearly labeled retrieved evidence without a simulated answer.
3. **One synchronized context:** `Answer | Graph | Timeline | Evidence | Workflow`. View switching cannot change authority or trigger unapproved tool execution.
4. **Graph-native exploration:** selecting an entity/claim/edge filters citations, highlights corresponding text and allows authorized further investigation. No inferred/placeholder edges.
5. **Progressive disclosure:** consumer sees meaning, sources, freshness and uncertainty first. Provider IDs, traces, chunks, latency and retries appear only in diagnostics.
6. **Resumable work:** durable project/session research may be reopened only after server-side scope checks.
7. **Responsive, accessible and predictable:** keyboard node navigation, focused reading panel, accessible list/table fallback, touch support, motion reduction, predictable cancel states.

## 4. Three graph concepts, zero extra truth stores

**Knowledge graph (existing memory projection):** records governed entities/events/assertions and typed edges with valid/observed/recorded times. Retrieval and traversals must remain scoped and bounded.

**Investigation graph (proposed typed view):** ephemeral or governed projection **from authorized search sources, extracted factual claims, selected entities, evidence links and research questions**. No independent write authority or free-form truth. An investigation graph response must be rendered from real links and provenance; absence of authorized material returns an explicit empty/degraded state.

**Execution graph (existing runtime workflow):** plans, dependencies, tool receipts, verified states and human approvals from runtime/LangGraph. Do not misinterpret a proposed plan as an executed action.

A reasoning capsule/trace is not user-facing chain-of-thought. Show evidence, sourced hypotheses, decisions and recorded execution milestones, not hidden internal reasoning.

## 5. Backend-authored investigation graph read contract (proposed, not implemented)

The runtime defines/validates the eventual endpoint and context. The UI must never construct graph truth itself. The following is a **contract sketch**, not proof of any existing route:

```text
GET authorized-investigation/{id}/graph?cursor=...&limit=...&as_of=...
context: authenticated user + tenant + session/project + correlation
response:
  investigation_id; snapshot_id; revision; status; degraded_reasons
  nodes[]: stable_id; kind; title; verification_state; source_ids[]; valid_at?; observed_at?
  edges[]: stable_id; source_node_id; target_node_id; relationship_type;
           source_ids[]; verification_state; valid_from?; valid_to?; observed_at?
  pagination; permission_scope; provenance; issued_at
```

Only use existing canonical identifiers for persisted source/event/memory rows. The graph read service must reject identifiers from another tenant; never accept identity/permissions from a browser payload. For private user/person data, require live source ACL checks on **every** traversed reference and result node; a cached `authorized` flag is not enough.

Node kinds can initially be bounded to `source`, `entity`, `claim`, `event`, `question`, `task`. Edge types must use a reviewed registry, e.g. `MENTIONS`, `SUPPORTED_BY`, `CONTRADICTS`, `SUPERSEDES`, `DEPENDS_ON`, `REQUIRES`. A proposed relationship should **not** be assigned the verification state of the source that merely mentions it.

Graph expansion: depth/fanout/total-node/page/deadline limits, cycle protection, temporal-as-of validity, stable paging, safe cancellation, clear stale snapshot behavior and source revocation invalidation. Missing graph support should not prevent ordinary non-graph search results.

## 6. Search-to-graph execution flow

```text
User draft query / scope
  → canonical ingress auth + request/tenant correlation
  → CORTEX intent, eligible capabilities and policy hints
  → ChatRuntime authority for source/memory/tool eligibility and budgets
  → existing Intelligent Search plugin + InternetCapabilityService (retrieval)
  → authorized evidence identifiers, crawl provenance and optional persistence receipts
  → canonical graph projection/traversal for eligible scoped records
  → NeuroRecall (if user/project memory recall is authorized)
  → runtime grounded synthesis / abstention + structured view manifest
  → consumer lenses (Answer, Graph, Timeline, Evidence, Workflow)
  → optional user-approved action via canonical runtime, with execution receipt
```

Do **not** call LangGraph for a one-step informational query. Do not rebuild CORTEX classification in the plugin, mount a second search route, mirror full articles into graph storage, or let the browser choose models.

## 7. UX interaction and error-state contract

| Scenario | Expected behavior |
| --- | --- |
| Blank start | Central composer, recent permitted investigations (if any), no fake trending topics |
| Ordinary quick question | Cited answer when synthesized; otherwise clearly labeled source results |
| Open graph | Expand only actual authorized, evidence-linked nodes; show source provenance on edge selection |
| Graph unavailable | Explicit unavailability/degraded banner; retain working answer/evidence views |
| Contradiction | Surface both source citations, difference, timestamps and verification status |
| Query edited | Preserve completed evidence as previous snapshot while indicating draft has changed |
| Query executed | Load new snapshot independently; late previous responses cannot overwrite it |
| Cancelled | UI cancellation and actual server cancellation receipts distinguished honestly |
| Permissions revoked | No stale restricted edge or source payload, even from cached graph snapshot |
| Historical as-of | Clearly distinguish world valid time from when evidence was observed and recorded |
| Follow-up question | Resolve selected source IDs by runtime on the server; verify permissions again |
| Task request | Preview scope, requested action, RBAC/approval and receipt; never auto-run from clicking an untrusted node |
| Narrow screen | Graph can be replaced by navigable entity list and detail drawer; preserve keyboard access |

## 8. Slices and proof

### KIS-GRAPH-01B: completed-result continuity
Change `useIntelligentSearch.ts` state contract: separate draft from the successful response snapshot, preserve older evidence after edits, show explicit stale/draft warning, invalidate in-flight requests and verify mode changes; add hook/component + Playwright tests. No backend mutation. Ensure option edits do not silently become the submitted query.

### KIS-GRAPH-01C: governed graph view producer
Audit existing graph query and evidence stores; inject authorized, bounded graph projection into canonical runtime response composition. Tests cover tenant/user isolation, source ACL revocation, cycles, depth, pagination, temporal state, dedup, ambiguous entities, cancellation and absent graph.

### KIS-GRAPH-01D: synchronized visual lenses
Render actual typed graph nodes/edges; accessible source panel and list fallback; clicking verified graph relations highlights answer/evidence/timeline. Do not duplicate plugin stores.

### KIS-GRAPH-01E: conversational follow-ups, durable research and workflow
Reuse runtime message contract and persistence; selected sources referenced by server-authorized IDs. For complex investigations, reuse existing LangGraph rather than new graph orchestrator. Workflow states are backend-confirmed.

### KIS-GRAPH-01F: first-class consumer acceptance
Run `python -m compileall src`, `pytest tests/ -q`, `ruff check src tests`, `mypy src`, frontend `npm run lint && npm run typecheck && npm run test && npm run build`; integration tests with real PostgreSQL and search/provider responses; authenticated browser tests at 390/768/1024/1440px with keyboard, screenreader and source revocation scenarios. Inspect packaging divergence. No consumer-ready claim from mocked component tests.

## 9. Release decision
This document **does not** implement or certify graph-native search. The release remains **NO-GO** pending implementation, CI, real backend/provider/graph acceptance and human UX review. Merge this architecture-only baseline independently when its documentation checks pass; future slices need their own exact-head proof.
