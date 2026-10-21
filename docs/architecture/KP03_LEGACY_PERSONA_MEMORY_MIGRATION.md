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
1. Audit callers in backend, tests, tools, plugins and UI via local repository-wide search (`rg -n 'persona_memory_entries|store_persona_memory|recall_persona_memories|_store_memory_entry|_retrieve_memories' --glob '!**/node_modules/**' .`). GitHub code search was incomplete, so no claim of zero callers.
2. Determine whether each legacy user_id and tenant_id maps to an authorized canonical UUID pair. Quarantine unmatched rows, never invent identity.
3. Determine per-record consent and permissible retention from authoritative user/tenant policy, not legacy contents or persona tags. No blanket grant.
4. Design idempotent, transactional, versioned backfill into the existing NeuroVault write protocol, with explicit signed/audited migration authority. Preserve source record IDs solely as provenance and redact secrets.
5. Prove unchanged source row counts, migrated/rejected/quarantined receipts, tenant and user isolation, rollback/resume, revocation, expiration, and no duplicate replays against disposable PostgreSQL.
6. Confirm rollout telemetry and recovery plan, then separately review retiring legacy readers/table. Never drop the table in KP-03 without archival and deletion approval.

## Outstanding proof
Persona lifecycle CI tests have been committed but latest-head passage is unverified. An inventory count is not migration completion.
