# Trace Completeness Specification

## Purpose

Define the minimum completeness requirements for cognitive traces. No silent holes.

## Completeness Requirements

### Required Events

Every successful cognitive request trace must contain:

| Event | Required | Condition |
|---|---|---|
| `cognition.started` | Always | |
| `intelligence.completed` | Always | |
| `recall.completed` or explicit skip reason | Always | |
| `context.planned` | Always | |
| `cortex.behavior_selected` or `cortex.abstained` | Always | |
| `runtime.execution_completed` or `runtime.execution_failed` | Always | |
| `cognition.completed` | Always | |

### Conditional Events

The following must either have an event or an explicit `NOT_APPLICABLE` / `SKIPPED` reason code:

| Event Group | Condition |
|---|---|
| `reasoning.*` | If reasoning was engaged |
| `belief.*` | If belief assessment was triggered |
| `goal.*` | If goal resolution was triggered |
| `salience.*` | If salience assessment was triggered |
| `meta.*` | If meta-cognition triggered |
| `adaptive.*` | If adaptive recommendations were generated |
| `learning.*` | If learning signals were generated |
| `reflection.*` | If reflection candidates were created |

### No Silent Holes

If a cognitive stage was applicable but produced no event, there must be an explicit reason code explaining why.

Valid reason codes for missing events:

| Code | Meaning |
|---|---|
| `STAGE_NOT_APPLICABLE` | Stage not applicable to this request |
| `STAGE_SKIPPED_POLICY` | Stage skipped due to policy |
| `STAGE_SKIPPED_ERROR` | Stage skipped due to upstream error |
| `STAGE_SKIPPED_DEGRADATION` | Stage skipped due to degradation |
| `STAGE_SKIPPED_BUDGET` | Stage skipped due to budget exhaustion |
| `STAGE_SKIPPED_FAST_PATH` | Stage skipped via fast-path optimization |

## Completeness Levels

### MINIMAL

The minimum trace needed to understand what happened.

Required:
- `cognition.started`
- `cortex.behavior_selected` or `cortex.abstained`
- `runtime.execution_completed` or `runtime.execution_failed`
- `cognition.completed`

### STANDARD

The default trace for normal operations.

Required:
- All required events
- All conditional events that were applicable
- All reason codes for decisions

### DIAGNOSTIC

Extended trace for debugging.

Required:
- All STANDARD requirements
- All intermediate event refs
- All input/output refs
- All candidate/rejection records

### AUDIT

Full trace for compliance and forensic analysis.

Required:
- All DIAGNOSTIC requirements
- All policy version references
- All verification records
- All learning/reflection lineage
- All decision lineage

## Completeness Validation

### Schema-Level Validation

Every trace must validate against the completeness schema:

```python
def validate_trace_completeness(trace: CognitiveTrace) -> CompletenessReport:
    """Validate that a trace meets completeness requirements."""
    report = CompletenessReport()

    # Required events
    for event_type in REQUIRED_EVENTS:
        if not trace.has_event(event_type):
            report.add_missing(event_type, severity="ERROR")

    # Conditional events
    for event_group in CONDITIONAL_GROUPS:
        if trace.was_stage_applicable(event_group):
            if not trace.has_event(event_group):
                if not trace.has_skip_reason(event_group):
                    report.add_missing(event_group, severity="WARNING")

    return report
```

### Completeness Report Structure

```
CompletenessReport
├── trace_id                 str    Trace being validated
├── is_complete              bool   Does trace meet requirements?
├── missing_required         list   Missing required events
├── missing_conditional      list   Missing conditional events
├── missing_skip_reasons     list   Applicable stages without events or reasons
├── completeness_score       float  [0, 1] completeness ratio
├── level                    str    MINIMAL | STANDARD | DIAGNOSTIC | AUDIT
└── validated_at             datetime
```

## Completeness Score

```
completeness_score = (events_present + skip_reasons_present) / (required + applicable_conditional)
```

| Score | Status |
|---|---|
| 1.0 | Complete |
| 0.9 - 0.99 | Acceptable (with documented exceptions) |
| 0.7 - 0.89 | Degraded (requires investigation) |
| < 0.7 | Incomplete (requires immediate attention) |

## Trace Integrity

### Causal Chain Integrity

Every event (except `cognition.started`) must have a `causation_id` linking to a preceding event.

### Temporal Integrity

Event timestamps must be monotonically non-decreasing within a causal chain.

### Reference Integrity

All `*_ref` fields must reference existing artifacts. Dangling references must be flagged.

### Tenant Isolation Integrity

All events in a trace must share the same `tenant_id`. Cross-tenant contamination is a critical error.

## Relationship to Existing Observability

This specification extends the existing `RuntimeEvent` completeness with cognitive-stage awareness.

| Existing | Cognitive Extension |
|---|---|
| `RuntimeEvent.status` | Cognitive status values (SUCCESS, PARTIAL, DEGRADED, FAILED, SKIPPED, NOT_APPLICABLE) |
| `RuntimeEvent.metadata` | Cognitive completeness metadata |
| `ObservabilityEmitter` | Cognitive completeness validation at emission |
| `ExecutionTrajectory` | Cognitive trace completeness validation |

## Completeness Monitoring

### Metrics

| Metric | Description |
|---|---|
| `cognitive_trace_complete_total` | Traces meeting completeness requirements |
| `cognitive_trace_incomplete_total` | Traces missing required events |
| `cognitive_trace_missing_skip_reason_total` | Applicable stages without events or reasons |
| `cognitive_trace_completeness_score_avg` | Average completeness score |

### Alerts

| Alert | Condition |
|---|---|
| `CognitiveTraceIncomplete` | Required event missing |
| `CognitiveTraceMissingSkipReason` | Applicable stage without event or reason |
| `CognitiveTraceLowCompleteness` | Completeness score below threshold |
