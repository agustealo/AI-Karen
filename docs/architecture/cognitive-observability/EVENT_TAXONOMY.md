# Cognitive Event Taxonomy

## Canonical Event Envelope

Every cognitive event conforms to the `CognitiveEvent` envelope:

```
CognitiveEvent
├── event_id              str    Unique event identifier (UUID)
├── event_type            str    Taxonomic type from this specification
├── correlation_id        str    Whole-request correlation identifier
├── request_id            str    Request this event belongs to
├── causation_id          str    Event that directly caused this event
├── parent_event_id       str    Structural trace parent
├── tenant_id             str    Tenant scope
├── user_id               str    User scope (governed)
├── session_id            str    Session scope
├── conversation_id       str    Conversation scope
├── cognitive_stage       str    Cognitive stage enum
├── policy_version        str    Cognitive policy version
├── schema_version        str    Event schema version
├── occurred_at           datetime  When the event occurred
├── duration_ms           int    Stage duration in milliseconds
├── status                str    SUCCESS | PARTIAL | DEGRADED | FAILED | SKIPPED
├── reason_codes          list[str]  Structured reason codes
├── input_refs            list[str]  References to input artifacts
├── output_refs           list[str]  References to output artifacts
└── safe_attributes       dict   Additional governed attributes
```

### Identity Fields

| Field | Purpose | Example |
|---|---|---|
| `event_id` | Unique identifier for this event | `evt-7f3a...` |
| `correlation_id` | Groups all events for one request | `corr-9b2c...` |
| `request_id` | The specific request | `req-4d1e...` |
| `causation_id` | The event that caused this event | `evt-8c4b...` |
| `parent_event_id` | Structural parent in trace tree | `evt-2a1f...` |

### Critical Distinction

```
correlation_id  = whole request (all events share this)
causation_id    = event that caused this event (causal chain)
parent_event_id = structural trace parent (tree hierarchy)
```

This lets us reconstruct **actual cognition** instead of relying on timestamps and hope.

### Cognitive Stage Enum

| Stage | Description |
|---|---|
| `PERCEPTION` | Intent recognition, input understanding |
| `RECALL` | Memory retrieval, associative activation |
| `BELIEF` | Belief assessment, conflict detection |
| `GOAL` | Goal resolution, intention formation |
| `SALIENCE` | Salience assessment, priority signaling |
| `CONTEXT` | Context planning, item selection |
| `REASONING` | Reasoning strategy execution |
| `META_COGNITION` | Self-monitoring, verification, loop detection |
| `ADAPTIVE` | Adaptive recommendation ranking |
| `CORTEX` | Behavior candidate generation and selection |
| `RUNTIME` | Execution of selected behavior |
| `LEARNING` | Learning signal generation |
| `REFLECTION` | Reflection and consolidation |

### Status Values

| Status | Meaning |
|---|---|
| `SUCCESS` | Stage completed successfully |
| `PARTIAL` | Stage completed with partial results |
| `DEGRADED` | Stage completed in degraded mode |
| `FAILED` | Stage failed |
| `SKIPPED` | Stage explicitly skipped (must have reason code) |
| `NOT_APPLICABLE` | Stage not applicable to this request |

## Event Types

### Lifecycle Events

| Event | Stage | Description |
|---|---|---|
| `cognition.started` | PERCEPTION | Cognitive processing initiated |
| `cognition.completed` | REFLECTION | Cognitive processing completed |

### Intelligence Events

| Event | Stage | Description |
|---|---|---|
| `intelligence.completed` | PERCEPTION | Intelligence analysis completed |

### Recall Events

| Event | Stage | Description |
|---|---|---|
| `recall.requested` | RECALL | Memory recall requested |
| `recall.completed` | RECALL | Memory recall completed |
| `recall.degraded` | RECALL | Memory recall completed in degraded mode |

### Belief Events

| Event | Stage | Description |
|---|---|---|
| `belief.assessment_started` | BELIEF | Belief assessment initiated |
| `belief.assessed` | BELIEF | Belief assessment completed |
| `belief.conflict_detected` | BELIEF | Belief conflict detected |

### Goal/Intention Events

| Event | Stage | Description |
|---|---|---|
| `goal.context_resolved` | GOAL | Goal context resolved |
| `intention.triggered` | GOAL | Intention triggered |

