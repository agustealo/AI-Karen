# KCR-04F | Historical effective-time validity for superseded claims

## Owner and observed defect

`MemoryClaim.is_valid()` in `src/ai_karen_engine/core/memory/contracts.py`
owns the canonical effective-validity predicate used by the in-process claim
store. Before this correction, an evolution from an earlier value to a later
value gave the earlier version `SUPERSEDED` status and a half-open
`valid_until`, but `is_valid(at)` rejected the earlier version at **every**
time, even within its former validity window.

This is a reproducible in-process semantic defect, **not evidence of an
unauthorized production recall or a data leak**. It was recorded separately
from KCR-04E because it is not caused by owner-scope hardening.

## Effective valid-time contract

- An **explicitly dated** query may include a `SUPERSEDED` version only if
  its `valid_until` is present and the requested instant lies within the
  half-open interval. The effective start follows the existing canonical
  temporal fallback: `valid_from`, then `event_time`, then `asserted_at`.
- At the start instant, the prior version is included. At the exclusive end,
  it is excluded; the successor may become valid at that instant.
- An implicit `claim.is_valid()` check never revives a superseded version.
  An unbounded superseded version is also excluded.
- `RETRACTED` and `STALE` versions remain excluded, and any claim with a
  `deleted_at` marker is withheld regardless of the requested time. This
  prevents a past valid-time lookup from bypassing deletion governance.
- Naive legacy times are interpreted as UTC, and offset-aware times are
  normalized using the pre-existing `_utc` helper.

This is **valid-time** behavior only, not a `recorded_as_of` reconstruction.
The method cannot reconstruct what KAREN knew at an earlier transaction time
from a present-day in-memory object. A future bitemporal audit query must use
the governed durable event/claim history and enforce its own RBAC, retention
and deletion controls. Do not infer such support from this PR.

## Scope and proof

The change stays with the existing `MemoryClaim` contract and focused
`tests/architecture/test_memory_temporal_evolution.py` coverage. No new
store, graph coordinator, route, provider, auth mechanism, database schema or
fallback path is introduced.

The regression checks explicit historical instants before, at and after the
exclusive boundary; current/undated queries; unbounded superseded versions;
retracted, stale and deleted content; and UTC/legacy-offset normalization.
Existing temporal graph, belief and recall tests should remain green.

## Merge and rollout

This slice is independent of KCR-04E's tenant/user claim-store ownership.
When both changes are included in a release candidate, rerun exact-head
memory isolation, temporal evolution, graph, auth and Main Quality tests.
Historical valid-time correctness **does not certify** persisted record-time
lineage or authenticated cross-tenant recall.
