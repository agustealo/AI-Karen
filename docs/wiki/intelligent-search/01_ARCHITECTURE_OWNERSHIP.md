# 01 | Runtime architecture, authority & source map

**Verified baseline:** `main@f9ff898f036b071d38bee9fafe43cf458e2e2bd4` (2026-11-20). Paths are relative to the repository root. Where an integration is not proved by the inspected call path, it is labeled **audit required**.

## 1. System responsibility map

| Responsibility | Canonical owner / observed path | Allowed | Forbidden |
| --- | --- | --- | --- |
| API ingress | Plugin kernel / API ingress | Validate input and auth/session, attach tenant and correlation, delegate | Provider selection, graph traversal, prompt composition or shadow routing |
| Intent and eligibility | CORTEX: `core/cortex/routing_intents.py` and runtime policy | Determine applicable capability and authorization hints | Execute tools, write memory or return synthetic answers |
| Chat execution authority | Canonical chat runtime, runtime policy and provider registry | Compose authorized context and prompts, choose capable provider, invoke governed tools, synthesize and persist/audit | Delegate security decisions to React |
| Plugin dispatch | `src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py` | Prepare selected mode and delegate to canonical search capability | Independent model/router, unchecked identity in request context |
| Search and crawl | `src/ai_karen_engine/services/tooling/internet_capability_service.py`; `services/search/` | Authorized search, crawl, extraction, evidence normalization, diagnostics | Invent source content or assume synthesis succeeded |
| Article storage | Runtime search article service via `services/database/repositories/repository_factory.py` | Durable document references with authorization and completeness | Treat preview as full article or expose another user's article |
| Memory event graph | `core/memory/graph/service.py`; `platform/memory/postgres/graph_repository.py` | Rebuildable scoped relational/temporal projection over governed data | Another durable graph truth store |
| Memory candidate selection | `core/memory/retrieval/neuro_recall.py` plus `retrieval/retrieval_router.py` | Bounded candidate routing, live source ACL, fusion, ranking, rejection, abstention | Search plugin directly publishing raw private graph rows |
| Complex workflows | `core/langgraph_orchestrator/` and runtime authorization | Graph planning, checkpoints and genuine branching tool chains | Extra orchestrator for single-step retrieval |
| Consumer presentation | `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/` | Show backend truth, accessible source and state controls | Construct factual relations, claim tool termination, save or modify memory |

## 2. Current ingress and output flow

```text
Consumer IntelligentSearchPage
   │ query/mode/advanced settings, user-controlled AbortSignal
   ▼
IntelligentSearchApi.executeSearch
   │ POST /api/plugins/execute
   │ { plugin_name: "intelligent-search", parameters: payload }
   ▼
Canonical plugin kernel / authenticated execution context
   ▼
WebSearchDispatcher.run(params, ExtensionExecutionContext)
   │ validates permitted capability context
   │ mode handler prepare(query, context)
   ▼
InternetCapabilityService.execute
   │ InternetSearchRequest normalization / provider policy / authorization
   │ mode resolution / source discovery / crawling / content processing
   │ durable article store (where allowed)
   ▼
Response: evidence, results, citations, diagnostics, provider / run metadata
   ▼
IntelligentSearchApi normalization -> ResultsWorkspace / ArticleReader
```

**Important limitation:** The plugin search response currently emphasizes retrieval and excerpts. It is not by itself proof of final, model-generated, claim-cited answer synthesis. Consumer copy must not call retrieval summaries verified AI answers.

## 3. Three source trees and packaging audit

1. **Active consumer source (observed):**
   `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/`.
   Key files: `IntelligentSearchPage.tsx`, `components/ResultsWorkspace.tsx`, `components/Panels.tsx`, `components/ArticleReader.tsx`, `hooks/useIntelligentSearch.ts`, `hooks/useSearchPayload.ts`, `services/IntelligentSearchApi.ts`, `types/index.ts`, `configs/modeConfig.ts`.
2. **Backend extension and adjacent UI package:**
   `src/ai_karen_engine/extensions/plugins/intelligent-search/`. Contains backend `handler.py`, `handlers/`, manifest, prompts and `ui/`.
3. **Essential/free plugin distribution copy:**
   `free_plugins/essential/intelligent-search/`, with independent manifest and UI-shaped files.

**Do not blindly copy files among these locations.** Before touching packaging, trace plugin manager bundling, import graph, build/install workflow, manifest resolution and actual mounted consumer path. Choose one authoritative edit owner, provide a deterministic generated packaging step where possible, retain compatibility only as needed. Audit all runtime registrations before deletion.

The backend manifest currently advertises `version: 2.0.0`, `entrypoint: handler:MainExtension`, `provides_ui`, `provides_api` and `prompt_first`. It also contains historical defaults including `default_mode: general` and provider names. **The live consumer hook defaults to auto** and backend provider authority is the central search/runtime configuration. Do not turn manifest metadata into a new provider registry.

## 4. Graph technologies are not interchangeable

- **PostgreSQL memory graph:** Canonical durable typed relationships and temporal reconstruction, scope-enforced. `LeanGraphConfig` defaults to `postgres`; `in_memory` is explicit test/development; retired `kuzu` is rejected.
- **NeuroRecall:** Candidate selection/ranking after source retrieval. Graph traversal alone is not publication authorization.
- **ReasoningGraph / CapsuleGraph:** Reasoning-related internal inspection, not a public chain-of-thought export or graph database.
- **LangGraph orchestration:** Workflow state and actions, not a second knowledge store.
- **Legacy `services/knowledge/knowledge_graph_client.py`:** Neo4j-oriented code exists. Its active production role and security must be established before reuse; it is **not** selected as the canonical memory graph.

## 5. Interfaces for extending the system

For a new result type: extend existing mode handler or canonical search service, define a typed output in plugin UI `types/index.ts`, and expose it through the current response normalizer. Add integration contract tests and consumer tests.

For an external retrieval provider: register through canonical provider configuration/registry; preserve provider IDs, source attribution, fallback metadata, budgets and errors. Do not hardcode an API key or provider preference inside a handler or frontend.

For investigation graph expansion: use a server-authorized projection of selected memory events and search evidence. Revalidate each source lineage, obey scope/temporal filters, and expose only proof-backed edges. Do not invoke PostgreSQL directly from the plugin UI.

For action integration: use runtime-approved plugin/task contracts with RBAC and audit. Clicking a node in the graph is a navigation event, not permission to run a destructive tool.

## 6. Ownership audit checklist

Before any change, document:
1. Who owns the responsibility and which exact production call path proves it?
2. Does an equivalent implementation already exist?
3. Which plugin copies are generated, mounted or unused?
4. Does the change preserve CORTEX decision versus runtime execution?
5. Does graph retrieval go through NeuroRecall or another authorized projection?
6. Does it preserve tenant, user, session, consent and source ACL?
7. Does it preserve provider selection, degradation reason, persistence receipts, tracing and audit?
8. What exact-head backend, frontend, integration and release tests prove it?

**Stop condition:** If the intended feature requires an additional graph truth store or unscoped memory route, redesign within the existing owner before implementation.
