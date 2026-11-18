# Cognee | structured knowledge extraction and incremental provenance

**Upstream:** [topoteretes/cognee](https://github.com/topoteretes/cognee) · **Pinned:** `5870f15d2488b99e80f71dd6e8e146b228749356` · **License/Python:** Apache-2.0; >=3.10,<3.15 · **Manifest:** [pyproject](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/pyproject.toml) · **Status:** source-inspected, unbenchmarked.

## Functional mechanisms to reverse-engineer
1. Staged content processing: parse, extract entities and relationships, normalize, enrich, index, then retrieve.
2. Structured model schemas/prompt contracts and deterministic validation when extraction is uncertain.
3. Relationship provenance, incremental ingestion and deletions; study how graph/vector records are retracted.
4. [Knowledge graph extraction entry point](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/infrastructure/llm/extraction/knowledge_graph/extract_content_graph.py) accepts temporal hints and routes to an LLM gateway; identify costs and failure semantics.
5. [Postgres graph adapter](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/infrastructure/databases/graph/postgres_demo/adapter.py) includes advisory locking, relationship/provenance operations and bounded neighborhood methods, but module remains under **`postgres_demo`**. Production readiness for Karen **unproven**.

## KAREN overlap and possible value
- KAREN already has MemoryFormationEvaluator, spaCy/semantic signals, entity resolver, memory event ledger and derived PostgreSQL graph projections.
- Potential improvement: extraction accuracy, deterministic source-span contracts, alias collision handling, and safe incremental deletion/projection rebuild.
- Study pipeline shapes and failure cases without importing Cognee's separate runtime and storage.

## Dependency/deployment consequences
Cognee's **base** dependency list is unusually broad: LiteLLM, LanceDB, Ladybug, FastEmbed/ONNX Runtime, NetworkX, dlt, HTTP/API stack and more. This risks new native wheels, model assets, versions and overlapping persistence owners. Explicitly measure transitive size before considering anything beyond an independent design adaptation.

## Investigation steps
- [ ] Compare canonical `MemorySignal` and `SemanticAssertion` to extraction schemas, confidence and evidence span.
- [ ] Trace source references through graph writes, corrections, deletion and replay.
- [ ] Check graph `postgres_demo` production limits and user/dataset/tenant authorization model.
- [ ] Propose one independent, dependency-zero extraction or lineage enhancement, not a copy of Cognee's architecture.
- [ ] Evaluate R07/R08/R09/R13/R14, extraction precision/recall and ingestion CPU/model cost.

**Gate:** No competing `cognify` pipeline or own database. KAREN's formation and NeuroVault remain single authorities.


## KCR-02B pinned code findings

[Source-reference removal](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/infrastructure/databases/unified/provenance_delete_planner.py#L1-L160) preserves shared derived records and seeks retry convergence for orphan vector/graph deletion. Karen uses NeuroVault and independent governed PostgreSQL consent checks. Adapt **test cases and failure-order principles**, not a second persistence engine. See [KCR-02B](../KCR02B_TEMPORAL_PROVENANCE.md).
