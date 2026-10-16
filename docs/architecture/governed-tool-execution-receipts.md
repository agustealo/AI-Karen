# MI-12: Governed Tool Execution Receipts (Step 3E)

## Finding, authority, and threat model

Medusa's existing `ToolBridge` invokes `ActionExecutionGate` and then
`ToolService`. Prior to MI-12 it emitted a structured log/event, but there
was no append-only proof of the individual governed tool invocation.

An LLM can invent text about tool success, a tool's return value may contain
untrusted data, and a successful HTTP/API acknowledgment does not prove the
destination's final state. This feature records **what Karen's trusted
tool-runtime path actually acknowledged**. It does NOT assert that external
work was independently verified, and cannot be used to auto-approve a
saved task. It is restricted to governed **Medusa ToolBridge** executions;
other plugin, connector and direct-tool paths remain uncovered until audited.

Canonical ownership remains:

- CORTEX/RuntimePolicy: eligibility and authorized execution plans.
- Medusa `ToolBridge` and the existing `ActionExecutionGate`: enforce
  the tool allow-list and authorized principal/tenant/policy decision before
  invoking `ToolService`. Bridge must never choose providers or plugins.
- `ToolService`: actual tool runtime, typed `ToolInput`/`ToolOutput`.
- `OutcomeRecorder` plus `PostgresOutcomeStore`: a new *method*, not a
  new store or event table, appends a typed `runtime.execution` observation.
- Automation execution: link current saved-task attempt to canonical runtime
  request ID, including failed/cancelled attempts. Creator-only service/API
  reads exact matching receipts. No task state changes based on these
  observations.
- UI: display runtime acknowledgment separately from business completion.

## Receipt shape and trust levels

Every executed tool call gets a new runtime-generated UUID `tool_call_id`.
Persisted `outcome_records` payload includes `outcome_id`,
`source=runtime.execution`, exact run `trajectory_id`, tool invocation
request ID, correlation ID, tenant/user, `tool_success`, execution status,
timestamp, and metadata:

- `event_type=agent.tool.execution`, `receipt_version=governed-tool.v1`
- tool name, registered version (or null if unknown)
- authenticated policy-decision ID, agent ID, step ID, unique call ID
- normalized error *type*, never raw provider/exception text
- optional SHA-256 digest of a small JSON-serializable response; never the
  response data or tool parameters
- `execution_scope=tool_runtime_acknowledgment`
- `independently_verified=false`

A result is considered acknowledged success only when the canonical tool
runtime reports literal `success=True`, no error and the exact issued
request ID. Unrecognized, contradictory or failed responses are recorded
as failures; exceptions are recorded by type and propagated without
the potentially secret exception message.

A missing policy identity, invalid tenant/user UUID, unauthorized tool,
plan-subject mismatch or insufficient budget is rejected *before* any
external side effect. If outcome persistence fails *after* a tool may have
acted, no success is returned and no automatic retry occurs. Operators and
the task creator must reconcile through the external system before a retry.

## Authenticated task read

`GET /api/tasks/{id}/tool-receipts?execution_id=<uuid>&limit=50`

1. Get current authenticated principal; get the creator-owned task from the
   canonical automation repository.
2. Require exact **current** attempt UUID. If it changed, respond 409.
3. Read only the backend-recorded `execution_request_id` from that task's
   latest receipt, never from a user-supplied run field. Older unlinked
   attempts return an empty set, without invented correlations.
4. `OutcomeStore.list_governed_tool_receipts_async` filters
   `tenant_id`, `user_id`, `trajectory_id`, source and event type in SQL.
   Existing tenant RLS remains in effect. Max 100 records per request.
5. Expose a sanitized receipt summary, never the full raw outcome payload,
   tool input, returned data or cross-user records. A database outage
   returns 503, not a fabricated empty history.

The Tasks UI displays this explicitly as an *acknowledgment*, with
on-demand loading, errors and stale-request fencing.

Historical MI-10 reviewed task events preserve the latest
`execution_request_id` link, but this slice's task endpoint intentionally
reads the current attempt only. A separate owner-authorized historical
receipt navigation must be added only when audit retention policy is
settled; do not invent task-to-run links.

## Verification

- `tests/agent_medusa/test_governed_tool_receipts.py`: authorization,
  cross-principal replay, strict tool-runtime success, sensitive data
  redaction, failure receipts, exception content redaction, storage outages
  and no blind retries.
- `tests/services/automation/test_task_tool_receipts.py`: owner-only
  exact-attempt task lookup and scoped history, missing-link behavior,
  stale attempts and honest API error codes.
- `tests/integration/test_live_automation_task_claims.py`: isolated
  PostgreSQL append and SQL/RLS-scoped reads for tenant, user and run.
- Automation Authority Gate, live PostgreSQL, Main Quality, Chat System
  Burn, security and frontend gates on the exact PR head.

No migration is required: MI-10 already added canonical
`outcome_records` authority and MI-08/09 already track task attempts.
No new worker, model selector, inference route, fallback engine, or audit
registry is introduced.

## What is *not* proven

- Whether an email was delivered/read or a payment settled.
- Whether a provider committed a change after its API returned success.
- Whether an outside file or resource still exists.
- Whether arbitrary LangGraph or plugin calls, not using Medusa ToolBridge,
  have the same receipt.
- Whether acceptance criteria semantically match a side effect.

Those require governed provider-specific reconciliation/verification
contracts built on this receipt and the authoritative external state.
Task `Success` still requires creator approval.
