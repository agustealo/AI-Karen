# Reproducible research benchmark contract

**Status: PROPOSED ONLY. No experiment has been run for this wiki.** KAREN's existing `tests/benchmarks/memory` entries for recall latency, quality, long-range recall and selective forgetting are currently vacuous `assert True` tests. This contract describes how to replace that absence of evidence.

## Baseline and experiment
- Baseline A: exact-current `MemoryRuntimeManager -> NeuroRecall` read path with canonical PostgreSQL, graph and Redis; record configuration, data counts, index types and query plan.
- Baseline B (optional): isolated source retriever runs to determine vector, FTS, lexical and graph contribution.
- Treatment: **one capability delta at a time**, using identical authorized input data, models, scope, prompt version and hardware.
- Run deterministic randomized query order, multiple seeds, warm/cold modes and both replays of fresh and persisted datasets. Capture absolute performance as well as paired deltas.
- Never send private KAREN user data to upstream services. Use synthetic and explicitly licensed corpora; keep any experiment processes isolated.

## Required gold cases
| ID | Suite | Question class | Expected proof |
| --- | --- | --- | --- |
| R01 | Paraphrase | Semantic restatement with low lexical overlap | Correct source recalled, nDCG@10/Recall@10 |
| R02 | Lexical | Exact ID or uncommon keyword | FTS/lexical retriever provides correct source |
| R03 | 2–5 hop graph | Entity → event → decision → outcome | Relevant path with source IDs and no leakage |
| R04 | Association | Weak indirect cue vs distractor cluster | True associations outrank unrelated neighbors |
| R05 | Valid-time | Historical fact effective at T1 | Correct fact for `valid_at=T1` |
| R06 | Known-time | Late correction learned at T2 about T1 | Correct **as-known-at** snapshot; no retroactive fabrication |
| R07 | Contradiction | Same slot conflicting evidence; explicit vs inferred | Quarantine or governed supersession with original record |
| R08 | Erasure | User withdraws consent and restarts | No recalled or derived leakage; source/graph/vector invalidated |
| R09 | Cross-tenant | Identical IDs/content in different principals | Zero unauthorized candidates through every traversal edge |
| R10 | Decision evidence | Ask why a previous decision occurred | Policy/evidence/outcome lineage, explicit uncertainty |
| R11 | Poisoning | Retrieved text instructs runtime to override memory policy | Prompt injection blocked, response grounded |
| R12 | Degradation | Redis, PG, embedding/model or retriever times out | Honest degradation, no fabricated memory save or retrieval |
| R13 | Entity collision | Same alias for unrelated entities | Identities separated; scope/ambiguity preserved |
| R14 | Replay & restart | Rebuild projections after correction/deletion | Stable IDs, no stale resurfaced memory |

## Measurements
- **Retrieval correctness:** Recall@{5,10}, nDCG@10, MRR, exact source lineage, contradiction errors, as-of accuracy, false associations, hallucinated provenance.
- **User-facing correctness:** answer fidelity, grounded citation to stored event, abstention rate, contextual token budget.
- **Operations:** p50/p95/p99 wall-clock latency, timeouts, success/failure rate, cold start, ingestion docs/s, extraction calls/tokens, graph nodes/edges, memory/CPU/GPU/disk.
- **Security:** cross-tenant false positives (must be **zero**), consent violation (zero), incorrect persisted save claims (zero), ungoverned external egress (zero).

## Proposed promotion thresholds, subject to baseline calibration
- Every security/consent/RBAC/erasure case passes (hard blocker regardless of score).
- Quality must show a reproducible improvement on its *target suite* over A with no material regression elsewhere; proposed target is **>=5 percentage points** in relevant recall metric across adjudicated fixtures, plus confidence intervals/repeats.
- Target p95 recall <= current **300 ms default NeuroRecall deadline** on agreed reference hardware, or justify scope-specific budgets without silently increasing the consumer deadline.
- Require an explicit maximum cost budget for each experiment, no surprise network inference, and reported new dependency/service count.
- A feature with equal quality and lower complexity can win; a feature that adds a service to solve an already-solved case does not.

## Proof execution requirements
Real PostgreSQL database, applied migrations, actual configured embeddings if evaluating vector search, current runtime entry point, independent expected outputs, tenant-isolated fixtures, failure injection, cancellation, restart, and reproducible command log. Pure unit tests and source-shape checks are useful but insufficient for "live-proven."

Report **exact git SHAs, model/provider revisions, environment lock, CPU/GPU, query count, dataset hashes, measurement script, raw JSON/CSV results, confidence intervals, and deviations**. No numeric performance claims in this wiki until those outputs exist.

