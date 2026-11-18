# AI KAREN | Cognitive Memory Research Wiki

> Sprint: **KCOG-RESEARCH-01** · Research baseline: **2026-11-17** · Status: **initial source review complete; experiments not executed** · Decision: **no framework adoption authorized**

This is the canonical **research wiki**, not a proposal to replace KAREN. It studies the capabilities of five public frameworks, identifies what KAREN already implements, and specifies dependency-free experiments. It intentionally adds **no runtime packages, services, databases, or changes to production orchestration**.

## Navigation
| Page | Purpose |
| --- | --- |
| [Sprint board](SPRINT.md) | Ten-working-day work packages, acceptance, artifacts, owners |
| [Karen baseline](KAREN_BASELINE.md) | Existing implementation and integration-truth inventory |
| [Capability matrix](CAPABILITY_MATRIX.md) | Framework strengths compared with existing KAREN components |
| [Dependency gates](DEPENDENCY_GATES.md) | License, direct/transitive cost, Python conflicts, security |
| [Benchmark contract](BENCHMARK_CONTRACT.md) | Reproducible, security-aware evaluation and thresholds |
| [Candidate backlog](ADAPTATION_BACKLOG.md) | Smallest feature-level experiments, ownership and proof |
| [Evidence ledger](EVIDENCE_REGISTER.md) | Pinned upstream SHA, claim quality and unverified items |
| [LightRAG](projects/LIGHTRAG.md) | PostgreSQL graph storage, retrieval modes, ingestion |
| [Graphiti](projects/GRAPHITI.md) | Temporal episodes, validity, contradiction handling |
| [Cognee](projects/COGNEE.md) | Structured extraction, incremental graph processing |
| [HippoRAG 2](projects/HIPPORAG2.md) | Personalized PageRank and associative multi-hop recall |
| [Semantica](projects/SEMANTICA.md) | Provenance, temporal truth maintenance and decision context |

## Architecture non-negotiables
1. **CORTEX decides** intent/routing/policy eligibility; runtime authorizes and executes.
2. **NeuroRecall** owns retrieval strategy, candidate fusion, deduplication, ranking and selection.
3. **NeuroVault** governs durable writes, consent, lifecycle, erasure, and provenance.
4. **Supabase/PostgreSQL** is the authoritative durable memory and graph substrate; **Redis** owns bounded STM.
5. Graph, temporal, causal and associative techniques are **subordinate algorithms or derived projections**, never alternate memory systems.
6. Do not resurrect retired **Milvus, Elasticsearch, Kuzu, or Neo4j** memory backends for research.
7. Do not mistake source code, a passing mocked test, vendor benchmarks, or logging metadata for **live acceptance**.

## Evidence labels
- **INSPECTED**: exact, version-pinned upstream implementation or manifest was read.
- **DOCUMENTED**: official docs state a capability; implementation/fitness not independently proven.
- **WIRED**: KAREN production composition imports/instantiates the mechanism; host execution not necessarily confirmed.
- **TESTED**: named local/unit/integration evidence exists; must state whether a real DB/model was exercised.
- **UNPROVEN**: unresolved behavior, baseline, performance, security, or availability.
- **PROPOSED**: candidate experiment or acceptance threshold, not an established result.

Do not promote a proposal to tested or a static test to production-proven without evidence. See [evidence ledger](EVIDENCE_REGISTER.md).

## Research method
Read official upstream docs + GitHub source + dependency manifests at pinned commits. Write independent functional specifications and test cases. Reuse public concepts or legally licensed source with full notices **only if explicitly approved**. Do not copy vendor implementations by default; never assume a GitHub repo grants rights beyond its license.

**Entry gate:** [KAREN memory architecture](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/docs/development/MEMORY.md) and [dependency policy](https://github.com/agustealo/AI-Karen/blob/6b70128174aa76f8eda3700d9079f73a1849b62a/requirements.txt).

**Exit state:** a reviewed accept/reject/defer ADR supported by comparative tests; **no deployment permission is implied**.

