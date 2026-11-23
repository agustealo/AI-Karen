# KCR-04G | Undated claim-store retrieval must not replay historical versions

## Existing owner and finding

`MemoryClaim.is_valid(at)` in `src/ai_karen_engine/core/memory/contracts.py`
owns effective valid-time semantics. KCR-04F permits a bounded `SUPERSEDED`
version in an **explicitly dated** valid-time query and excludes it when
`is_valid()` receives no time. `MemoryClaimStore.get_valid_claims()`
also accepts an optional time, but it captured a single UTC snapshot and
passed that snapshot to `is_valid` **even for undated requests**.

That converted the store's implicit current-state read into an explicit
historical valid-time read. With a superseded version having a future
`valid_until` and the current snapshot inside its former effective window,
the store could return the superseded record. This is an in-process
contract inconsistency identified by source inspection, **not an observed
production leak, unauthorized recall or cross-tenant breach**.

## Repair and ownership

The existing store distinguishes `at is None` from a caller explicitly
supplying an instant. For an undated request, it excludes `SUPERSEDED`
records before calling the canonical claim-validity predicate. Explicit
`get_valid_claims(valid_at, **owner_scope)` continues delegating bounded
historical eligibility to `MemoryClaim.is_valid(valid_at)`.

The store still captures **one UTC snapshot** for all other claims,
prevalidates the full stored identity/owner set through `_verified_items`,
and preserves tenant/user scope checks. It does not duplicate the
canonical temporal interval calculation or alter `RETRACTED`, `STALE`,
`deleted_at`, version identity, authorization, RBAC, NeuroVault, or
PostgreSQL recall semantics.

## Regression and acceptance

`tests/architecture/test_memory_temporal_evolution.py` verifies that
a frozen undated snapshot excludes a superseded record even before its
exclusive effective-time end, retains an active record, and reads the
clock exactly once. An explicitly supplied timestamp inside the interval
still returns both applicable records; the exclusive end excludes the old
version without another clock read.

Required proof on the **exact candidate head**:

1. `PYTHONPATH=src pytest -q tests/architecture/test_memory_temporal_evolution.py tests/architecture/test_memory_claim_store_scope.py tests/architecture/test_memory_consumer_domain_migration.py`
2. `ruff check src/ai_karen_engine/core/memory/claims/__init__.py tests/architecture/test_memory_temporal_evolution.py`
3. `python -m compileall -q src/ai_karen_engine/core/memory`
4. Main Quality, Cognitive Proof, Chat System Burn, Context Authority,
   Live PostgreSQL Profile Memory and Production First-Boot exact-head gates.
5. Independent code/security review, Vercel exact-head preview, and
   mainline reconciliation before merge.

**Merge/release state:** development candidate, not approved. Creating
a branch or PR is not test execution, reviewer approval, deployment success
or production acceptance. The valid-time contract is not a bitemporal
`recorded_as_of` reconstruction; retention and deletion governance remain
separate authorities.
