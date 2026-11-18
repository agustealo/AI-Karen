# KCR-04D | One-clock in-process claim snapshot

**Dependency:** PR #1019, canonical half-open `MemoryClaim.is_valid()` boundary.
**Ownership:** `MemoryClaimStore.get_valid_claims()` in `src/ai_karen_engine/core/memory/claims/__init__.py`.
**Scope:** Single-instant in-process recall only; no persistence, storage, provider, routing, or API change.

## Finding

The existing `get_valid_claims(at=None)` passed `None` to each `MemoryClaim.is_valid()` call. The contract chooses `datetime.now(timezone.utc)` for each call separately. Around a `valid_until` boundary, one logical snapshot could therefore evaluate two claims at different instants.

## Repair

Capture `snapshot_at` exactly once at the store boundary with `datetime.now(timezone.utc)` when `at is None`, or preserve the caller-provided instant when explicit. Pass that same object to each claim's canonical validity contract. Do not duplicate half-open range logic or normalize timestamps in another owner.

## Targeted proof

- `tests/architecture/test_memory_temporal_evolution.py::test_get_valid_claims_without_at_uses_one_utc_snapshot`: records actual validity-call arguments, requires the same timezone-aware UTC instant for both claims; fails on the old implicit-`None` behavior.
- `tests/architecture/test_memory_temporal_evolution.py::test_get_valid_claims_implicit_snapshot_respects_exact_end`: freezes the store's clock at a common end/start boundary, requires one clock read and the new claim only.
- Existing explicit as-of, microsecond, UTC offsets, retraction and temporal evolution tests stay intact.

## Explicitly not proved

The in-process `MemoryClaimStore` is **not** the tenant authorization or persistence authority. This slice does not establish PostgreSQL as-of parity, RLS enforcement, graph consent, persisted claim histories, multitenant cache safety, or live production behavior. Separate real-PostgreSQL tests must assert the canonical recall predicate at the exact boundary under scoped tenant/user credentials, and an independent owner audit must assess whether the in-process store ever crosses tenant lifetimes.

## Merge contract

1. Merge PR #1019 only after its own required deployment and review proof.
2. Rebase this dependent slice on the new `main` and re-run exact-head architecture, Main Quality, Cognitive Proof and First-Boot checks.
3. Obtain independent review and exact-head Vercel deployment acceptance. Neither prior green checks nor a build-rate-limit failure can be substituted for deployment.
4. Do not merge on the basis of this document or unexecuted tests.

## Verification commands

```sh
PYTHONPATH=src pytest tests/architecture/test_memory_temporal_evolution.py -q
PYTHONPATH=src pytest tests/benchmarks/memory/test_temporal_research_contract.py -q
ruff check src/ai_karen_engine/core/memory/claims/__init__.py tests/architecture/test_memory_temporal_evolution.py
python -m compileall -q src/ai_karen_engine/core/memory
```
