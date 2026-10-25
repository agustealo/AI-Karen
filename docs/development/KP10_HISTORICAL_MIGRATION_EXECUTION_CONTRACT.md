# KP-10: Authenticated Historical Persona Migration

Status: **NOT EXECUTABLE**. Historical NeuroVault writes must remain denied until
the acceptance matrix below passes on disposable PostgreSQL. This is an
implementation contract, not evidence that migration has been enabled.

## Canonical ownership

- Auth middleware establishes current JWT/session identity and revocation.
- Runtime owns the entire migration invocation and one PostgreSQL transaction.
- RuntimePolicy authorizes the exact migration action and session.
- The existing PostgreSQL source adapter owns locked source, identity,
  consent and retention evidence.
- The existing replay receipt adapter owns deterministic replay-slot locking.
- NeuroVault is the **only** writer of the canonical memory event and assertion.
- PostgreSQL commit, not a staged VaultWriteReceipt, defines success.
- No API route, UI handler or inspection receipt may issue write capability.

## Implementation sequence

1. Enter through authenticated HTTP ingress. Validate the requested source
   identifier and require the migration-specific RuntimePolicy action.
2. Derive replay identity from tenant/user/source with the existing canonical
   helper. Do not accept a client-chosen memory or request identifier.
3. Open `async_transaction_scope(tenant_id=..., user_id=...)` **once**.
   All later source, replay, authorization and write work uses this session.
4. Hold source, consent, retention and replay locks through staging and commit.
   Read historical content only within the executor, never in the read-only
   inspection API or in a response/log.
5. Recheck authenticated session and RuntimePolicy after awaited dependency
   calls, and recheck locked consent/retention/replay immediately before write.
6. Mint a **non-serializable, single-use** runtime execution capability bound
   to this exact session, transaction ID, principal, source, replay identity,
   final policy decision, and consent evidence. A frozen dataclass, caller
   supplied flag, inspection receipt or public constructor is insufficient.
7. NeuroVault must independently verify and consume that capability in its
   public transaction gate **and** internal ledger gate. Standalone `persist()`
   must continue to reject historical entries unconditionally.
8. Persist exactly one canonical MemoryEvent and MemoryAssertion via NeuroVault.
   Use deterministic replay identifiers and preserve existing audit and RLS.
   Do not return success from a staging receipt.
9. Commit inside the transaction owner. Return a durable receipt only after
   successful commit, with correlation, policy decision and replay metadata,
   but no historical content.
10. Any denial, collision, cancellation or commit failure must roll back and
    not return success. Preserve the canonical shielded rollback and
    invalidation-on-failure behavior.

## Acceptance matrix (required, not yet passed)

| Scenario | Required result |
| --- | --- |
| Authorized source, active consent, valid retention | One committed event and assertion |
| Repeated request after commit | Existing receipt, no second write |
| Two concurrent requests for missing replay slot | One winner, no duplicate |
| Consent revoked before final write | Deny, zero committed rows |
| Permission/session revoked during awaited policy | Deny, zero committed rows |
| Tenant or user scope mismatch | Deny before content exposure |
| Expired retention or invalid source | Deny, zero committed rows |
| Forged, replayed or expired execution capability | Deny in both Vault gates |
| Cancellation during stage, final scope, or commit | No false success; verify durable outcome |
| Commit exception or failed rollback | No success; invalidate uncertain session |
| Ordinary memory write | Existing behavior unchanged |
| Standalone historical Vault write | Deny regardless of supplied context |
| Read-only historical inspection | Metadata only; no payload read |

Run focused unit tests, disposable PostgreSQL integration tests, the full
memory test suite, import checks, Ruff, mypy and API contract tests. Document
exact head SHA, PostgreSQL engine, commands and outcomes. Neither build-rate
limits nor unavailable hosted CI establishes a green result. Do not merge
or enable execution until these proofs exist.

## Current blocker

`execute_authenticated_legacy_migration` intentionally fails closed.
`PostgresNeuroVault.persist_in_transaction` and
`PostgresNeuroVault._persist_with_session` independently deny historical
writes. Existing `LegacyMigrationTransactionAuthority` is a read-only,
constructible snapshot, **not** an executable grant. Do not bypass either
writer gate by spoofing metadata or substituting an ordinary consent scope.