### Salience Events

| Event | Stage | Description |
|---|---|---|
| `salience.assessed` | SALIENCE | Salience assessment completed |

### Context Events

| Event | Stage | Description |
|---|---|---|
| `context.planned` | CONTEXT | Context plan created |
| `context.item_selected` | CONTEXT | Context item selected for inclusion |
| `context.item_omitted` | CONTEXT | Context item explicitly omitted |

### Reasoning Events

| Event | Stage | Description |
|---|---|---|
| `reasoning.started` | REASONING | Reasoning stage initiated |
| `reasoning.completed` | REASONING | Reasoning stage completed |
| `reasoning.strategy_changed` | REASONING | Reasoning strategy changed mid-process |

### Meta-Cognition Events

| Event | Stage | Description |
|---|---|---|
| `meta.assessed` | META_COGNITION | Meta-cognitive assessment completed |
| `meta.verification_required` | META_COGNITION | Verification required before proceeding |
| `meta.loop_detected` | META_COGNITION | Cognitive loop detected |
| `meta.stop_recommended` | META_COGNITION | Stop recommended by meta-cognition |

### Adaptive Events

| Event | Stage | Description |
|---|---|---|
| `adaptive.ranked` | ADAPTIVE | Adaptive recommendations ranked |

### CORTEX Events

| Event | Stage | Description |
|---|---|---|
| `cortex.candidates_generated` | CORTEX | Behavior candidates generated |
| `cortex.candidate_rejected` | CORTEX | Behavior candidate rejected |
| `cortex.behavior_selected` | CORTEX | Final behavior selected |
| `cortex.abstained` | CORTEX | CORTEX abstained from deciding |

### Runtime Events

| Event | Stage | Description |
|---|---|---|
| `runtime.execution_started` | RUNTIME | Behavior execution started |
| `runtime.execution_completed` | RUNTIME | Behavior execution completed |
| `runtime.execution_failed` | RUNTIME | Behavior execution failed |

### Learning Events

| Event | Stage | Description |
|---|---|---|
| `learning.signal_created` | LEARNING | Learning signal created |
| `learning.signal_rejected` | LEARNING | Learning signal rejected |

### Reflection Events

| Event | Stage | Description |
|---|---|---|
| `reflection.started` | REFLECTION | Reflection stage initiated |
| `reflection.candidate_created` | REFLECTION | Reflection candidate created |
| `reflection.candidate_promoted` | REFLECTION | Reflection candidate promoted |
| `reflection.candidate_rejected` | REFLECTION | Reflection candidate rejected |

## Event Type Format

Event types follow the pattern:

```
<stage>.<action>
```

Where `<stage>` is the lowercase cognitive stage and `<action>` is a past-tense verb describing what occurred.

## Reason Codes

Reason codes follow the pattern:

```
<DOMAIN>_<SPECIFIC_REASON>
```

Examples:

| Code | Meaning |
|---|---|
| `RECALL_SKIPPED_NO_RELEVANT_MEMORIES` | Recall skipped: no relevant memories found |
| `RECALL_DEGRADED_TIMEOUT` | Recall degraded: retrieval timeout |
| `BELIEF_CONTRADICTS_PRIOR` | Belief contradicts prior belief |
| `CONTEXT_OMITTED_TOKEN_BUDGET` | Context item omitted due to token budget |
| `CORTEX_REJECTED_POLICY_VIOLATION` | Candidate rejected: policy violation |
| `CORTEX_ABSTAINED_LOW_CONFIDENCE` | CORTEX abstained: low confidence |
| `META_VERIFICATION_CONFLICTING_EVIDENCE` | Verification required: conflicting evidence |
| `LEARNING_REJECTED_INSUFFICIENT_EVIDENCE` | Learning signal rejected: insufficient evidence |
| `REFLECTION_REJECTED_BELOW_THRESHOLD` | Reflection candidate rejected: below promotion threshold |

## Schema Versioning

Each event carries a `schema_version` field. Schema evolution rules:

1. **Additive changes** (new optional fields): Minor version bump
2. **Required field additions**: Major version bump
3. **Field removals**: Major version bump with deprecation period
4. **Semantic changes**: Major version bump

Consumers must handle multiple schema versions gracefully.
