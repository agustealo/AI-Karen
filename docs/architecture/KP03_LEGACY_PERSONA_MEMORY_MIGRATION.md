# KP-03 legacy persona memory retirement gate

**Status:** Inventory and migration design only. Do not drop or copy production records until the owner, consent, identities and replay semantics are verified.

## Ownership
- Legacy schema: `supabase/migrations/20260827010000_01_core_persona_runtime.sql` creates `persona_memory_entries` with free-form tenant/user strings, content, persona attribution, optional embedding identifier and timestamps.
- Migration 40 protects the legacy table with tenant row-level security. Keep this protection while records exist.
- `PersonaService` no longer executes direct legacy memory SQL. Canonical ChatRuntime -> MemoryRuntimeManager/formation -> NeuroVault owns writes; RuntimeEvidenceResolver -> NeuroRecall owns eligible reads.
- Canonical NeuroVault requires scoped UUID identity, explicit RuntimePolicy write authorization, consent and auditable provenance. Legacy rows cannot be bulk-copied as privileged writes.

## Read-only inventory
Execute `python scripts/audit/persona_legacy_memory_inventory.py --tenant-id <authorized-tenant>` using a DB role whose app.current_tenant_id session context and RLS have been verified. Results contain aggregate counts only, no content or user IDs. The tool never elevates roles, infers cross-tenant scope or mutates data.

## Blockers before migration
1. Audit callers in backend, tests, tools, plugins and UI using `python scripts/audit/persona_memory_references.py --root . --output persona-memory-references.json` (or `rg -n 'persona_memory_entries|store_persona_memory|recall_persona_memories|_store_memory_entry|_retrieve_memories' --glob '!**/node_modules/**' .`). GitHub code search was incomplete, so no claim of zero callers.
2. Determine whether each legacy user_id and tenant_id maps to an authorized canonical UUID pair. Quarantine unmatched rows, never invent identity.
3. Determine per-record consent and permissible retention from authoritative user/tenant policy, not legacy contents or persona tags. No blanket grant.
4. Design idempotent, transactional, versioned backfill into the existing NeuroVault write protocol, with explicit signed/audited migration authority. Preserve source record IDs solely as provenance and redact secrets.
5. Prove unchanged source row counts, migrated/rejected/quarantined receipts, tenant and user isolation, rollback/resume, revocation, expiration, and no duplicate replays against disposable PostgreSQL.
6. Confirm rollout telemetry and recovery plan, then separately review retiring legacy readers/table. Never drop the table in KP-03 without archival and deletion approval.

## Outstanding proof
Persona lifecycle CI tests have been committed but latest-head passage is unverified. An inventory count is not migration completion.

The source scanner reports file, line and symbol, including declarations and tests. Every result must be classified as active, compatibility, migration, test or dead before deletion. A scanner commit alone is **not** a completed repository-wide audit; run it on a full checkout and review the results.

## Strict reference triage
Run `python scripts/audit/persona_memory_references.py --root . --output persona-memory-references.json --fail-on-review` on a full checkout. A nonzero exit signals an unresolved production reference; it does not delete or modify code. Classifications are `historical_schema`, `audit_tool`, `test_reference`, `compatibility_declaration`, or `requires_review`. Review each unresolved result manually and record its active owner before removing or redirecting it. This is a conservative triage, not proof that all historical data can be migrated.

## Verified source reference inventory, 2026-10-21

