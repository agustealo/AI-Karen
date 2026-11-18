# KCR-04E | In-process memory claim store owner isolation

**Base dependency:** KCR-04D PR #1023, itself stacked on KCR-04B PR #1019.
**Baseline:** `071aa01b4fdcb13fdaa6e23763916354fba57d0b`.
**Scope:** The already-existing `MemoryClaimStore` in `src/ai_karen_engine/core/memory/claims/__init__.py`. No new store, runtime, registry, route, database schema, migration, provider, or dependency.

## Finding and evidence boundary

The original in-process store had no owner context. Its key was `subject:predicate:object`, which omits tenant and user. It also exposed `get()`, `get_by_subject()`, `get_valid_claims()`, `get_claims_by_status()`, mutation helpers, and contradiction detection without caller scope. Sharing a single instance across tenants/users could permit collisions or disclosure.

**This is a real API design weakness but is not an observed production breach.** Direct runtime-memory modules inspected did not construct `MemoryClaimStore`. The GitHub code search index was incomplete, so production-wide caller coverage and actual injection lifecycle remain unknown. Core exports the class publicly; callers outside the inspected package remain a migration risk.

## Source caller census (read-only, exact branch)

An API-backed walk of the complete `src/ai_karen_engine/core/memory` tree at Git tree `ad1fcb42d2c766d025d84cdc414cbb66fdbefd84` enumerated **109 Python files**. Every file was read from the KCR-04E branch. Searches for exact `MemoryClaimStore` and `get_valid_claims` symbols found only the canonical class/implementation in `claims/__init__.py` and its public export in `memory/__init__.py`; there were **zero direct callers in the memory package and zero unread files**.

A second focused read of 16 additional runtime/composition modules, including `core/cortex/memory_formation.py`, LangGraph memory nodes, `runtime/memory/coordinator.py`, and the integrations/memory entry points, found no direct use of either symbol. That is a **125-file source audit**, not a repository-wide executed AST census. Dynamic import aliases and other packages remain unverified until the checkout-based architecture gate executes.

These observations support the decision to keep this change in the existing in-process utility rather than adding a new store or altering the durable ledger. They do not prove that the public export has no external consumers or that caller-provided scope strings are authenticated.

## Additional key-replacement integrity repair

An exact-head adversarial reproduction showed that a retained mutable claim could
be changed to a foreign user or tenant after insertion and then silently
overwritten by a same-key `add()` or `evolve()`. Incoming-only scope checking
did not protect the record already present at the destination key.

`MemoryClaimStore._checked_replacement_id()` now validates an existing
destination record against the bound owner before any replacement. This
preflight is reused before `evolve()` and `supersede()` mutate a prior record.
Three regression tests prove rejection and absence of partial writes. These
are single-process integrity guarantees, not runtime authentication, locking,
or database transaction isolation.

## Correct owner and behavior

- Bind each `MemoryClaimStore` at construction to explicit immutable tenant and user identifiers; `user_id=None` represents a distinct tenant-level owner.
- Enforce same-owner claim insertion and reject foreign scope on evolution and supersession *before* mutation.
- Demand tenant and user scope for each public read and identity-targeted mutation; verify those values against the bound store.
- Revalidate stored record ownership even on reads, failing closed when mutable claim objects have been changed after insertion.
- Preserve the existing within-owner key format, temporal evolution owner, single-UTC snapshot semantics from KCR-04D, and canonical claim lifecycle.
- Emit generic errors without disclosing the stored tenant, user or claim payload.

**Caller-supplied scope strings are not authentication.** The runtime must obtain these values from an authenticated and authorized principal, and must not inject a store from another scope. This Core utility must not replace RuntimePolicy, RBAC, session, tenant, or NeuroVault authorization.

This is intentionally an **API-breaking change** to an exported in-process utility. Do not merge until a repository-wide import/call census and any necessary same-scope caller migrations are completed.

## Adversarial regression proof

`tests/architecture/test_memory_claim_store_scope.py` asserts:

- No missing/default tenant, invalid user, or absent constructor scope
- Identical claim keys remain isolated in two different owner-bound store instances
- Foreign tenant and foreign user are rejected by every public read entry point
- Missing read scope is an error, never a fallback to unscoped access
- Cross-owner insert, evolution and supersession cannot mutate existing records
- Foreign confidence updates are denied before mutation
- Mutated stored records cannot leak through any read path
- Multi-claim contradiction evaluation validates every stored owner before modifying any claim, avoiding partial writes when a later entry has been corrupted
- Tenant-level and user-level owner scopes are distinct

Existing KCR-04B/04D temporal tests are migrated to pass the explicit owner context. `Main Quality Gate` now explicitly invokes the new security contract module.

## Guarded caller compatibility

`tests/architecture/test_memory_consumer_domain_migration.py::test_cognitive_claim_store_has_no_unreviewed_static_callers` extends the **existing canonical memory consumer migration suite**, rather than introducing another scanner or owner. It walks Python files in `src`, `tests`, `scripts`, `plugins`, and `extensions` of a complete checkout. Only the existing class definition, public export, and deliberately migrated architecture/security tests are reviewed references. Any additional literal `MemoryClaimStore` occurrence causes a test failure with the source path, requiring an explicit migration decision.

This guard is committed and included in the already-existing Main Quality architecture suite. **It has not yet executed on this exact PR head**. The textual check is intentionally conservative: references in comments can require review, and unresolved alias/dynamic-import references still need an independent import/call census. A clean run would be evidence for static references in the scanned checkout, not end-to-end authorization or live production reachability.

## Acceptance not established by this PR

- Actual production reachability, injection lifetime, and all direct/dynamic callers
- Authenticated end-to-end tenant isolation and user RBAC
- Live PostgreSQL/RLS or durable ledger as-of parity
- Graph source consent, NeuroVault deletion and external tool response policies
- Hosted Vercel preview, exact-head CI, or independent review until their observed results are available

## Required proof and merge sequence

1. Exact import/caller census across `src`, `tests`, `scripts`, backend routes, plugins, and dynamic imports, including the public `core.memory` export.
2. Migrate any legitimate call sites, with authorized runtime scope as the only source. Never infer scope from a request JSON field.
3. `PYTHONPATH=src pytest -q tests/architecture/test_memory_temporal_evolution.py tests/architecture/test_memory_claim_store_scope.py tests/benchmarks/memory/test_temporal_research_contract.py`
4. `ruff check src/ai_karen_engine/core/memory/claims/__init__.py tests/architecture/test_memory_temporal_evolution.py tests/architecture/test_memory_claim_store_scope.py`
5. `python -m compileall -q src/ai_karen_engine/core/memory`
6. Exact-head Main Quality, Cognitive Proof, First-Boot, independent review and deployment acceptance. Keep this PR a draft while upstream PRs or Vercel/Codex quotas are blocked.
7. Merge KCR-04B (#1019), then KCR-04D (#1023), then reconcile this PR onto live `main` and repeat all exact-head checks. KCR-04C (#1022) remains an independent owner.

**Release status:** PROPOSED, unmerged. The source changes and tests are committed; running them and proving production authorization remain explicit gates.
