# Canonical GoalState retirement: time-boxed compatibility exception

**Owner:** `core/personalization/goals`  
**Canonical lifecycle:** `src/ai_karen_engine/core/memory/contracts.py::GoalState`  
**Legacy:** `src/ai_karen_engine/core/personalization/contracts.py::UserGoalStatus`  
**New expiry:** 2026-10-22 (one-week deferral from 2026-10-15).  
**Scope:** Compatibility debt predating MI-07; not a completed migration.

## Why not delete it immediately?

The existing `UserGoal` and `UserModel` stored-value contracts still reference
`UserGoalStatus`. The platform's derived personalization repository returns
legacy statuses from `memory_user_goal`; the goal-domain converter maps
those statuses to the canonical `GoalState`. Deleting it on expiry would
break live goal readers, and mis-mapping a goal to `completed` or
`abandoned` would be an unacceptable loss of truth.

## Audited live owners and consumers

- `src/ai_karen_engine/core/personalization/contracts.py`: `UserGoalStatus`,
  `UserGoal.status`, `GoalState.status` (legacy dataclass, not canonical
  enum) and relationship commitment contracts.
- `src/ai_karen_engine/core/personalization/goals/contracts.py`:
  `goal_from_user_goal` and `_map_user_goal_status`.
- `src/ai_karen_engine/platform/personalization/repository.py`:
  `PostgresPersonalizationRepository.list_goals` and `_goal_status`.
- `tests/core/personalization/goals/test_lifecycle.py`:
  legacy-to-canonical conversion contract.
- `tests/architecture/cognitive_contracts/test_convergence_invariants.py`:
  expiry and ownership guard.

This is a minimum **known** list, not proof of an exhaustive import search.
Use repository-wide symbol searches before modifying or removing the types.

## Required migration

1. Enumerate every symbol import, runtime serialization/deserialization path,
   stored consumer, API schema and frontend reader.
2. Make the core memory `GoalState` the sole lifecycle-state authority.
   Preserve all currently stored values. Explicitly map legacy
   `unknown` to `proposed` only at a versioned migration boundary.
3. Keep `active`, `paused`, `blocked`, `at_risk`, `satisfied`,
   `completed`, `abandoned`, `superseded` and `expired` distinct.
4. Prove goal-store roundtrips against migrated data, tenant isolation,
   persistence reads, API compatibility and transition invariants.
5. Delete the legacy enum, imports and shim registry entry only after
   a no-reference audit. No dead aliases or parallel lifecycle enums.
6. Pass `pytest tests/architecture/cognitive_contracts -q`,
   `pytest tests/core/personalization/goals -q`, backend quality,
   compile/import checks and main-quality gates.

## Verification gate and risk

The compatibility registry's `expired_shims()` enforcement **remains active**.
This single bounded deferral does not declare the legacy contract fixed.
Failure after 2026-10-22 is expected unless the real migration is completed.
The MI-07 memory-governance changes must remain orthogonal to this work.

GitHub Issues is disabled for this repository, so this document is the durable
owner/action ledger. Do not silently extend the deadline again.
