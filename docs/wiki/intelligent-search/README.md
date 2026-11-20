# Intelligent Search Developer Wiki

> **Audience:** KAREN/KARI maintainers, core-runtime developers, graph/memory engineers, plugin authors, UX developers, security reviewers, release engineers.
>
> **Baseline verified:** `main@f9ff898f036b071d38bee9fafe43cf458e2e2bd4`, 2026-11-20.
> **Release status:** NOT consumer certified. See [SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md) for the release gate.
> **Documentation status:** This wiki describes live code, historical behavior and proposed capabilities separately. A documented planned contract is **not** an implemented endpoint.

## Navigation

| Document | Primary question answered |
| --- | --- |
| [01. Architecture & ownership](01_ARCHITECTURE_OWNERSHIP.md) | Who decides, executes, persists and renders? Which existing implementation to reuse? |
| [02. Runtime, modes & API contracts](02_SEARCH_RUNTIME_AND_CONTRACTS.md) | What is the actual request path and payload? What does the response mean? |
| [03. Graph-native intelligence](03_GRAPH_MEMORY_AND_INVESTIGATION.md) | How do memory, knowledge, evidence, temporal and workflow graphs interact without duplicate authority? |
| [04. Consumer UX & accessibility](04_CONSUMER_UX_AND_ACCESSIBILITY.md) | What are the actual UI entrypoints, states and future synchronized research lenses? |
| [05. Security, provenance & observability](05_SECURITY_PROVENANCE_OBSERVABILITY.md) | What prevents tenant/source leaks, forged citations, prompt injection and unapproved actions? |
| [06. Development, testing & release](06_DEVELOPER_WORKFLOW_AND_RELEASE.md) | How do we extend, verify, review, ship and troubleshoot a change? |
| [07. Backlog & ADR register](07_ROADMAP_ADRS.md) | What is complete, proposed, blocked and intentionally not selected? |

## Product mission

Intelligent Search is the **discovery doorway** to KAREN's broader intelligence: sourced retrieval, answers where the runtime actually generated them, inspectable evidence, entity and temporal investigation, scoped memory recall, and (with explicit authorization) executable work plans. The user should move between **Answer, Graph, Timeline, Evidence and Workflow** views without losing provenance or being shown invented intelligence.

A search result graph is not automatically a personal memory graph. A proposed task is not proof of tool execution. A retrieved passage is not a verified AI answer. A relationship inferred from language is not an observed causal edge. These distinctions are architecture contracts, not copywriting details.

## Start here by role

- **Backend:** Read 01, 02, 03, 05, 06. Begin at `src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py` and `src/ai_karen_engine/services/tooling/internet_capability_service.py`.
- **Frontend:** Read 02, 04, 05, 06. Begin at `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/intelligent-search/IntelligentSearchPage.tsx`.
- **Cognitive graph/memory:** Read 01, 03, 05, 06. Begin at `core/memory/graph/service.py`, `platform/memory/postgres/graph_repository.py` and `core/memory/retrieval/neuro_recall.py`.
- **Plugin developer:** Read 01, 02, 05, 06. Extend the existing plugin manifest, mode handlers and kernel execution contract, not a second search service.
- **Release/security:** Read 05, 06 and [SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md).

## Source hierarchy and document truth

1. **Live source, tests and observed exact-head CI** establish current implementation and verification.
2. **Architecture policies** constrain changes even where legacy code diverges.
3. **This developer wiki** explains ownership, known gaps and intended evolution.
4. **Historical completion summaries** record prior work but do not certify current runtime or endpoints.
5. **PR proposals** remain unshipped until merged, verified in the target stack and release-accepted.

Primary linked references:
- [KIS-GRAPH-01A architecture contract](../../intelligent-search/KIS_GRAPH_01A_DISCOVERY_CONTRACT.md), merged from [PR #1117](https://github.com/agustealo/AI-Karen/pull/1117).
- [Consumer release SR-01](../../intelligent-search/CONSUMER_RELEASE_SR01.md), currently RED.
- [Historical completion summary](../../INTELLIGENT_SEARCH_COMPLETION.md), **historical**, not source-of-truth for active route or readiness.
- [Memory graph developer sheet](../../development/MEMORY_GRAPH_DEV_SHEET.md).
- [Graph retrieval research](../cognitive-memory/KCR02A_GRAPH_RETRIEVAL.md).
- [Plugin developer guide](../../DEVELOPER_PLUGINS.md).

## Non-negotiable rules

- **One owner per responsibility.** Search plugin executes its capability; CORTEX decides eligibility; runtime owns trusted context, models, prompt assembly, synthesis, approved tool invocations and response truth; NeuroRecall owns memory candidate fusion; PostgreSQL owns durable graph projection; LangGraph owns *only* genuine multistep workflows.
- **Local-first, prompt-first, secure by default.** No plugin-specific shadow LLM router, prompt assembly in React, client-defined RBAC or direct browser-to-memory-database access.
- **No fabricated evidence.** Every answer claim, graph node/edge, source quote, weather observation, status, and execution receipt must have a verified data origin or be clearly marked proposed/unknown.
- **No cross-tenant access.** Enforce server-side tenant, user, consent, source ACL and temporal policy at every graph/retrieval expansion, persistence read and action gate.
- **Prove changes.** Architecture audit, import/reference scan, backend/frontend tests, real PostgreSQL/host acceptance where relevant, exact-head CI and release attestation. Never confuse mocked Playwright with live provider proof.

## Contributor workflow

1. Identify canonical owner and active call path.
2. Search existing source, PRs, issues, package copies and tests before adding functionality.
3. Record a concise contract or ADR when the request crosses runtime, plugin, graph or persistence boundaries.
4. Implement the smallest coherent slice, add denial and success tests, maintain typed response compatibility.
5. Run the proof matrix in [06](06_DEVELOPER_WORKFLOW_AND_RELEASE.md) and update this wiki in the same PR.
6. Merge only the reviewed, exact-head-green PR; consumer-ready remains a separate deployment gate.

**Wiki maintenance requirement:** When an API shape, mode, graph relationship, security boundary or UX state changes, update its corresponding chapter, source matrix, regression tests and the roadmap status in the *same PR*. Do not duplicate this wiki in each packaged plugin copy.
