# Capability matrix | external techniques vs KAREN

**This is a feature research matrix, not a ranking or claim of comparative performance.** All five have useful concepts; none is a new KAREN authority.

| Research subject | Strongest feature to inspect | Already inside KAREN | Potential contribution | Production package decision |
| --- | --- | --- | --- | --- |
| LightRAG | Local/global/hybrid graph-informed candidate selection; incremental entity/edge rebuild | PostgresGraphRepository, NeuroRecall, graph candidate router | Better source-aware context assembly and incremental provenance consistency | **Do not install** |
| Graphiti | Episodic fact reconciliation and validity/invalidity timelines | MemoryTemporalEvolutionService, memory ledger, graph valid/recorded fields | Dual-clock as-of query semantics and tested contradiction history | **Do not install** |
| Cognee | Staged extraction/normalization/cognification with source-linked graph provenance | MemoryFormationEvaluator, signal pipeline, entity resolver, projections | Better extraction quality and incremental deletion handling | **Do not install** |
| HippoRAG 2 | Entity/passage graph + Personalized PageRank evidence propagation | SpreadingActivation, graph traversal, NeuroRecall fusion | Better multi-hop recall and association scoring without igraph | **Do not install** |
| Semantica | Context/decision provenance, temporal truth-maintenance and rule-based explanations | SemanticProvenance, OutcomeRecorder, memory events, belief resolution | Auditable decision evidence, PROV-O export, bounded deterministic inference | **Do not install** |

## Top capability gaps to measure, not assume
1. **Hybrid candidate coverage:** Does actual production retrieval use vector similarity and FTS, or chiefly substring matching? Compare from the same RLS-protected corpus.
2. **Multi-hop associative accuracy:** Does current depth/decay strategy recover indirect but relevant evidence without introducing false associations? Compare Personalized PageRank only within already-authorized neighborhoods.
3. **Bi-temporal correctness:** Can answers distinguish *valid-at* from *known-at* and resolve retrospective corrections?
4. **Entity resolution and lifecycle:** Can merges avoid accidentally conflating two people/entities and reliably erase derived references?
5. **Decision explanation:** Can the answer show policy, source event, outcome and uncertainty as linked evidence, not model-generated post-hoc causality?

## Integration owner rules
- **Formation** extracts signals; experiments may adjust cues and confidence but do not create a second formation pipeline.
- **Graph** stores derived relationships with PostgreSQL, tenant/user scope and source IDs.
- **NeuroRecall** is the only source-fusion/rerank/select authority.
- **Runtime + CORTEX** enforce policy and execution; upstream agent MCP servers do not gain decision authority.
- **NeuroVault** is the only durable mutation/erasure authority.

## Research release stages
**INSPECT → REPRODUCE → BENCHMARK → GATE → ADR**. The sprint is currently at **INSPECT**. Source files and a proposed test plan are not completed functional enhancements.

