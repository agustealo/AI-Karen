# MEDUSA-CLOSURE-2: Real PostgreSQL/Redis cancellation proof

The source CI integration in `tests/integration/test_live_medusa_cancellation_stores.py`
uses disposable actual PostgreSQL 16 and Redis 7 instances through the canonical
Medusa persistence and coordination adapters. It never substitutes in-memory
test doubles, creates production tables at runtime, or silently skips a failing
service when explicitly enabled.

The test applies the versioned Medusa SQL migrations in its dedicated disposable
CI database, starts two independent run-manager instances with distinct worker
identities, verifies cross-tenant denial, commits a cancellation plus audit
reference to PostgreSQL while leaving Redis running, observes the live lease
owner recover the request, verifies the real worker-local task receives
`CancelledError`, and asserts the exact SQL transition history and preserved
audit reference after observed terminalization.

This is an **integration acceptance**, not a full production-host certification:
both run managers operate in one Python interpreter, Redis and PostgreSQL are
disposable CI services, and process-kill/restart plus multi-host timing are not
tested. Terminal cancellation is recorded only after the task has actually
observed cancellation; an accepted request is not itself terminal evidence.

Remaining gates: separate worker OS processes; crashed-owner and replaced-lease
fencing; PostgreSQL latency/failure while Redis renewal continues; production
role-backed RLS; and an authenticated target installation's audit-readback.

## KCON-471: Distinct OS owner process and crash-fencing acceptance (candidate)

The same disposable real-store CI now launches a separate Python OS process
running the original Medusa manager with independent Redis/PostgreSQL clients.
The requester remains outside that PID. The owner reports an explicit ready
and cancelled event, the requester commits cancellation to PostgreSQL without
signaling Redis, and the child finalizes only after its own task observes
cancellation. PostgreSQL transitions and original audit reference are read
back by the requester after the child exits.

A second child is terminated by the test process. Its durable row must remain
running, never fabricate a cancelled terminal outcome. After its real Redis
lease expires, cancellation is refused; replacing the lease value without
matching owner metadata still cannot authorize cancellation or old-owner
heartbeat. These are controlled process-termination and stale-lease checks,
not proof that a restarted worker can resume a killed asyncio task.

Remaining: production-role tenant RLS, authenticated target-host audit readback,
recovering workers after infrastructure restart, and real network partition
or PostgreSQL pool-starvation timing. No test may declare those passed.

## KCON-471: PostgreSQL read stall versus live Redis lease (candidate)

The existing real-store suite now holds a genuine PostgreSQL
`ACCESS EXCLUSIVE` table lock on the disposable Medusa run table for
longer than the configured Redis lease TTL. It polls the actual lease
TTL and checks the owner task remains active while the canonical
`MedusaRunManager` times out its durable recovery reads and renews
Redis ownership. Once the lock is released, the test commits a
durable-only cancellation request, observes an independently occurring
`CancelledError` with a shielded test timeout, and verifies that
terminal `cancelled` is recorded only after task interruption.

This proves bounded recovery-read behavior under **SQL lock contention**
on disposable CI infrastructure, not full PostgreSQL unavailability,
connection-pool exhaustion, Redis network partition, post-crash task
resurrection or production-host execution. Exact-head source CI and
real-service execution are required before claiming that proof passed.

## ARM-11I: isolated Redis restart and memory-pressure candidate

The existing real SQL rollback / independent-process terminal recovery scenario gains an explicitly opted-in private loopback Docker Redis instance. The positive control uses AOF with appendfsync always, kills Redis with SIGKILL, restarts the same container, checks the exact retained receipt and pending index, then forces volatile-lru eviction and OOM using a deliberately below-baseline memory cap. Restores capacity before existing late-cancellation and durable recovery assertions. The negative allkeys-lru control checks that PERSISTed receipt and discovery keys can be evicted; it does not assert recovery from actual evidence loss. The shared Redis service is not reconfigured. CI opts in with KAREN_MEDUSA_REDIS_RESTART_ACCEPTANCE=1; local opt-in requires Docker and a preloaded redis:7-alpine image. No production config change, power-loss durability, failover guarantee or deployment acceptance is claimed. Irrecoverable-evidence behavior and shared consumer capacity/eviction impact remain separate release blockers.

The first infrastructure execution (job 140225498457) reached SIGKILL/start and internal PING but failed host-side manager initialization (20 passed, 1 failed). Resolve the published loopback endpoint after every start, wait for bounded host-side PING, then reconnect the same canonical manager. Assert same container ID and different Redis server run ID. This distinguishes server restart from transport readiness; no receipt assertion is relaxed. Port reassignment versus readiness timing was not identified in the original logs.
