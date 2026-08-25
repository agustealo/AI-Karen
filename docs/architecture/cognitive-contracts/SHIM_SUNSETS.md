# Cognitive Compatibility Shim Sunsets

COG-CONVERGE-1 keeps only compatibility seams that have an explicit canonical
replacement and removal condition. New code must import the canonical owner.

| Shim | Canonical replacement | Owner | Removal condition | Target sunset |
|---|---|---|---|---|
| `cortex.behavior.VerificationDepth` | `core.contracts.cognitive.ReasoningDepth` | reasoning/core contracts | zero imports of `VerificationDepth` outside compatibility tests | 2026-10-01 |
| `reasoning.meta.VerificationNeedAssessment` | `core.contracts.cognitive.VerificationRequirement` | shared cognitive contracts | all callers construct/consume `VerificationRequirement` | 2026-10-01 |
| `personalization.goals.EvidenceSourceType` | `reasoning.belief.EvidenceType` | belief/evidence | zero legacy `EvidenceSourceType` imports | 2026-10-01 |
| `personalization.DriftState` | `personalization.PreferenceDriftState` for preference drift; `adaptive.dr​ift` for adaptive drift | personalization/adaptive | callers use domain-specific drift type | 2026-10-15 |
| `personalization.UserGoalStatus` | `personalization.goals.GoalState` | personalization/goals | `UserGoal` compatibility projection retired | 2026-10-15 |
| `cortex.contracts.ReasoningRequest` | `core.reasoning.contracts.ReasoningRequest` | reasoning | zero production callers of legacy CORTEX request | 2026-10-15 |
| `cortex.contracts.ReasoningResult` | `core.reasoning.contracts.ReasoningResult` | reasoning | zero production callers of legacy CORTEX result | 2026-10-15 |
| `reasoning.contracts.ReasoningEvidence.timestamp` | `event_time` / `observed_at` / `created_at` | reasoning | all callers use explicit temporal semantics | 2026-10-15 |
| `personalization.goals.GoalStore` re-export from contracts | `personalization.goals.lifecycle.GoalStore` | goals lifecycle | zero imports from contracts module | 2026-10-15 |

## Reference audit

```bash
rg -n "VerificationDepth|VerificationNeedAssessment|EvidenceSourceType|UserGoalStatus|DriftState" src tests
rg -n "from .*cortex\.contracts import .*Reasoning(Request|Result)" src tests
rg -n "ReasoningEvidence\(.*timestamp=|\.timestamp" src tests
rg -n "goals\.contracts import .*GoalStore" src tests
```

A shim may be removed only after its reference count is zero or every remaining
reference is a documented compatibility test. Removing a shim also requires
compile, unit, architecture, cognitive benchmark, and API/runtime contract proof.

## Legacy platform seams discovered during convergence

The following are **not canonical cognition** and remain explicit migration debt:

- `core/memory/memory_runtime_manager.py`: legacy runtime/write authority with
  direct SQLAlchemy usage. Replacement direction: runtime memory coordinator +
  platform memory adapters.
- `core/memory/unified_memory_service.py`: legacy service shell over memory
  adapters. Replacement direction: Runtime consumes Core memory/recall ports,
  Platform supplies adapters.
- `core/adaptive/runtime.py`: advisory runtime still consumes legacy Core
  observability context. Replacement direction: inject request/correlation
  context from Runtime or an observability port.

New Core contracts and cognitive modules MUST NOT import these files. They are
migration shims, not approved dependency targets. Their removal is tracked as a
follow-up structural extraction, because moving them in the same contract
canonicalization change would create a high-risk runtime/persistence migration.
