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


## KCOMM-03E2: bounded authenticated wait

Use the existing HTTP ingress rather than an indefinitely held SSE connection.
GET /api/communications-center/inbox/wait accepts no query parameters and
returns only {"changed": true|false}, no-store. A false result means an
acknowledged idle wait, not a durable no-change assertion. A 503 means the
hint transport is unavailable; normal authenticated inbox GET remains valid.

The service authorizes COMMUNICATIONS_READ before subscribing and after
closing the subscription, with fresh canonical session authentication on the
original request. Any session failure, changed principal, permission loss,
or disabled flag denies the result. Broker content never enters the response.
Exact owner channel and subscription acknowledgment are required. Disconnect,
cancellation and malformed/foreign frames end the wait. No queue or new
Redis connection lifecycle is introduced. A process-local admission set
limits concurrent waits (one per owner per worker, at most the configured
limit, with at least two pool connections reserved). This is not a global
capacity or rate-limit guarantee; real multiworker load/revocation tests
remain required. The proxy and UI are not yet wired to call this route.

- KARI_ENABLE_COMMUNICATIONS_INVALIDATION_WAIT=false (requires invalidation)
- KARI_COMMUNICATIONS_INVALIDATION_WAIT_SECONDS=10 (1–15)
- KARI_COMMUNICATIONS_INVALIDATION_MAX_WAITERS=2 (1–4 per process)

The Redis read window is bounded; canonical auth, driver cleanup and ingress
deadlines are separate. No claim of lossless delivery, live presence, SSE,
or production activation. Polling remains mandatory for missed hints and
privacy cascades.


### Disposable Redis process-isolation gate

The existing Communications PostgreSQL proof workflow now additionally starts
a disposable Redis 7 container on a dynamically assigned loopback port.
The test uses three independent Python subscriber processes and the canonical
publisher/manager, exact Redis subscription counts, one intended owner and
two foreign scopes (different owner, different tenant). It requires a real
change result for the owner, verified idle results for the other two, and
subscription count zero after exit. It also checks cancellation and resubscribe
using real connections. It does not flush or modify existing Redis data, use
hosted credentials, or change production configuration. This certifies the
broker boundary only, not authenticated end-to-end HTTP revocation or browser
delivery. The test must actually run and pass; an opt-out skip is not evidence.


The canonical authentication middleware also applies no-store to the wait
response before it leaves ingress, covering initial authentication rejection
and dependency rejection as well as successful and post-wait responses.
No duplicate authentication owner or global cache-policy change is introduced.


## KCOMM-03E3B: authenticated frontend reconciliation

The canonical inbox GET reports the explicit configuration capability
`invalidation_wait_enabled`; it is false unless both flags are enabled.
It is not a health or connection receipt. Missing capability means disabled
for compatibility. The API client uses one same-origin cancellable GET for
a wait; no retry, redirect, proactive credential rotation or logout side
effect occurs in the optional path. Ordinary inbox GET retains existing auth
behavior. The mounted view's existing reconciliation effect owns the wait,
cancels on visibility/offline/cleanup and pauses during reads or uncertain
mutations; only an exact boolean change hint may request the canonical
principal-fenced GET. Malformed/unavailable hints back off to normal polling.
A coalesced/missed hint is recovered by periodic reconciliation. No persistent
connection badge, broker payload, optimistic data, or automatic mutation.
Browser-to-backend disconnect and signed-session revocation acceptance remain
required; both server flags stay default-off.
