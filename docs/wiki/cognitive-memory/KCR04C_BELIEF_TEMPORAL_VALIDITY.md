# KCR-04C | Native belief temporal validity and UTC normalization

**Baseline:** `6ec4a950795bac695ad382eb2703fff98e4a79ea`. **Status:** proposed, exact-head acceptance pending.  
**Independent of PR #1019:** no overlapping files; the memory claim owner and the belief owner remain distinct.

## Correct owner and repair
`ClaimTemporalValidity.is_expired()` now uses the exclusive `valid_until` boundary. `TemporalReasoner.is_valid()` shares that expiry contract rather than repeating another end comparison, and normalizes legacy naive UTC and timezone-aware times with the existing belief `_utc` helper. `is_stale`, `temporal_distance`, and `validate_temporal_consistency` consistently use UTC. The consistency method drops a no-op pass-only comparison loop, and evidence expires at the boundary.

This is temporal eligibility logic, **not** an RBAC or NeuroVault authorization substitute. No schema, prompt, model, provider, app route, or graph backend changes.

## Proof
- `tests/core/reasoning/belief/test_belief.py` checks microsecond/exact-end expiry, inclusive start, zero-length interval, equivalent timezone offsets and naive UTC timestamps, mixed-clock staleness/distance, evidence expiry, and open-ended claims, alongside existing belief regression tests.
- Main Quality now calls that full module explicitly, so a green outcome must represent actual execution.
- Run `PYTHONPATH=src pytest tests/core/reasoning/belief/test_belief.py -q`, `ruff check src/ai_karen_engine/core/reasoning/belief tests/core/reasoning/belief`, and repository quality gate.

**Remaining:** This does not provide live Postgres as-of retrieval, direct graph-source current-consent enforcement, or deployment certification. PR #1019 remains blocked by Vercel preview build quota, not by this independent code slice.
