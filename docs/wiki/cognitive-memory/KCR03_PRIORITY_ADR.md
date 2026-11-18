# KCR-03 | Evidence-ranked cognitive capability investments

**Decision record:** `KCOG-RESEARCH-01 / KCR-03`  
**Review date:** 2026-11-18  
**KAREN reference:** [`cff4656dc5070e52948b06b9cd878772da168903`](https://github.com/agustealo/AI-Karen/commit/cff4656dc5070e52948b06b9cd878772da168903)  
**Status:** preliminary **research execution order**, **not** vendor performance ranking, production authorization or a claim of full benchmarks.

## Decision

**Do not install LightRAG, Graphiti, Cognee, HippoRAG 2 or Semantica in KAREN's production stack.** The five upstream source studies produced candidate *techniques* with substantial overlap against KAREN's existing owners. Research findings so far justify solving native correctness and evidence gaps before approving a new runtime dependency.

The research studies were published in [KCR-02A](KCR02A_GRAPH_RETRIEVAL.md) and [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md). [KCR-01](KCR01_RETRIEVAL_LINEAGE.md) documents the storage split. The [KAREN baseline](KAREN_BASELINE.md) records canonical composition.

### Scoring and ranking discipline

The ordinal ranks below use **known implementation gaps, security impact, owner fit, and work prerequisites**, not imaginary throughput or precision scores.

- **P0 correctness/security:** A demonstrated semantic inconsistency, missing authorization assurance, or lack of verifiable production retrieval truth; fix or prove before algorithm selection.
- **P1 functional evidence:** A useful missing capability with an existing canonical owner and a testable workload.
- **P2 optional optimization:** Requires real labeled evidence of incremental gain, not a synthetic demonstration or vendor claim.
- **P3 defer:** No independently measured gap, unclear marginal benefit, or high duplication/maintenance cost.
- Any suggested change must pass **security and consent hard gates** before a quality score can qualify it. No weighted numerical scores are assigned without actual measurements.

## Ranked native work packages

| Order | ID / gate | Decision | Current KAREN owner | Specific source evidence and missing proof | External inspiration / cost decision |
| --- | --- | --- | --- | --- | --- |
| 1 | **A01 / P0** | **Prove canonical PostgreSQL retrieval and candidate score provenance.** Do not design another memory engine. | NeuroRecall + PostgresRecallRetriever + existing memory ledger | `memory_items` HNSW/FTS migrations coexist with `memory_assertion` substring recall. No actual HNSW/FTS execution shown by current canonical adapter. [KCR-01](KCR01_RETRIEVAL_LINEAGE.md) | LightRAG source selection; **new packages/services = 0** for audit |
| 2 | **A03a / P0** | **Correct half-open validity-boundary mismatch** after direct-caller audit. | `MemoryClaim` contract + `MemoryClaimStore` + `MemoryTemporalEvolutionService` | `MemoryClaim.is_valid(valid_until)` returns true although temporal interval/SQL end is exclusive; strict XFAIL records this. [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md) | Graphiti / Semantica temporal semantics; **no dependency** |
| 3 | **A04a / P0** | **Prove current-consent authorization at graph source and final evidence expansion.** | PostgresGraphRepository + PostgresEventSource + NeuroRecall + NeuroVault | Raw graph recursive CTE filters `MemoryEvent.consent_state`, while `PostgresEventSource` enforces later scoped revocation; direct graph callers must not bypass final gate. [KCR-02B](KCR02B_TEMPORAL_PROVENANCE.md) | Cognee source ownership; **no dependency** |
| 4 | **A03b / P1** | **Implement a read-only dual-clock historical query only if actual user workload proves need.** | Temporal service + governed ledger + NeuroRecall | Fields exist, but graph neighbor SQL filters `CURRENT_TIMESTAMP`; no independently selectable `valid_at` and `known_at` query demonstrated. | Semantica `query_at`, Graphiti episodes; **no added graph DB** |
| 5 | **A04b / P1** | **Prove retry-safe derived-data erasure and shared-source cleanup.** | NeuroVault lifecycle + Postgres projection workers | Real consent revocation tests exist; source-reference sharing, vector/cache/graph deletion retries and restart need end-to-end evidence. | Cognee provenance deletion planner; **adapt tests, not its store** |
| 6 | **A05 / P2** | **Reconstruct decision-to-evidence receipts without invented causes.** | Runtime OutcomeRecorder + CORTEX policy records + NeuroRecall | Recorded outcome/policy evidence exists; queryable scoped decision → source → outcome completeness unproven. | Semantica provenance; **no second recorder** |
| 7 | **A02 / P2** | **Compare bounded edge-weight propagation with current activation.** | SpreadingActivation as compute primitive, NeuroRecall as final fusion/ranking | Synthetic tests show that PPR can distinguish weighted paths when hop decay ties; real multi-hop recall delta and cost unmeasured. | HippoRAG 2 PPR; **no igraph/torch/OpenAI upgrade** |
| 8 | **A04c / P3** | **Defer extraction-pipeline redesign pending measured errors.** | MemoryFormationEvaluator + signal pipeline + entity resolver | Current extraction and normalization are present; no gold corpus demonstrates an unmet extraction precision/recall requirement. | Cognee staged extraction; **no cognify pipeline** |

**Order 1 is an evidence prerequisite.** Orders 2 and 3 are independently actionable bounded correctness/security investigations; neither should wait for retrieval-quality scores. Orders 4–8 remain contingent on their individual acceptance.

## Actual implementation ownership and boundaries

- **CORTEX decides:** intent classification, eligibility and reasoning hints. No external agent may authorize memory actions.
- **NeuroRecall selects:** retrieval activation, source fusion, deduplication, ranking, and context evidence. Graph ranking is an input, not a second selector.
- **PostgresGraphRepository is a scoped, temporal *projection***; it may not become an independent durable truth store.
- **NeuroVault writes and erases:** source event consent, durable persistence, projection life cycles, audit and deletion.
- **OutcomeRecorder owns execution outcomes:** an explanation must reference persisted evidence; a PPR rank or model explanation is not evidence of causation.
- **UI reflects backend truth:** no claimed saved state, retrieval source, historical proof or fallback without receipts.

## Dependency gate for every candidate

A production dependency request must supply a fully resolved software bill of materials, exact Python/OS/architecture compatibility, direct/transitive/native package delta, pinned license/SPDX and model terms, vulnerabilities, startup footprint, CPU/RAM/disk/latency, egress/telemetry, rollback and a benchmark differential on identical authorized input.

**Unmeasured fields must be marked UNKNOWN, not zero.** "New deps = 0" here is the **proposal for native research slices**, not a claim that installing any upstream framework would be cost-free.

Known source-manifest stop signs at the pinned upstream versions:

- **HippoRAG 2:** `openai>=3.3.1,<4` conflicts with KAREN's `openai==2.32.0`; also pinned Torch, Transformers, igraph and LiteLLM.
- **Graphiti:** requires Neo4j Python driver and generally a supported graph backend, in addition to an embedding/LLM integration.
- **Cognee:** adds a broad graph/vector/extraction stack with native wheel burden.
- **LightRAG:** adds its own storage, inference and graph retrieval owners; KAREN already has PostgreSQL graph and NeuroRecall.
- **Semantica:** broad RDF/provenance/scientific dependencies for functions KAREN already partially owns.

See [dependency manifest audit](DEPENDENCY_GATES.md) and [pinned evidence register](EVIDENCE_REGISTER.md). No package installs are approved by this ADR.

## Acceptance and follow-on sequence

**KCR-04A, baseline retrieval proof:** first verify `memory_items` writes and `memory_assertion` ledger projection consumers, native SQL/EXPLAIN, real pgvector + FTS candidate generation, index use, and scored evidence at `MemoryRuntimeManager -> NeuroRecall`. Use isolated PostgreSQL with actual migrations; do not claim the unrelated connected Supabase project is Karen. Report R01/R02/R03/R08/R09/R12 and p50/p95/p99. Stop if scope or consent fails.

**KCR-04B, temporal boundary correctness:** audit callers including `MemoryClaimStore.get_valid_claims()`, update only the canonical `MemoryClaim.is_valid()` exclusive endpoint (if callers agree), remove the strict XFAIL, and run architecture/temporal tests on the same exact head. Avoid overlap with any pending PR editing the temporal research test; preserve historical source events. This correction should have its own small PR, not be hidden in this research documentation change.

**KCR-05, leakage and deletion proof:** directly exercise graph-source retrieval and event-source consent gates under revoked scopes and cross-tenant identities, plus shared derived object deletion, partial failure, idempotent retry, restart and projection rebuild in real PostgreSQL. Confirm both historical and current reads apply current authorization.

**KCR-06, provider-neutral dependency budget:** run isolated solver/SBOM and package vulnerability checks against the *actual* KAREN pins; measure wheel/image/resource deltas without installing candidate frameworks into production.

**KCR-07, conditional algorithm benchmark:** only after real graph-neighborhood source scope and vector/FTS truth are established, compare real KAREN spreading activation with a low-dependency weighted random-walk variant. Score Recall@K, nDCG@10, MRR, evidence attribution, budget and resource use on independent labeled cases.

**KCR-08, final ADR:** one technique per independently justified production slice. Reject or defer any treatment with no demonstrated gain, unknown compliance, unacceptable resource delta or duplicate responsibility.

## Decision log

| Check | Result |
| --- | --- |
| Five source-pinned framework studies | Completed initial + targeted mechanical inspection |
| Real post-merge synthetic/SQL CI probes | Exist and executed in Main Quality; **not** live semantic retrieval proof |
| Running PostgreSQL pgvector/FTS performance | **UNKNOWN** |
| Current temporal-boundary inconsistency | **SOURCE-INSPECTED; not fixed here** |
| Live dual-clock as-of API | **UNPROVEN** |
| Shared-source erasure across derived stores | **UNPROVEN** |
| Cross-system decision-to-evidence reconstruction | **UNPROVEN** |
| Resolved dependency SBOM or runtime footprint | **UNKNOWN** |
| Approved production memory-framework changes | **NONE** |

**Revisit rule:** This is a reversible research-order decision. Reassess only when an experiment returns reproducible source, test, resource and security evidence meeting the benchmark contract. External marketing or GitHub stars alone are not acceptance.
