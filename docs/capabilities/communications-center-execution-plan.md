# Communications Center execution and evidence plan

## Status at 2026-11-26

Source baseline: `908e900e90aaeae54c02fb4454f349bbc9da671c`. The functional Decisions inbox (#1330) is squash-merged. Its exact PR head `098bb190a800c250a38575ba0d22faa275e9f820` passed eight checks, including 139 frontend test files / 1,461 tests, 15 Communications tests, and the actual admin route regression. The P1 missing approval provider finding was fixed and its review thread resolved. The dashboard and /admin each mount the canonical principal-scoped approval controller above their workspace tabs; these are separate route mounts, not a cross-tab or cross-route global lock. Backend authorization remains canonical. Real authenticated browser acceptance and deployed revision acceptance are not established.

| Slice | Source status | Proof or boundary |
| --- | --- | --- |
| KCOMM-01A | Merged | Actionable operational snapshot, #1322 |
| KCOMM-01B.1 | Merged | Backend workflow discriminator, #1323 |
| KCOMM-01B.2 | Merged | Shared approval controller, #1326 |
| KCOMM-01B.2A | Merged | Verified conversation handoff, #1327 |
| KCOMM-01B.3 | Merged | Persistent provider, #1329 |
| KCOMM-01B.4 | Merged | Decisions inbox, #1330 |
| KCOMM-02A | Design and ownership audited | No migration or database execution yet |
| KCOMM-02B | Pending | Scoped repository/service/API |
| KCOMM-02C | Pending | First real producer and recoverable admission |
| KCOMM-02D | Pending | Consumer inbox lifecycle |
| KCOMM-03 | Pending | Realtime invalidation, replay, reconnect |
| KCOMM-04–11 | Pending | Channels, intelligence, briefings, memory, schedules, preferences, conversation UX, acceptance |

## KCOMM-02A: ownership and storage contract

### Reuse inventory

| Existing source | Owns | Does not own |
| --- | --- | --- |
| `api_routes/content/communications.py` | Scoped operational snapshot | Durable inbox or total unread count |
| `persistence/repositories/approval_repository.py` | Authorization decisions and consumption | Notification read or archive |
| `persistence/repositories/chat_run_repository.py` | Run lease, terminal state, replay and recovery | Human attention state |
| `agent_medusa/execution/run_manager.py` and Medusa run/transition migrations | Specialist execution and coordination | Personal inbox acknowledgment |
| `persistence/repositories/channel_repository.py` and channel inbox/outbox | Verified provider admission and delivery | General notification lifecycle |
| `maintenance_notification_requests` in the core runtime migration and SQLAlchemy models | Maintenance-specific subscriptions and dispatch | General notification lifecycle |
| `core/realtime/events.py`, `services/database/repositories/realtime_event_registry.py`, `realtime_accessor.py` | Versioned event transport, including notification.created.v1 | Durable delivery, read state or source authority |
| `event_bus/__init__.py` and extension communication manager | Internal event and extension messaging | Personal inbox |
| `services/privacy_compliance.py` | Export and erasure | UI local draft or retention claims |
| `NotificationSettings.tsx` | Existing /api/settings/notifications preference projection | Notification record storage |

The inspected migrations, model definitions and repository contracts do not expose a general durable inbox read/acknowledge/archive lifecycle. Finish reference search of any maintenance producer, account deletion, all privacy callers and schema bootstrap before activating a new producer. Do not replace channel queues, approvals, audit logs, or runtime journals.

### First source: conversation-owned terminal chat execution

Use the existing `runtime_chat_runs` ledger for the first narrow inbox source, initially failed/orphaned runs requiring attention. Do not use the optional AG-UI event journal as terminal authority or assume an orphaned run can be safely restarted. The canonical run repository's status/readback and recovery contracts determine what can be shown. A completed run alone does not prove a saved artifact or successful downstream effect.

The existing migrations establish reusable keys:
- `20261025020000_43_runtime_chat_run_ledger.sql`: runtime chat execution identity and terminal state; tenant/user FORCE RLS.
- `20261025050000_46_runtime_chat_event_journal.sql`: unique index `uq_runtime_chat_run_full_scope` on (execution_id, tenant_id, user_id, conversation_id).
- `20261118213000_64_kui_presentation_pin_references.sql`: `conversations_scope_reference_unique` on (conversation_id, tenant_id, user_id); reference-only design with source deletion cascade and client role revocation.
- `20261125030000_76_runtime_chat_unresolved_run.sql`: unresolved orphaned runs retain the admission fence. Inbox acknowledgment must not clear it.

Do not create another execution ledger or an untyped polymorphic reference whose ownership cannot be enforced. The initial migration may define a single communications lifecycle relation with a narrowly constrained source type and a typed execution reference; future source kinds require explicit schema constraints and owner-specific admission. Do not pre-enable arbitrary sources or free-form notification creation.

Proposed row contract (not yet implemented):

| Field | Meaning |
| --- | --- |
| entry_id | Server-issued stable UUID |
| tenant_id, user_id | Authenticated principal |
| conversation_id, execution_id | Composite reference to actual run and conversation |
| source_kind | Closed allowlist, initial terminal execution attention kind only |
| created_at | Server-generated insertion timestamp; not delivery time |
| read_at | Nullable server timestamp |
| acknowledged_at | Nullable explicit human acknowledgment timestamp |
| archived_at | Nullable explicit archive timestamp |
| revision | Positive bounded compare-and-swap version |

Require both composite FKs, on-delete cascade to source run AND conversation. Do not store titles, user content, prompts, raw error strings, event payloads, secrets, provider responses, or copied execution status. Derive safe status and display reason at readback from the current owner. A unique constraint on source identity + principal + source kind provides idempotent producer admission. Enforce source identity immutability and valid lifecycle timestamps. Use bounded owner-ordered indexes. A schema row is not proof of source eligibility: backend must admit a terminal source with exact current ownership and read back the original authority.

### Security and privacy gates

- Use the existing async scoped PostgreSQL transaction manager (`persistence/postgres/transactions.py`) with tenant AND user context. Do not construct context from request-body principal IDs. FORCE RLS with both settings in USING/WITH CHECK, deny missing scope, revoke PUBLIC and existing anon/authenticated roles; plain PostgreSQL startup must work if Supabase-specific roles do not exist. Verify grants with a non-owner, non-BYPASSRLS application role. No direct client Data API or SECURITY DEFINER bypass.
- Current `DataExporter` supports memories, conversations, analytics, audit logs; `DataEraser` supports memories and conversations, and rejects other data categories. Do not claim that a new inbox category is already covered. For this first conversation-bound reference, include lifecycle metadata in canonical conversation export and verify conversation deletion cascade. If independent inbox erasure is introduced, extend the same privacy authority and its supported-data contract explicitly. Preserve source erasure and account/tenant deletion behavior; verify the existing runtime ledger's RESTRICT on user deletion and don't bypass it.
- No separate cache as authority, no speculative producer, no migration-time historical backfill. If later backfill is approved, prove it cannot recreate intentionally erased/archived records or materialize a revoked/deleted source.
- Define retention by source and privacy lifecycle before activation. Archive is visibility state, not privacy erasure. Read/acknowledgment is not approval, execution, provider delivery, or a restart permission. A failure notice must never reveal raw exception messages.
- No service-wide cleanup script or production database changes as part of this source task.

## KCOMM-02B: repository, API and lifecycle

Use one repository/service owner and thin authenticated routes in the existing communications ingress. Require stable source eligibility, bounded keyset list, explicit count semantics, validated identity and revision on mutation. A retry of the same already-applied operation must read back authoritative state, not increment again or return fictional success. Use server timestamps; enforce stale revision rejection and concurrency serialization. Acknowledge implies read, archive must not implicitly acknowledge. Unarchive/mark-unread are separate product decisions, not hidden side effects. Verify exact mutation identity/receipt and reconcile uncertain network outcomes before retry. Use structured safe correlation events and existing audit owner; never copy audit ledger.

## KCOMM-02C/02D and 03

One real terminal source producer first. Prove commit/admission and recovery ordering, uniqueness on duplicate producer attempts, source deletion races, failure isolation from original runtime truth, and no premature notification success. No arbitrary public creation endpoint. Existing notification.created.v1 / user-topic publish can be a best-effort invalidation hint only after durable persistence. No realtime event is a receipt of human delivery.

Use one principal-scoped inbox controller. Show verified bounded pending/unread/archived states, source context, explicit controls and safe errors. Keep Decisions in the existing ApprovalService/provider. For realtime, audit `useUserNotifications.ts`: initial client ref survives tenant parameter changes, append-only transient state has no deduplication, and no durable reconnect reconciliation. Do not wire it to personal data until tenant/user/session fencing, bounded dedup, subscription teardown and durable readback are proven. Existing preferences remain governed by their owner; do not invent a second settings surface.

## Acceptance gates

1. Generate forward-only migration using the repository's local Supabase toolchain; verify unique version and full migration baseline. No runtime DDL.
2. Real disposable PostgreSQL proof of same-tenant other-user and cross-tenant read/write denial; missing scope, client grant denial, composite source mismatch, duplicate source constraint, concurrent CAS/retry, rollback, source deletion and privacy export/erasure. Verify full migration chain and first-boot without optional client roles. Keep CI exact-head checks and independent review.
3. Service/API tests for auth-derived identity, eligibility, safe bounded projections, count semantics, idempotent read/ack/archive, source revocation/deletion, stale/uncertain receipts, fail-closed errors. Include redaction and correlation proof.
4. Consumer account switching, stale response, explicit action, disabled/unknown states, accessibility and responsive acceptance. Authenticated browser evidence uses a sanctioned real principal; no mock production success.
5. No deployment-ready claim until actual deployed/local revision and signed-in browser acceptance. Vercel quota failure is not source quality failure.

This document is a source-level implementation contract, not a schema migration, storage implementation, or live proof. The available work environment lacked the local Supabase CLI and PostgreSQL binaries; do not use a connected production database as a substitute for disposable verification.
