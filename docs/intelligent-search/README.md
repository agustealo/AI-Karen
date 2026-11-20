# Intelligent Search: developer documentation entrypoint

The maintained, detailed developer guide is the **[Intelligent Search Developer Wiki](../wiki/intelligent-search/README.md)**.

The wiki includes:
- [Architecture, canonical ownership and package copies](../wiki/intelligent-search/01_ARCHITECTURE_OWNERSHIP.md)
- [Runtime, modes, API and request/response contracts](../wiki/intelligent-search/02_SEARCH_RUNTIME_AND_CONTRACTS.md)
- [Graph, NeuroRecall, temporal and evidence investigation](../wiki/intelligent-search/03_GRAPH_MEMORY_AND_INVESTIGATION.md)
- [Consumer UX, accessibility, responsive behavior and continuity](../wiki/intelligent-search/04_CONSUMER_UX_AND_ACCESSIBILITY.md)
- [RBAC, source provenance, prompt injection and observability](../wiki/intelligent-search/05_SECURITY_PROVENANCE_OBSERVABILITY.md)
- [Developer workflow, exact-head CI, browser acceptance and release](../wiki/intelligent-search/06_DEVELOPER_WORKFLOW_AND_RELEASE.md)
- [Roadmap, ADRs, risks and next execution handoff](../wiki/intelligent-search/07_ROADMAP_ADRS.md)

## Related source documents

- [KIS-GRAPH-01A architectural contract](KIS_GRAPH_01A_DISCOVERY_CONTRACT.md), merged in PR #1117
- [SR-01 consumer release](CONSUMER_RELEASE_SR01.md), **RED until authenticated real deployment acceptance**
- [Historical plugin completion report](../INTELLIGENT_SEARCH_COMPLETION.md), **not proof of current deployed route, live provider or consumer readiness**

**Baseline:** `main@9b956d892a8f4773c0173a7773af74d23ad0eb33`, 2026-11-20. PR #1118 and #1119 have both merged; this docs PR remains pending exact-head validation. Refresh GitHub live before making claims about PR/check/merge status.

Update the wiki and its evidence matrix in the same PR whenever search mode semantics, runtime routing, API shapes, graph schema, plugin packaging, provider policy, UI states or release requirements change.
