# KCOMM-03E: Committed inbox invalidation boundary

The durable PostgreSQL CommunicationsInboxRepository remains the sole inbox
authority. Its existing scoped admission, reconciliation and mutation methods
emit a best-effort internal Redis wake-up only after confirmed transaction exit
and only when a new record or lifecycle change was committed. No-op replay,
denial, conflicts and rollback do not publish. Privacy erasure/cascade and
other writers are not covered by this seam; canonical polling remains mandatory.

The signal is the fixed literal `communications.inbox.changed.v1` on an
exact server-derived user topic in the existing Redis manager namespace.
No notification content, row ID, revision, count, or token is transmitted.
The Redis broker and its ACL/network are trusted infrastructure, not a
browser-accessible authorization surface. A recipient count is only a broker
acknowledgment, never a delivery receipt. Outages and timeout do not turn a
committed write into a reported database failure. No local fallback, retry,
new queue, store, or new Redis client lifecycle.

Configuration (central runtime settings and .env.example):

- `KARI_ENABLE_COMMUNICATIONS_INVALIDATION=false` (strict boolean, default off)
- `KARI_COMMUNICATIONS_INVALIDATION_TIMEOUT_MS=250` (1–1000 ms)

This flag does not activate the terminal producer, expose a route, or establish
client connectivity. The optional publisher reuses the app-owned Redis manager
if already initialized; unavailable/degraded Redis leaves HTTP reads intact.
Cancellation is not swallowed; the client may need existing uncertain-write
reconciliation.

Next: bounded authenticated subscriber lifecycle, fresh session and RBAC
validation at delivery, exact owner channel selection, nonbuffered proxy,
coalesced canonical GET, cleanup, reconnect, and real Redis cross-worker proof.
Never forward arbitrary broker content or treat it as a user-facing event.
Do not activate until those boundaries have been verified.
