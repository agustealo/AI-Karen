# KCR-04B | Canonical half-open memory claim validity

**Source baseline:** `6ec4a950795bac695ad382eb2703fff98e4a79ea`, 2026-11-18  
**Scope:** one in-process claim contract, two regression test files and this evidence note.  
**Status:** exact-head CI pending; not yet a live PostgreSQL migration or a historical as-of memory retrieval API.

## Correct owner
- `MemoryClaim.is_valid(at)` in `src/ai_karen_engine/core/memory/contracts.py` was treating `valid_until` as **inclusive**, using `at > valid_until`.
- `MemoryTemporalEvolutionService.TemporalInterval` already defines the correct half-open interval **[valid_from, valid_until)**.
- Canonical PostgreSQL `PostgresRecallRetriever` and `recallable_memory_event` already use `valid_to > now` for the end of a valid interval.
- `MemoryClaimStore.get_valid_claims(at)` delegates to `MemoryClaim.is_valid(at)`; the bug affects its in-process valid-claim snapshot.
- The correction changes exactly one branch to `at >= valid_until` and preserves existing UTC conversion, status guards, subject ownership and all persisted schemas.

## Caller and redundancy audit
A source scan across the 115 Python modules in `src/ai_karen_engine/core/memory/` and `src/ai_karen_engine/core/reasoning/belief/` found the direct `MemoryClaim.is_valid` consumer in `src/ai_karen_engine/core/memory/claims/__init__.py`: `MemoryClaimStore.get_valid_claims(at)`. Other checked owners use temporal interval handling or different types. This is the **audited scope**, not a claim to have enumerated every dynamic caller in the wider repository.

The separate belief system uses `ClaimTemporalValidity.is_expired` and `TemporalReasoner.is_valid` with inclusive-end comparisons in `src/ai_karen_engine/core/reasoning/belief/contracts.py` and `temporal.py`. Its time normalization and naive/aware datetime handling differ. **Do not silently change that authority in KCR-04B**. Audit callers, potential mixed-time errors and behavior under a separately owned follow-on task before modifying it.

## Actual tests
- `tests/benchmarks/memory/test_temporal_research_contract.py`: the former **strict XFAIL** now becomes a normal assertion. Any regression makes CI red.
- `tests/architecture/test_memory_temporal_evolution.py`: proves valid-from inclusivity, valid-until exclusivity at microsecond precision, equivalent UTC offsets, naive UTC input, claim store continuity at a shared end/start instant and status-based retraction.
- Existing temporal evolution, contradiction/supersession, graph, RBAC and memory recall tests remain unchanged and run in the usual quality suite.
- This change does **not** create new historical retrieval, change ledger rows, change consent policy, or run a migration.

## Acceptance
1. Exact-head Main Quality, memory temporal research test, architecture authority test, review and deployment contract must pass.
2. No unexpected behavior changes to scope, status, UTC conversion, persisted records, or production tenant authorization.
3. A later live ledger smoke test must confirm that a claim's in-process boundary and PostgreSQL end time agree on the same fixture. KCR-04A already separately demonstrated real PostgreSQL assertion recall and validity filtering.
4. No external frameworks, models, services or production dependency changes.

## Proof commands
```sh
PYTHONPATH=src pytest -q tests/benchmarks/memory/test_temporal_research_contract.py tests/architecture/test_memory_temporal_evolution.py
PYTHONPATH=src python -m compileall -q src/ai_karen_engine/core/memory
ruff check src/ai_karen_engine/core/memory/contracts.py tests/architecture/test_memory_temporal_evolution.py tests/benchmarks/memory/test_temporal_research_contract.py
```
