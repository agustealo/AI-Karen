# Temporal Semantics

A cognition system that only has `created_at` will eventually hallucinate temporal continuity even if the memory database is flawless.

## Inventory

| Temporal field | Domains using it | Meaning |
| -------------- | ---------------- | ------- |
| `created_at` | memory, personalization, adaptive, cortex | When the record was first created |
| `updated_at` | memory, personalization, adaptive | When the record was last modified |
| `observed_at` | reasoning/belief, personalization, adaptive/learning | When the underlying event/evidence was observed |
| `asserted_at` | memory/contracts.py (MemoryClaim) | When the claim was asserted/entered |
| `valid_from` | memory/contracts.py, personalization/contracts.py | When a claim/property becomes valid |
| `valid_until` | memory/contracts.py, personalization/contracts.py, reasoning/belief | When a claim/property expires |
| `last_confirmed_at` | personalization/contracts.py, memory/contracts.py | When confidence was last reinforced |
| `last_verified_at` | reasoning/belief/contracts.py | When verification was last performed |
| `superseded_at` | *missing in most domains* | When a record was replaced by a newer one |
| `deleted_at` | *missing in most domains* | When a record was soft-deleted |
| `timestamp` | reasoning, adaptive, memory/types (float or str) | Event timestamp; inconsistent type (float vs datetime vs str) |
| `started_at` | personalization/goals, personalization | When a goal/intention/commitment began |
| `completed_at` | personalization/goals, memory | When a goal/memory was completed |
| `expires_at` | memory, personalization, adaptive | When a record becomes stale |
| `last_seen` / `first_seen` | personalization | When a behavior pattern was observed |
| `triggered_at` / `archived_at` | personalization/goals | Prospective memory lifecycle |
| `fulfilled_at` / `failed_at` / `committed_at` | personalization/goals | Commitment lifecycle |
| `revised_at` / `detected_at` | personalization, reasoning/belief | Revision/contradiction detection time |
| `recorded_at` | reasoning/contracts.py | When evidence was recorded in reasoning system |
| `event_time` | *missing across all domains* | Original event time (distinct from observed_at) |

## Domain requirements

| Domain | Required temporal fields | Missing fields |
| ------ | ----------------------- | -------------- |
| Memory | created_at, updated_at, expires_at, valid_from, valid_until, last_confirmed_at | superseded_at, deleted_at, event_time |
| Belief | asserted_at, observed_at, valid_from, valid_until, last_verified_at | superseded_at, deleted_at, event_time |
| Goals | started_at, completed_at, expires_at, target_date | superseded_at, event_time |
| Adaptive | created_at, expires_at | observed_at, valid_from, valid_until |
| Context | created_at | updated_at, expires_at |
| Salience | last_activated_at | created_at, valid_from, valid_until |
| CORTEX | decided_at | superseded_at |

## Type inconsistencies

| Field | Types found | Issue |
| ----- | ----------- | ----- |
| `timestamp` | `float`, `str`, `datetime` | Should be standardized to `datetime` |
| `created_at` | `datetime`, `str` | Should be standardized to `datetime` |
| `observed_at` | `datetime`, `str` | Should be standardized to `datetime` |
| `recorded_at` | `Optional[str]` | Should be `Optional[datetime]` |
| `detected_at` | `datetime`, `str` | Should be standardized to `datetime` |

## Recommendation

1. Standardize all temporal fields to `datetime` with UTC timezone.
2. Add `superseded_at` and `deleted_at` to all major cognitive contracts.
3. Add `event_time` to `MemoryClaim` and `BeliefClaim` to distinguish occurrence from observation.
4. Deprecate `timestamp` (float/str) in favor of `created_at` (datetime).
