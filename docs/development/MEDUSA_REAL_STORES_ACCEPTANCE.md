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
