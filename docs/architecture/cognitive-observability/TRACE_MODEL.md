# Cognitive Trace Model

## Purpose

Define the canonical trace/event model needed to explain **why Karen thought, decided, verified, remembered, learned, or abstained** on any request.

This specification owns **forensic explainability**: the ability to reconstruct cognitive decisions after the fact without relying on timestamps and hope.

## Scope

This document defines:

- The canonical `CognitiveTrace` structure
- The `CognitiveEvent` envelope
- Event taxonomy
- Decision lineage requirements
- Memory lineage requirements
- Learning lineage requirements
- Privacy and redaction rules
- Trace sensitivity classes
- Deletion-aware tracing
- Replay semantics
- Counterfactual replay
- Explainability levels
- Trace completeness requirements

This specification does **not** define:

- Runtime wiring or emission code
- OpenTelemetry or Prometheus configuration
- Logger implementation changes
- Cognitive logic changes

This sprint designs the **black box recorder**, not the aircraft controls.

## Canonical Cognitive Trace

Every request should eventually have one lineage:

```
CognitiveTrace
├── request
├── perception / intent
├── recall
├── beliefs
├── goals / intentions
├── salience
├── context selection
├── reasoning
├── meta-cognition
├── adaptive recommendations
├── CORTEX decision
├── runtime outcome
├── learning signals
└── reflection / consolidation candidates
```

This is **not** a giant serialized brain dump. It is an **event graph with references**.

### Design Principles

1. **Reference, don't embed.** Events link to each other by ID, not by nesting full payloads.
2. **Correlation over timestamp.** Causation is explicit via `causation_id`, not inferred from wall clocks.
3. **Structured evidence, not raw reasoning.** No chain-of-thought dumps. Only structured decision evidence.
4. **Deletion-safe.** References survive deletion; content does not.
5. **Sensitivity-classed.** Every attribute has a sensitivity class governing what may be stored.

### Trace Lifecycle

```
cognition.started
    ├── intelligence.completed
    ├── recall.requested → recall.completed | recall.degraded
    ├── belief.assessment_started → belief.assessed | belief.conflict_detected
    ├── goal.context_resolved → intention.triggered
    ├── salience.assessed
    ├── context.planned → context.item_selected | context.item_omitted
    ├── reasoning.started → reasoning.completed | reasoning.strategy_changed
    ├── meta.assessed → meta.verification_required | meta.loop_detected | meta.stop_recommended
    ├── adaptive.ranked
    ├── cortex.candidates_generated → cortex.candidate_rejected | cortex.behavior_selected | cortex.abstained
    ├── runtime.execution_started → runtime.execution_completed | runtime.execution_failed
    ├── learning.signal_created | learning.signal_rejected
    ├── reflection.started → reflection.candidate_created → reflection.candidate_promoted | reflection.candidate_rejected
    └── cognition.completed
```

## Relationship to Existing Observability

This specification extends the existing observability subsystem (`core/observability/`) with cognitive-stage awareness. The existing `RuntimeEvent` and `ObservabilityContext` provide the transport layer; this specification defines the cognitive semantics layered on top.

Key integrations:

| Existing Concept | Cognitive Trace Concept |
|---|---|
| `ObservabilityContext.correlation_id` | `CognitiveEvent.correlation_id` (whole request) |
| `RuntimeEvent.event_id` | `CognitiveEvent.event_id` |
| `RuntimeEvent.event_type` | `CognitiveEvent.event_type` (cognitive taxonomy) |
| `DecisionProvenance` | `DecisionLineage` (expanded) |
| `ExecutionTrajectory` | `CognitiveTrace` (cognitive-stage enriched) |
| `FeatureSnapshot` | Input snapshots for replay |
| `DecisionObservation` | Decision evidence in lineage |

## Trace Identity

Each `CognitiveTrace` is identified by:

| Field | Type | Description |
|---|---|---|
| `trace_id` | `str` | Unique trace identifier (UUID) |
| `request_id` | `str` | The request this trace explains |
| `correlation_id` | `str` | Correlation identifier spanning the request |
| `tenant_id` | `str` | Tenant scope |
| `user_id` | `str` | User scope (governed) |
| `session_id` | `str` | Session scope |
| `conversation_id` | `str` | Conversation scope |
| `schema_version` | `str` | Schema version for this trace |
| `cognitive_policy_version` | `str` | Cognitive policy version active at trace time |
| `started_at` | `datetime` | When cognition began |
| `completed_at` | `datetime` | When cognition completed |
| `event_count` | `int` | Number of events in this trace |
| `event_refs` | `list[str]` | References to constituent events |

## Trace Completeness

Every successful cognitive request trace must contain:

| Stage | Required? | Condition |
|---|---|---|
| `cognition.started` | Always | |
| `intelligence.completed` | Always | |
| `recall.completed` or explicit skip reason | Always | |
| `context.planned` | Always | |
| `cortex.behavior_selected` or `cortex.abstained` | Always | |
| `runtime.execution_completed` or `runtime.execution_failed` | Always | |
| `cognition.completed` | Always | |
| `reasoning.*` | Conditional | If reasoning was engaged |
| `meta.*` | Conditional | If meta-cognition triggered |
| `learning.*` | Conditional | If learning signals generated |
| `reflection.*` | Conditional | If reflection candidates created |

Conditional stages must either have an event or an explicit `NOT_APPLICABLE` / `SKIPPED` reason code. No silent holes.
