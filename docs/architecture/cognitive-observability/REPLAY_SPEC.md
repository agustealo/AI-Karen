# Replay Specification

## Purpose

Define deterministic cognitive replay semantics for:

- Reproducing old cognitive decisions
- Comparing new policies against old ones
- Detecting behavioral drift
- Validating cognitive changes

## CognitiveReplayManifest Structure

```
CognitiveReplayManifest
├── manifest_id              str    Unique manifest identifier
├── trace_id                 str    Reference to original cognitive trace
├── request_fixture_ref      str    Reference to frozen request fixture
├── cognitive_policy_version str    Policy version for this replay
├── schema_versions          dict   Schema versions for each component
├── input_snapshot_refs      dict   Model-independent input snapshots
│   ├── perception_ref       str    Perception/intent snapshot
│   ├── recall_ref           str    Recall results snapshot
│   ├── belief_ref           str    Belief state snapshot
│   ├── goal_ref             str    Goal state snapshot
│   ├── salience_ref         str    Salience state snapshot
│   └── context_ref          str    Context plan snapshot
├── memory_snapshot_refs     list[str]  Memory state at decision time
├── goal_snapshot_refs       list[str]  Goal state at decision time
├── belief_snapshot_refs     list[str]  Belief state at decision time
├── candidate_set            list[str]  Behavior candidates available
├── random_seed              int    Random seed where applicable
├── expected_decision        str    Expected behavior selection
├── expected_confidence      float  Expected confidence
├── occurred_at              datetime  When the manifest was created
└── schema_version           str    Schema version
```

## Replay Types

### Deterministic Replay

Given the same inputs and policy, the cognitive system should produce the same decision.

Requirements:
- Frozen request fixture
- Frozen cognitive policy version
- Frozen memory/goal/belief snapshots
- Deterministic reasoning (no randomness or fixed seed)

### Policy Comparison Replay

Given the same inputs but different policies, compare decisions.

```
Original policy:  behavior-v1
Candidate policy:  behavior-v2

Same frozen cognitive inputs.
Compare: selected behavior, confidence, verification requirement,
         candidate ranking, policy rejection.
```

### Drift Detection Replay

Periodically replay historical requests to detect behavioral drift.

Requirements:
- Historical request fixtures
- Current policy version
- Comparison against original decisions
- Drift threshold configuration

## Input Snapshots

### Perception Snapshot

```
PerceptionSnapshot
├── intent                  str    Detected intent
├── intent_confidence       float  Confidence in intent
├── entities                list   Extracted entities
├── user_context            dict   User context (governed)
└── schema_version          str
```

### Recall Snapshot

```
RecallSnapshot
├── recalled_memory_refs    list[str]  Memories recalled
├── recall_scores           dict   memory_id → score
├── recall_degraded         bool   Was recall degraded?
└── schema_version          str
```

### Belief Snapshot

```
BeliefSnapshot
├── active_belief_refs      list[str]  Active beliefs
├── conflict_refs           list[str]  Detected conflicts
├── assessment_status       str    Assessment status
└── schema_version          str
```

### Goal Snapshot

```
GoalSnapshot
├── active_goal_refs        list[str]  Active goals
├── intention_refs          list[str]  Triggered intentions
├── goal_conflicts          list[str]  Goal conflicts
└── schema_version          str
```

### Salience Snapshot

```
SalienceSnapshot
├── salience_scores         dict   dimension → score
├── overall_salience        float  Overall salience
├── priority_adjustments    list   Priority adjustments made
└── schema_version          str
```

### Context Snapshot

```
ContextSnapshot
├── included_item_refs      list[str]  Items included in context
├── omitted_item_refs       list[str]  Items omitted from context
├── token_budget_used       int    Tokens used
├── token_budget_total      int    Total token budget
└── schema_version          str
```

## Replay Execution

### Pre-conditions

1. Request fixture is available and valid
2. Cognitive policy version is available
3. Input snapshots are available
4. Memory/goal/belief snapshots are available
5. Candidate set is available

### Execution

1. Load request fixture
2. Load cognitive policy version
3. Inject frozen input snapshots
4. Run cognitive processing
5. Capture actual decision
6. Compare against expected decision

### Post-conditions

1. Replay result recorded
2. Drift detected (if any) flagged
3. Comparison metrics captured

## Replay Result Structure

```
ReplayResult
├── result_id               str    Unique result identifier
├── manifest_id             str    Reference to replay manifest
├── actual_decision         str    Actual behavior selected
├── actual_confidence       float  Actual confidence
├── decision_match          bool   Did decision match expected?
├── confidence_delta        float  Confidence difference
├── ranking_delta           float  Candidate ranking difference
├── verification_changed    bool   Did verification requirement change?
├── policy_rejection_changed bool  Did policy rejection change?
├── drift_detected          bool   Was drift detected?
├── drift_magnitude         float  Magnitude of drift
├── executed_at             datetime  When replay was executed
└── schema_version          str
```

## Counterfactual Replay

### Purpose

Compare original policy behavior against candidate policy behavior on the same frozen inputs.

### Format

```
CounterfactualReplay
├── replay_id               str    Unique counterfactual identifier
├── original_manifest_ref   str    Original replay manifest
├── candidate_policy_version str   Candidate policy version
├── original_decision       str    Decision under original policy
├── candidate_decision      str    Decision under candidate policy
├── decision_changed        bool   Did the decision change?
├── original_confidence     float  Confidence under original policy
├── candidate_confidence    float  Confidence under candidate policy
├── original_ranking        list   Candidate ranking under original policy
├── candidate_ranking       list   Candidate ranking under candidate policy
├── original_rejections     dict   Rejections under original policy
├── candidate_rejections    dict   Rejections under candidate policy
├── comparison_metrics      dict   Quantitative comparison
└── schema_version          str
```

### Comparison Metrics

| Metric | Description |
|---|---|
| `decision_changed` | Whether the selected behavior changed |
| `confidence_delta` | Change in confidence |
| `ranking_jaccard` | Jaccard similarity of candidate rankings |
| `rejection_overlap` | Overlap in rejected candidates |
| `verification_changed` | Whether verification requirement changed |

## Integration with Adaptive/OPE

Counterfactual replay plugs into the existing adaptive/OPE system:

- `DecisionObservation` provides the original decision record
- `FeatureSnapshot` provides the frozen input features
- Counterfactual replay provides the policy comparison layer

This specification does not modify the adaptive/OPE system; it defines the replay format that consumes it.

## Determinism Requirements

For deterministic replay:

1. **No wall-clock dependence**: All timestamps are from the fixture
2. **No random variation**: Random seeds are fixed
3. **No external state**: All inputs are from snapshots
4. **No provider variation**: Model outputs are from snapshots
5. **No time decay**: Salience/decay are from snapshots

If any of these conditions cannot be met, the replay is non-deterministic and must be flagged.

## Non-Deterministic Replay

When full determinism is impossible:

1. Record which inputs were live vs. frozen
2. Report confidence intervals instead of exact matches
3. Flag non-deterministic factors in the replay result
4. Use statistical comparison instead of exact comparison
