# MI-08: Paperclip-inspired task ownership, using Karen's existing authority

## Purpose

Adopt the useful *atomic checkout + durable ownership + verified terminal write*
properties of Paperclip without adopting its extra orchestration platform.
This is an integration-hardening slice of Step 3, not a complete task board.

## Owners (single source of truth)

| Concern | Existing owner |
| --- | --- |
| Saved task definition and latest attempt | `SqlAutomationRepository` and `public.automation_tasks` |
| Saved-task lifecycle execution | `services/automation/execution.py` |
| General background lease runner | `services/automation/claim_lease.py` |
| Chat, provider choice and fallback | `ChatRuntime` |
| Intent, policy and agent eligibility | CORTEX and runtime policy |
| Multi-agent execution | Agent Medusa and LangGraph (only when a real graph is needed) |
| Scheduling | Existing cron/queue claim services |
| Configuration | `config/runtime.py::TimeoutSettings` |
| Tenant boundaries | Authenticated `UserData` and DB tenant predicates |

## Behavior

1. An authenticated task execution attempts one SQL UPDATE with a new UUID
   fencing token. An already Running task cannot be claimed until its
   **tokened** lease expires. A legacy Running task with no token refuses
   automatic takeover until explicitly reconciled.
2. The same repository already owns the task definition, so no new table,
   alternate registry or task executor is introduced.
3. Existing shared `run_with_claim_heartbeat` renews the lease while
   `ChatRuntime` handles the work. Ownership loss cancels the in-flight
   coroutine, and the old worker cannot publish success.
4. All terminal updates require the same token, correct tenant, Running
   state, and unexpired lease. They clear the lease after finalization.
5. A concurrent attempt returns HTTP 409, not a second execution or
   fabricated success. Missing tasks remain HTTP 404.
6. Memory, provider and graph controls are unaffected.

## Configuration

`KARI_SAVED_TASK_CLAIM_LEASE_SECONDS` defaults to `900`.
`KARI_SAVED_TASK_CLAIM_HEARTBEAT_SECONDS` defaults to `60`.
The central runtime validator rejects leases under 30 seconds and heartbeat
intervals that are not strictly less than half the lease. The execution
boundary validates the same invariant and fails closed.

## Deploy sequence and legacy safety

Apply `supabase/migrations/20261016010000_28_automation_task_fenced_claims.sql`
before deploying worker code, then cut over all workers to the same version.
Old binaries do not enforce token ownership and should not concurrently
execute saved tasks during the cutover. Any old `Running` rows with no token
require an operator review of whether the work is still executing; migration
does not silently expire or mark them complete.

No runtime schema creation or automatic rollout is performed here.

## Proof matrix

- Two simultaneous claims: exactly one gets the SQL row.
- A live lease blocks a second worker.
- The winning worker can heartbeat; the losing worker cannot.
- Forced expiry permits a recovered claim.
- An old owner cannot finalize after takeover.
- An unclaimed legacy Running record remains non-executable.
- Cross-tenant task lookup does not reveal another tenant's task.
- Runtime rejection, cancellation and lost lease never falsely return
  success to the API.
- CI: `tests/services/automation/test_task_claim_ownership.py`,
  `tests/services/automation/test_execution.py` and
  `tests/integration/test_live_automation_task_claims.py`.

## Deliberately not asserted or implemented

A returned model answer is not proof that a user's business objective was
satisfied. This slice prevents two writers from both owning and finalizing
the same *saved-task attempt*, but it does not yet introduce objective-evidence
review, goal ancestry, per-run work artifacts, budgets or user approval gates.
Those remain explicit follow-up phases and must reuse existing runtime outcome,
approval, audit, agent and memory authorities. The current `Success` status
still means that ChatRuntime returned a nonempty OK/degraded response, not
that an external-world task has independently passed completion review.

Lease expiry cannot undo external side effects from a worker that lost
ownership but has not observed cancellation. Side-effecting tools must retain
their own idempotency and permission boundaries.