- GitHub Actions run [39702857769](https://github.com/agustealo/AI-Karen/actions/runs/39702857769) completed successfully. Uploaded artifact `persona-memory-reference-inventory` (ID `12394131464`) contained 30 references: 11 test references, 9 audit-tool references, 6 historical-schema references, 2 fail-closed compatibility declarations and 2 references in the existing live PostgreSQL proof workflow.
- The two previously `requires_review` matches in `.github/workflows/live-postgres-memory-proof.yml` are confirmed legacy-table RLS/security proof checks, not live application memory consumers. The scanner now assigns them `security_proof` classification.
- No active application caller of the retired legacy APIs was identified **in this complete scanned checkout**. This is code-reference evidence, not a guarantee about unindexed external consumers or historical stored records.
- Do not remove historical schema or security proofs yet. No user data backfill has been conducted. Before retiring table: inventory real tenant-level counts; prove authorized identity mapping, per-record consent, idempotent NeuroVault migration and recovery; verify all relevant deployments and integrations.

## Historical record readiness inventory (read-only)

`scripts/audit/persona_legacy_memory_inventory.py` now reports aggregate invalid UUID-shaped user/tenant identifiers and blank content counts in addition to existing provenance counts. These are **triage signals**, not eligibility determinations. An identifier matching UUID syntax does not establish that the canonical user exists, is authorized, or belongs to the same tenant. Output explicitly fixes `migration_eligible=0` and `eligibility_status=unverified_consent_and_identity` until a separately audited, tenant-scoped identity/consent reconciliation exists. Do not use this aggregate inventory as an import source or authorize bulk replay. The command is read-only and must execute under a verified RLS tenant context. No automatic migration is performed.

## Pure migration preflight contract

`core/memory/legacy_persona_preflight.py` is a pure decision helper used **only after** trustworthy evidence is collected. It accepts separately supplied legacy and authorized tenant/user identities plus explicit verified identity, consent, retention and source-record flags. It fails closed on malformed IDs, mismatches and any unverified evidence, returning non-sensitive reason codes. An eligible *preflight* result is **not** a RuntimePolicy grant and cannot call NeuroVault. The next executable migration step must obtain fresh authenticated tenant/user mappings, prove record-level consent and retention, acquire governed write authorization, and persist idempotent replay receipts; never turn a Boolean supplied by a legacy row or user-facing request into proof.

### Evidence-origin guard
The preflight now rejects evidence whose origin is not explicitly marked `authorized_runtime`. This is a **defense-in-depth marker, not cryptographic attestation or RBAC enforcement**: a caller can construct the dataclass, so migration execution must still derive all evidence server-side from authenticated canonical sources and independently obtain a valid RuntimePolicy write grant. Never expose this preflight contract directly as a user-controlled API payload.

## Independent write-admission boundary

`core/memory/legacy_persona_admission.py` requires both eligible preflight and an explicitly granted, principal-scoped `memory.write` policy decision. This is a **pure guard**, not an authorization service or executable migration: its dataclass values can be fabricated by an untrusted caller. Only the canonical runtime may construct it from authenticated policy decisions, and NeuroVault must independently enforce the authentic RuntimePolicy/consent at persistence time. No new write owner, bypass or bulk-import endpoint is introduced. Negative tests cover policy denial, preflight denial, principal mismatches and missing write capability.

## Deterministic replay identity, not execution authorization

`derive_legacy_migration_replay_identity` derives stable UUIDv5 `memory_id` and `request_id` from canonical tenant/user identifiers plus the immutable legacy source-record ID. NeuroVault's existing idempotency key includes `request_id`, so arbitrary fresh request IDs on retry cannot provide durable replay semantics. This helper does not read rows, assert consent, create `VaultContext`, migrate memories or persist receipts. Before using it, the future migration executor must verify the separately authorized admission is bound to the identical principals, re-check current consent/retention and carry trusted policy evidence into NeuroVault. Store actual write receipts in the governed ledger. No general chat idempotency behavior is changed.

### Principal-bound replay admission

`LegacyMigrationAdmission` now carries the tenant/user identity for the admitted decision; rejected decisions carry no principals. Retry-identifier generation rejects a different requested tenant or user even when `admitted=True` was returned for another principal. This prevents accidental cross-principal reuse of an approved decision in the pure migration helper. Its dataclass remains forgeable; authenticated execution must still derive it from canonical runtime policy, revalidate current consent and let NeuroVault enforce its own checks.

### Consent revocation versus idempotent replay

The disposable PostgreSQL NeuroVault integration proof now writes one synthetic admitted migration record twice, revokes its consent scope, and asserts that a further retry with identical deterministic IDs is rejected. This ensures replay identifiers never function as a consent bypass. The existing canonical vault checks current consent before it looks up a duplicate idempotency key. This is a test of the current ordering, not an alternative migration writer, and no historical records are touched.

### Interrupted-run receipt reconciliation

`legacy_persona_recovery.py` now provides a pure, fail-closed classification of *already authenticated, tenant/user-scoped* persisted receipt evidence. A matching persisted memory receipt means do not retry; an absent receipt can permit **consideration** of retry only after new consent, retention and policy checks. Partial, failed or cross-principal receipts are blocked pending operator reconciliation. This helper does not fetch receipts or prove that a receipt is authentic, and `safe_to_retry` must not be interpreted as a write grant. Durable canonical ledger lookups and authenticated migration execution remain outstanding.

### Canonical ledger recovery evidence

`platform/memory/postgres/legacy_persona_receipts.py` performs a read-only, fully tenant/user-scoped `MemoryAssertion`/`MemoryEvent` join and passes scoped receipt facts to the existing pure recovery classifier. Its evidence is not a permission grant: a missing record can only trigger renewed authorization, consent and retention checks. An integration test exercises matching persisted receipt evidence and cross-tenant non-disclosure against disposable PostgreSQL. The adapter uses `memory_persisted`, the existing NeuroVault event type. The ledger remains the sole durable source of truth; no parallel receipt store or backfill process is added.

### Replay request provenance requirement

Recovery lookup now requires the deterministic expected migration request ID alongside memory ID and authenticated tenant/user scope. Even if an assertion with the expected ID exists, its canonical `MemoryEvent.payload.vault.request_id` must match the expected operation before recovery reports a successful prior migration. A mismatch blocks automatic retry and requires reconciliation; the adapter does not use the stored request ID as an authorization token. Synthetic PostgreSQL tests assert that a mismatched request is not classified as already migrated.

### Recovery is not authorization

A canonical ledger receipt can prove that a migration operation already persisted; it cannot prove continuing permission to write or to keep that content. `requires_fresh_migration_authorization` identifies only an absent-receipt retry candidate, which must still pass fresh canonical identity mapping, consent, retention, runtime policy and NeuroVault enforcement. Existing or conflicting receipts never trigger automatic replay. This helper has no migration execution capability.
