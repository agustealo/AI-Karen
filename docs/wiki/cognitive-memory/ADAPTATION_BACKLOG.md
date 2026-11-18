# Candidate feature-level adaptation backlog

**Status: research hypotheses, not implementation authorizations.** Reuse canonically owned logic and complete existing paths before suggesting libraries.

## A01 | Native hybrid retrieval truth (P0)
**Owns:** NeuroRecall fusion + existing PostgreSQL candidate retriever implementations.  
**Current gap:** `PostgresRecallRetriever` uses substring matching while runtime metadata names `postgres_pgvector_fts`.  
**Inspect from:** LightRAG local/global/hybrid query design and Graphiti hybrid scoring; avoid importing their search stacks.  
**Experiment:** Native PostgreSQL pgvector and FTS candidates under existing scopes; compare separately then together; report real query plans, token cost, RLS and degraded statuses.  
**Proof:** R01, R02, R03, R09, R12; new services=0; new Python dependencies=0 unless an exact proven necessary gap.

## A02 | Association propagation (P1)
**Independent method inspection:** [KCR-02A, pinned HippoRAG PPR and LightRAG mechanics](KCR02A_GRAPH_RETRIEVAL.md). The research-only comparator is *not* a runtime adaptation.
**Owns:** `SpreadingActivation` compute over authorized `PostgresGraphRepository` neighborhoods; **NeuroRecall final ranking**.  
**Inspect from:** HippoRAG 2 Personalized PageRank entity/passage links and LightRAG graph context extraction.  
**Experiment:** Existing bounded-decay algorithm vs a dependency-free sparse Personalized PageRank implementation built only in isolated research code.  
**Proof:** R03, R04, R09, R14; show memory/hop budget and how graph deletions propagate.

## A03 | Dual-clock temporal recall (P1)
**Source/audit update:** [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md) identifies the historical as-of API gap and half-open claim validity boundary mismatch. Production changes require a scoped follow-on review.
**Owns:** `MemoryTemporalEvolutionService`, `BeliefResolution`, governed PostgreSQL graph, NeuroVault writes.  
**Inspect from:** Graphiti episodes, validity and invalidation; Semantica truth snapshots.  
**Experiment:** Reconstruct `valid_at` and `known_at` from durable evidence; refuse unauthorized historical truth and do not conflate `created_at` with worldly validity.  
**Proof:** R05, R06, R07, R08, R14.

## A04 | Evidence-linked knowledge extraction (P2)
**Source/audit update:** [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md) documents Cognee's ownership-aware deletion planner and Karen's final consent-read gate; verify retries and shared evidence without importing Cognee.
**Owns:** `MemoryFormationEvaluator` and canonical signal pipeline, PostgreSQL entity resolver, graph projection worker.  
**Inspect from:** Cognee extraction graph pipeline; LightRAG incremental merge/rebuild; Semantica provenance schemas.  
**Experiment:** Typed entity/relation candidates with confidence, source span, dedupe, life-cycle and error/abstain behavior. No alternate persisted text or graph.  
**Proof:** R07, R08, R13, R14 plus ingestion cost and source coverage.

## A05 | Decision-to-evidence reconstruction (P2)
**Source/audit update:** [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md) documents the distinction between recorded lineage and post-hoc causal explanation, and Semantica's optional own-store design.
**Owns:** runtime outcome/decision ledger, governed memory event references, CORTEX policy scope; NeuroRecall can retrieve approved evidence.  
**Inspect from:** Semantica decision provenance, PROV-O and explanation chains; Graphiti episodic lineage.  
**Experiment:** Read-only chain `decision_id -> policy_version -> evidence_ids -> execution/outcome`; explain historical record without asserting causal identification. Optional standards export after authorization review.  
**Proof:** R09, R10, R11, R12 and audit/erasure coverage.

## Decision statuses
`reject` / `defer` / `native-enhancement-candidate` / `dependency-review-required`. No candidate is currently marked adopted or benchmark-proven.

