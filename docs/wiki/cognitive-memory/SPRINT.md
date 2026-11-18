# KCOG-RESEARCH-01 | Research sprint board

**Timebox:** 10 working days from kickoff; the dates are a planning cadence, not a claim of work completed. **Branch type:** documentation/research. **Tracking:** this page because GitHub Issues are disabled in `agustealo/AI-Karen` (verified 2026-11-17); no issue number is implied.

**Objective:** Evaluate LightRAG, Graphiti, Cognee, HippoRAG 2, and Semantica via official web documentation, GitHub source and reproducible experiments. Identify the smallest implementations that improve KAREN without adding new cognitive authorities or infrastructure.

## Stages and deliverables

| ID | Day(s) | Workstream | Output | Initial state |
| --- | --- | --- | --- | --- |
| KCR-01 | 1 | Existing KAREN memory, graph, reasoning, evidence, and retrieval call graph | [Baseline](KAREN_BASELINE.md) + explicit gaps | Source-inspected; host unverified |
| KCR-02 | 2-4 | Five upstream studies: algorithms, algorithms' failure cases, license, manifests, storage, LLM/model costs | [Project dossiers](README.md#navigation) and [evidence](EVIDENCE_REGISTER.md) | Initial read complete; deep methods pending |
| KCR-03 | 5 | Collapse overlaps, separate core technique from vendor platform | [Capability matrix](CAPABILITY_MATRIX.md) and [candidate backlog](ADAPTATION_BACKLOG.md) | First-pass draft |
| KCR-04 | 6 | Fix definition of valid baseline (paraphrase, FTS, pgvector, temporal, graph, provenance) | [Benchmark contract](BENCHMARK_CONTRACT.md) | Specified; not executed |
| KCR-05 | 7 | Prove permissions, erasure, deletion propagation, RLS, old/new revision semantics | Adversarial fixtures and test report | Not started |
| KCR-06 | 8 | SBOM/solver check, license, CPU/RAM/disk/latency/model/operational overhead | [Dependency gate](DEPENDENCY_GATES.md) | Manifest inspection only |
| KCR-07 | 9 | Implement **research-only** low-dependency comparison behind existing contracts, with no production imports | Isolated benchmark artefacts, if authorized | Not started |
| KCR-08 | 10 | Decide each feature: native improve / optional algorithm / reject / defer; record tradeoffs | Evidence-backed ADR with rollback and proof | Not started |

## Research questions, by owner
- **MemoryFormationEvaluator:** Is extraction or entity resolution actually underperforming? Do we need better source attribution, source normalization, or conflict cues?
- **MemoryTemporalEvolutionService + belief resolution:** Can a user ask *what was true on date X as KAREN knew it on date Y*? Does a late correction preserve both timelines?
- **MemoryGraphService/PostgresGraphRepository:** Do semantic and temporal graph edges return authorized, relevant evidence within the budget?
- **NeuroRecall:** Does bounded spreading activation or Personalized PageRank beat current candidates on multi-hop recall?
- **Runtime outcome/decision evidence:** Can KAREN reconstruct *why* a decision was made from immutable policy/evidence/outcome receipts without inventing causal claims?

## Scope guard
**Allowed:** read-only source analysis; local fixtures; lockfile simulations; baseline instrumentation; independent diagrams/tests; isolated dependency-free algorithms.  
**Not allowed:** installing five frameworks into KAREN, adding graph/vector databases, bypassing NeuroVault, reimplementing intent/policy in tools, granting third-party inference access to user data, shipping placeholder benchmarks as green, changing provider defaults, modifying live migrations or production Compose.

## Definition of done
- [ ] All five dossiers have exact source SHAs, licensing, direct dependencies, transitive-cost investigation, algorithm entry points and findings.
- [ ] Existing KAREN logic is classified as wired, partial, test-only, retired or unproven with source references.
- [ ] Benchmark fixtures are real, adversarial, deterministic, scoped, replayable and **run against live PostgreSQL and the intended recall entry point** where applicable.
- [ ] Results report baseline and treatment quality, p50/p95/p99, cold start, ingestion cost, CPU/RAM/storage, number of model calls, failure/degraded behavior and provenance completeness.
- [ ] RLS/tenant isolation, per-user scope, consent revocation, deletion/rebuild, cancellation and prompt/tool security pass in both arms.
- [ ] Final ADR names **at most one feature-level production change per independently justified follow-on slice**.
- [ ] No dependency added on a research documentation PR.

## Future implementation
If a feature wins, create a separately reviewed, scoped change with a single canonical owner, migration/rollback strategy, tests, and dependency budget. The wiki itself authorizes **no change**.

