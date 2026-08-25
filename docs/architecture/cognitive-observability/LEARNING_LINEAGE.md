# Learning Lineage Specification

## Purpose

A learned preference must be explainable back to the experiences that produced it. No "preference magically exists."

Learning needs the reverse path of memory lineage:

```
BehaviorDecision
       ↓
ExecutionOutcome
       ↓
ExperienceObservation
       ↓
LearningSignal
       ↓
ReflectionCandidate
       ↓
PromotionDecision
       ↓
Memory/Adaptive candidate
```

## LearningLineage Structure

```
LearningLineage
├── lineage_id               str    Unique lineage identifier
├── signal_id                str    The learning signal being traced
├── trace_id                 str    Parent cognitive trace
├── request_id               str    Request that generated the signal
├── correlation_id           str    Request correlation
├── decision_ref             str    Reference to the behavior decision
├── outcome_ref              str    Reference to execution outcome
├── observation_ref          str    Reference to experience observation
├── signal_type              str    Type of learning signal
├── signal_strength          float  Strength of the signal [0, 1]
├── reflection_candidate_ref str    Reference to reflection candidate
├── promotion_ref            str    Reference to promotion decision
├── promoted                 bool   Was the candidate promoted?
├── promotion_reason         str    Reason for promotion/rejection
├── resulting_memory_ref     str    Reference to resulting memory (if promoted)
├── resulting_adaptive_ref   str    Reference to resulting adaptive update (if promoted)
├── occurred_at              datetime  When the learning signal was created
└── schema_version           str    Schema version
```

## Lineage Stages

### Stage 1: Behavior Decision

The decision that led to the learning opportunity. Reference: `decision_ref`.

This links to the `DecisionLineage` for the decision being learned from.

### Stage 2: Execution Outcome

The outcome of executing the behavior. Reference: `outcome_ref`.

Captures:
- Whether execution succeeded or failed
- The actual result produced
- Any error conditions

### Stage 3: Experience Observation

The observation derived from the outcome. Reference: `observation_ref`.

Captures:
- What was observed about the experience
- User feedback if available
- Success/failure indicators

### Stage 4: Learning Signal

The signal generated from the observation. Captured via `signal_id`, `signal_type`, `signal_strength`.

This is the atomic unit of learning: "this experience suggests X."

### Stage 5: Reflection Candidate

The signal was elevated to a reflection candidate. Reference: `reflection_candidate_ref`.

Captures:
- That the signal was considered for learning
- The candidate's initial assessment

### Stage 6: Promotion Decision

The decision on whether to promote the candidate. Reference: `promotion_ref`.

Captures:
- Whether the candidate was promoted or rejected
- The reason for the decision
- The evidence threshold applied

### Stage 7: Result

The resulting memory or adaptive update (if promoted). References: `resulting_memory_ref`, `resulting_adaptive_ref`.

## Signal Types

| Type | Description |
|---|---|
| `PREFERENCE_LEARNED` | User preference inferred from behavior |
| `STRATEGY_EFFECTIVE` | Strategy proved effective |
| `STRATEGY_INEFFECTIVE` | Strategy proved ineffective |
| `CORRECTION_RECEIVED` | User corrected the system |
| `SUCCESS_PATTERN` | Pattern of success observed |
| `FAILURE_PATTERN` | Pattern of failure observed |
| `CONTEXT_INSIGHT` | Insight about context handling |
| `PROVIDER_PERFORMANCE` | Provider performance observation |

## Promotion Outcomes

| Outcome | Description |
|---|---|
| `PROMOTED_TO_MEMORY` | Promoted to persistent memory |
| `PROMOTED_TO_ADAPTIVE` | Promoted to adaptive recommendation update |
| `REJECTED_BELOW_THRESHOLD` | Rejected: signal strength below threshold |
| `REJECTED_CONFLICTING` | Rejected: conflicts with existing knowledge |
| `REJECTED_INSUFFICIENT_EVIDENCE` | Rejected: insufficient evidence |
| `REJECTED_POLICY` | Rejected: policy violation |
| `DEFERRED` | Deferred for future evaluation |

## Traceability Requirements

### Forward Trace (Experience → Learned Behavior)

Given an experience, we must be able to trace:

1. What learning signal it generated
2. Whether that signal became a reflection candidate
3. Whether it was promoted
4. What memory or adaptive update resulted
5. How that affects future behavior

### Reverse Trace (Learned Behavior → Experience)

Given a learned preference or behavior, we must be able to trace:

1. What experiences produced it
2. What learning signals were generated
3. What reflection candidates were created
4. What promotion decisions were made
5. The evidence threshold that was applied

## Relationship to Existing Structures

| Existing Structure | LearningLineage Role |
|---|---|
| `ActionOutcomeObservation` | Outcome observation record |
| `FeatureSnapshot` | Decision-time feature snapshot |
| `DecisionObservation` | OPE decision record |
| `LearningDatasetManifest` | Dataset-level lineage |
| `ReflectionEngine` | Reflection processing |
| `PromotionGate` | Promotion decision logic |
| `AdaptiveRecommendation` | Adaptive recommendation output |

## Evidence Requirements

A learned preference is only valid if:

1. **Source decision exists** (`decision_ref` is non-null)
2. **Execution outcome exists** (`outcome_ref` is non-null)
3. **Observation exists** (`observation_ref` is non-null)
4. **Signal was generated** (`signal_id` is non-null)
5. **Promotion decision exists** (`promotion_ref` is non-null)
6. **Evidence threshold was met** (encoded in `promotion_reason`)

If any of these are missing, the learned preference has no valid lineage and must be flagged.

## Counterfactual Learning

Learning lineage enables counterfactual analysis:

- "Would we have learned this if the outcome had been different?"
- "What experiences would need to change to unlearn this?"
- "Is this preference based on sufficient evidence?"

This plugs into the adaptive/OPE system without modifying it.
