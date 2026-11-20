# 03 | Graph-native discovery, cognitive memory and investigation design

**Implementation truth:** Memory graph and graph retrieval exist on the verified mainline. The bounded retrieval evidence graph and accessible Graph lens are now merged via [PR #1119](https://github.com/agustealo/AI-Karen/pull/1119); a full cross-source investigation graph is still proposed. Persistent cross-source investigation sessions, graph-selected entity followups and synchronized temporal/workflow lenses are **future work**.

## 1. Four distinct graph responsibilities

| Graph concept | What it represents | Existing implementation / source of truth | Publication rule |
| --- | --- | --- | --- |
| Cognitive memory graph | Entities, events, assertions, provenance, temporal relationships | `core/memory/graph/service.py` + `platform/memory/postgres/graph_repository.py`, governed PostgreSQL | Scope and source-authorize, then let NeuroRecall select recall memories |
| Retrieval evidence graph | Document/source and passage provenance from an executed search | Merged `services/search/evidence_graph_projection.py` in PR #1119 | Exact fetched-source URL relationship only, no fabricated entity/claim edges |
| Investigation graph | Questions, evidence, claims, disputed relations, selected scope, investigation state | **Proposed typed server-authorized projection** over governed sources and memory/events | No standalone graph database, no private memory export, no unverified relationship as fact |
| Workflow graph | Plans, steps, dependencies, tool runs, approval/termination states | Canonical runtime and LangGraph for true multistep workflows | Distinguish proposed vs running vs verified completion; server receipt required |

Reasoning/capsule graphs may aid internal explainability and diagnostics. **Do not publish internal chain-of-thought or model hidden reasoning traces** in a consumer graph.

## 2. Durable memory graph internals

- `LeanGraphService` projects authorized memory events and assertions into typed `GraphEdge` relationships. Event and assertion sources remain canonical ledger records; the graph holds references, not duplicated full memory text.
- `GraphEdge` includes `from_id`, `to_id`, relationship, `tenant_id`, `user_id`, `conversation_id`, confidence, weight, salience, lifecycle, `source_memory_id`, `source_event_id`, schema version and four temporal fields.
- `LeanGraphConfig` defaults to `postgres`; `in_memory` exists for controlled testing; `kuzu` is explicitly retired/rejected. It sets projection limits for entities and edges and relationship toggles.
- `PostgresGraphRepository` uses migration-owned schema, `async_transaction_scope`, scoped entity upsert, temporal relation persistence and bounded recursive traversal.
- `EntityResolver` owns normalization and ambiguity handling. Do not lowercase and merge two people/entities merely because text matches.
- `HybridRetrievalRouter._query_graph` resolves entity cues, fetches graph context, then retrieves canonical scoped event payloads; graph paths with missing event evidence do not generate pseudo-memories.
- `NeuroRecall.recall` validates explicit non-default tenant and user, bounded deadlines, candidate fusion, user/tenant alignment, guardrails, source-lineage authorization and final ranking.

**Do not bypass NeuroRecall by calling `PostgresGraphRepository` directly to populate a public personal-memory UI.** An authorized graph projection may inspect already-selected candidate provenance through a reviewed runtime-owned path, with a second source ACL check if the requested graph expansion adds references.

## 3. Relationship vocabulary and epistemic discipline

Refer to [MEMORY_GRAPH_DEV_SHEET](../../development/MEMORY_GRAPH_DEV_SHEET.md) for the canonical evolving ontology. Examples include:

| Type | Intended semantics | Minimum backing proof |
| --- | --- | --- |
| `MENTIONS` | A governed source/event mentions an entity | Source/event ID and entity resolution status |
| `ALIAS_OF` / `SAME_AS` | Identity relation | Audited entity-resolution outcome; reversible merges |
| `ASSERTS` | Evidence asserts a claim | Exact source/event text and claim extraction provenance |
| `SUPPORTED_BY` | Claim has supporting evidence | Source ID, passage span, verification state |
| `CONTRADICTS` | Conflicting statements or observations | Two source-backed claims and temporal context; not automatic proof one is wrong |
| `SUPERSEDES` | Newer version replaces previous fact | Revision history, world-time and observation-time |
| `DEPENDS_ON` / `REQUIRES` | Explicit prerequisite | Dependency source or executed workflow contract |
| `CAUSED` | Causal assertion | Substantive causal evidence; temporal co-occurrence alone is insufficient |
| `DERIVED_FROM` | Passage/content originates from source | Exact fetched-source evidence, not semantic similarity |

A graph renderer must show the **verification state of each edge**. An observed citation relationship is not an established causal relationship. Confidence of extraction/relevance is not truth probability. No free-form relationship names from untrusted model output should be committed without registry validation.

## 4. Proposed investigation graph contract

**This is design guidance, not an existing live endpoint.** Use a backend-owned Pydantic/dataclass contract at a reviewed runtime aggregation boundary; avoid a new route if the existing plugin/runtime response can carry the data safely.

```text
InvestigationSnapshot:
  schema_version, investigation_id, snapshot_id, revision, status
  tenant/user/project scope stored server-side (never accepted from browser)
  observed_at, generated_at, as_of?, cursor?, truncated, degraded_reasons[]
  nodes[]: id, kind, label, source_ids[], verification_state, temporal fields?
  edges[]: id, from, to, relationship_type, source_ids[],
           path?, hop_count?, verification_state, temporal fields?
  provenance[]: canonical source/event/memory references and permission state
  view_manifest: enabled lenses and reasons for unavailable ones
```

**Never include unrestricted tenant/user identifiers or raw private memory bodies merely to power the visualization.** The graph API resolves authorized IDs server-side and returns bounded display-safe fields. Treat non-availability as an explicit read state. A `cursor` must encode server-validated scope, revision and traversal bounds so it cannot be replayed under another identity.

Recommended node kinds: `source`, `passage`, `entity`, `claim`, `event`, `question`, `task`, subject to verified source support. Do not add a synthetic “person” or “memory” node for a guessed entity.

## 5. Candidate retrieval to graph display

```text
Authorized user request
  -> runtime validates user/tenant/session/project, RBAC and query
  -> CORTEX selects eligible capabilities
  -> standard search retrieves source evidence
  -> NeuroRecall retrieves *candidate* memory via STM/graph
  -> NeuroRecall applies scope/consent/lineage + final selection
  -> runtime graph-view projector checks selected source IDs, consent,
     temporal constraints, output budgets and fresh ACL
  -> versioned nodes/edges tied to original evidence
  -> browser renders graph + list/table accessible alternative
```

**Key invariant:** an intermediate graph path containing a foreign or revoked event must not leak that event's ID, label, edge weight, count or existence in the response. Denial is not a partially successful graph. An authorized user may request greater detail, but not bypass source ACL, max depth or request budgets.

## 6. Multi-hop, time, and ranking

Traversal must enforce a hard `max_depth`, per-node fanout, visited node cap, cycle detection, relationship allowlist, latency/deadline and page limits **before** materialization. Every hop needs server-side tenant/user/consent filtering, not only the seed. Prefer PostgreSQL recursive queries already in `PostgresGraphRepository`; do not add Neo4j, Graphiti, NetworkX or another memory backend because the interface wants lines between circles.

Use both **valid time** (“was this true on date X?”) and **known/observed time** (“what did Karen know on date Y?”) when source and schema support them. Null timestamps remain unknown, not current. Superseded facts should be inspectable historically but excluded from current-claim views unless explicitly requested and authorized.

NeuroRecall owns ranking and candidate fusion. Experimental HippoRAG/LightRAG techniques are documented in [KCR02A](../cognitive-memory/KCR02A_GRAPH_RETRIEVAL.md); the repository research note says their production adoption is **not approved** without real-user benchmark and security evidence. Do not install a second engine on the strength of synthetic benchmark ties.

## 7. Implementation stages

1. **Evidence source graph:** only exact source→passage links, bounded and backend-authored. [PR #1119](https://github.com/agustealo/AI-Karen/pull/1119), merged in `main` at `9b956d892a8f4773c0173a7773af74d23ad0eb33`; not yet target-host consumer certified.
2. **Authorized memory projection:** runtime-selected, NeuroRecall-authorized memories and metadata, no raw graph exposure; explicit degraded/empty state, security tests first.
3. **Graph interaction:** entity focus, expandable neighborhood, evidence-highlighted selections, linked timeline; screen-reader list alternative.
4. **Durable investigation identity:** server-created session ID, snapshot revision and selected source IDs, governed persistence and source revocation invalidation.
5. **Workflow view:** runtime/LangGraph receipts, approval checkpoints, cancellation versus verified worker termination, contextual authorized actions.
6. **Advanced reasoning:** contradiction reconciliation, time-aware source comparisons and optional graph ranking algorithms only after scored retrieval, authorization and p95 benchmarks.

## 8. Adversarial graph tests

Test missing tenant, default tenant, wrong user, changed project, revoked document, stale source revision, guessed event ID, conflicting entity aliases, negative/invalid depth, cycles, large fanout, timing-based existence leak, disallowed edge type, self-loop, unsourced claim, conflicting temporal evidence, timeout and cancellation. Confirm no sensitive graph data in logs, progress indicators or negative response counts.

For the consumer, test no graph payload, single source, discovery-only snippet, complete fetched source, multiple passages, truncated graph, stale result tab state, cross-view selection and keyboard-only operation.
