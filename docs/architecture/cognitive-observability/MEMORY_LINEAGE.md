# Memory Lineage Specification

## Purpose

A memory influencing behavior must be traceable through the full cognitive pipeline:

```
stored episode
    ↓
recall candidate
    ↓
recall ranking
    ↓
belief assessment
    ↓
context inclusion
    ↓
behavior decision
```

This is essential for debugging:

- "Why did Karen remember that?"
- "Why did that memory affect this answer?"

## MemoryLineage Structure

```
MemoryLineage
├── lineage_id               str    Unique lineage identifier
├── memory_id                str    The memory being traced
├── trace_id                 str    Parent cognitive trace
├── request_id               str    Request this memory influenced
├── correlation_id           str    Request correlation
├── storage_ref              str    Reference to stored episode
├── recall_candidate_ref     str    Reference to recall candidate record
├── recall_rank              int    Rank in recall results
├── recall_score             float  Recall relevance score
├── belief_assessment_ref    str    Reference to belief assessment
├── belief_influence         str    SUPPORTED | CONTRADICTED | NEUTRAL
├── context_inclusion_ref    str    Reference to context inclusion decision
├── context_included         bool   Was this memory included in context?
├── context_omission_reason  str    Reason if omitted from context
├── decision_ref             str    Reference to behavior decision
├── decision_influence       str    How the memory influenced the decision
├── occurred_at              datetime  When the influence occurred
└── schema_version           str    Schema version
```

## Lineage Stages

### Stage 1: Storage

The memory exists as a stored episode. Reference: `storage_ref`.

This links to the canonical memory storage record (existing `MemoryEntry`, `MemoryClaim`).

### Stage 2: Recall Candidate

The memory was retrieved as a recall candidate. Reference: `recall_candidate_ref`.

Captures:
- That the memory was retrieved
- Its rank in the recall results
- Its relevance score

### Stage 3: Recall Ranking

The memory was ranked among candidates. Captured via `recall_rank` and `recall_score`.

This enables answering: "Was this memory in the top-N? How did it score?"

### Stage 4: Belief Assessment

The memory was assessed for belief consistency. Reference: `belief_assessment_ref`.

Captures:
- Whether the memory supported, contradicted, or was neutral to current beliefs
- Any belief conflicts detected

### Stage 5: Context Inclusion

The memory was considered for context inclusion. Reference: `context_inclusion_ref`.

Captures:
- Whether the memory was included in the context window
- If omitted, why (token budget, relevance threshold, etc.)

### Stage 6: Behavior Decision

The memory influenced the final behavior decision. Reference: `decision_ref`.

Captures:
- How the memory influenced the decision
- Whether it was a primary or secondary influence

## Influence Types

| Influence | Description |
|---|---|
| `DIRECT` | Memory directly determined the behavior |
| `SUPPORTING` | Memory supported the chosen behavior |
| `CONTRASTING` | Memory contrasted with the chosen behavior (informed rejection) |
| `BACKGROUND` | Memory provided background context |
| `PRIORITY` | Memory changed the priority of behaviors |

## Omission Reasons

When a memory is recalled but not included in context:

| Reason | Description |
|---|---|
| `TOKEN_BUDGET` | Context token budget exhausted |
| `RELEVANCE_THRESHOLD` | Below relevance inclusion threshold |
| `POLICY_EXCLUSION` | Excluded by policy (e.g., sensitive memory) |
| `DUPLICATE` | Duplicate of already-included memory |
| `CONTRADICTED` | Contradicted by higher-confidence memory |
| `STALE` | Memory too old for inclusion |

## Traceability Requirements

### Forward Trace (Memory → Decision)

Given a memory ID, we must be able to trace:

1. Which requests recalled this memory
2. What rank it achieved
3. Whether it was included in context
4. What decisions it influenced
5. How it influenced those decisions

### Reverse Trace (Decision → Memory)

Given a decision ID, we must be able to trace:

1. Which memories were recalled
2. Which were included in context
3. Which influenced the decision
4. What beliefs were affected
5. What the recall scores were

## Relationship to Existing Structures

| Existing Structure | MemoryLineage Role |
|---|---|
| `MemoryEntry` | The stored memory being traced |
| `MemoryClaim` | Belief-level claims derived from memory |
| `RecallScoreComponents` | Recall scoring breakdown |
| `SalienceScore` | Salience dimensions for recall priority |
| `MemoryProcessingStage` | Lifecycle stage tracking |
| `ProspectiveMemory` | Intention-based memory triggers |

## Privacy Constraints

Memory lineage must never embed:

- Memory plaintext content
- Private memory text
- Full conversation contents
- Sensitive document bodies

Only references (`memory_ref`, `claim_ref`, `evidence_ref`) and structured metadata (rank, score, influence type) may be stored.

See `PRIVACY_REDACTION.md` for full redaction rules.

## Deletion-Aware Tracing

If memory `m123` is deleted:

- Historical telemetry may retain `memory_ref=m-123` where governance permits
- It must **not** retain deleted semantic content
- Deletion must not create a loophole where observability becomes a shadow memory database

See `PRIVACY_REDACTION.md` for deletion-aware tracing rules.
