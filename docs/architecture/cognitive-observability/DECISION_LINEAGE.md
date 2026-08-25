# Decision Lineage Specification

## Purpose

For every final behavior decision, we must be able to answer:

- What did Karen choose?
- What alternatives existed?
- What was rejected?
- Why?
- What memory mattered?
- What beliefs mattered?
- What goal mattered?
- Did salience change priority?
- Did policy block anything?
- Was verification required?
- Which cognitive policy version was used?

## DecisionLineage Structure

```
DecisionLineage
├── decision_id              str    Unique decision identifier
├── trace_id                 str    Parent cognitive trace
├── request_id               str    Request this decision serves
├── correlation_id           str    Request correlation
├── selected_behavior        str    The behavior that was selected
├── selection_confidence     float  Confidence in selection [0, 1]
├── candidate_ids            list[str]  All candidate behavior IDs
├── rejected_candidate_ids   list[str]  Rejected candidate IDs
├── rejection_reasons        dict[str, str]  candidate_id → reason_code
├── reason_codes             list[str]  Top-level reason codes
├── memory_refs              list[str]  Memory IDs that influenced this decision
├── belief_refs              list[str]  Belief IDs that influenced this decision
├── goal_refs                list[str]  Goal IDs that influenced this decision
├── salience_ref             str    Salience assessment reference
├── context_plan_ref         str    Context plan reference
├── reasoning_ref            str    Reasoning trace reference
├── meta_ref                 str    Meta-cognition assessment reference
├── adaptive_ref             str    Adaptive recommendation reference
├── policy_ref               str    Policy decision reference
├── policy_version           str    Cognitive policy version
├── verification_required    bool   Was verification required?
├── verification_depth       str    Verification depth if required
├── abstained                bool   Did CORTEX abstain?
├── abstain_reason           str    Reason for abstention
├── occurred_at              datetime  When the decision was made
└── schema_version           str    Schema version
```

## Key Principles

### No Raw Chain-of-Thought

Decision lineage contains **structured decision evidence only**. No raw reasoning text, no chain-of-thought dumps, no internal monologue.

### Reference-Based

All influencing factors are referenced by ID, not embedded:

```
memory_ref=m-182        ✓ (reference)
belief_ref=belief-43    ✓ (reference)
claim_ref=claim-43      ✓ (reference)
evidence_ref=e-91       ✓ (reference)

memory_text="..."       ✗ (embedded content)
reasoning_trace="..."   ✗ (raw reasoning)
```

### Rejection Transparency

Every rejected candidate must have a reason. No silent rejections.

```python
rejection_reasons = {
    "cand-001": "CORTEX_REJECTED_POLICY_VIOLATION",
    "cand-002": "CORTEX_REJECTED_LOW_CONFIDENCE",
    "cand-003": "CORTEX_REJECTED_SALIENCE_TOO_LOW",
}
```

### Policy Version Pinned

Every decision records the cognitive policy version active at decision time. This enables:

- Behavioral drift detection
- Policy comparison (counterfactual replay)
- Audit trail for policy changes

## Relationship to Existing Structures

| Existing Structure | DecisionLineage Role |
|---|---|
| `DecisionProvenance` | Lightweight ownership/version record; DecisionLineage expands this |
| `DecisionObservation` | OPE-focused decision record; DecisionLineage is explainability-focused |
| `BehaviorDecision` | Behavior system output; DecisionLineage contextualizes it |
| `ExecutionDecision` | CORTEX execution output; DecisionLineage explains why |

## Decision Evidence Matrix

| Evidence Type | Required? | Stored As |
|---|---|---|
| Selected behavior | Always | `selected_behavior` |
| Candidate set | Always | `candidate_ids` |
| Rejected candidates | If any rejected | `rejected_candidate_ids` + `rejection_reasons` |
| Memory influences | If memory influenced | `memory_refs` |
| Belief influences | If beliefs influenced | `belief_refs` |
| Goal influences | If goals influenced | `goal_refs` |
| Salience influence | If salience mattered | `salience_ref` |
| Context plan | Always | `context_plan_ref` |
| Reasoning trace | If reasoning engaged | `reasoning_ref` |
| Meta-cognition | If meta triggered | `meta_ref` |
| Adaptive ranking | If adaptive engaged | `adaptive_ref` |
| Policy decision | Always | `policy_ref` |
| Verification | If verification required | `verification_required`, `verification_depth` |
| Abstention | If abstained | `abstained`, `abstain_reason` |

## Abstention Lineage

When CORTEX abstains, the lineage must record:

1. **Why abstained** (`abstain_reason`)
2. **What candidates existed** (`candidate_ids`)
3. **What would have been needed** to not abstain (encoded in `reason_codes`)
4. **Fallback behavior** if any (`selected_behavior` may indicate fallback)

Abstention is a first-class decision outcome, not a failure.

## Audit Use Cases

### "Why did Karen choose X?"

```
SELECT * FROM decision_lineage
WHERE request_id = 'req-123'
  AND selected_behavior = 'VERIFY';
```

Returns: candidates, rejections, memory refs, belief refs, policy version.

### "What memories influenced this decision?"

```
SELECT memory_refs FROM decision_lineage
WHERE decision_id = 'dec-456';
```

Returns: `['m-182', 'm-201', 'm-315']`

### "Did policy block anything?"

```
SELECT rejection_reasons FROM decision_lineage
WHERE decision_id = 'dec-456';
```

Returns: `{'cand-001': 'CORTEX_REJECTED_POLICY_VIOLATION'}`

### "Was this decision made under the current policy?"

```
SELECT policy_version FROM decision_lineage
WHERE decision_id = 'dec-456';
```

Compare against current policy version to detect stale decisions.
