# CK-07A: Runtime-owned durable chat run foundation

**Status:** Opt-in engineering implementation, not consumer release. Source branch: PR #556.

## Canonical owners

- `ChatRuntime.execute_stream()` remains the only model/prompt/provider/persistence executor.
- `ConversationRuntimeGateway.require_owned_conversation()` proves tenant/user/thread ownership.
- `core/runtime/chat_run_lifecycle.py` admits a run and fences streamed terminal outcomes.
- `persistence/repositories/chat_run_repository.py` owns parameterized SQL and scope checks.
- `supabase/migrations/20261025020000_43_runtime_chat_run_ledger.sql` owns schema/RLS.
- `api_routes/chat/runtime.py` is only ingress and SSE event translation.
- `AGUIEventProjection` remains the single source of runtime-to-AG-UI event mapping.
- CopilotKit remains UI/transport only. Its `runId` is never an execution capability.

The ledger stores **no transcript, prompt, provider payload, tool arguments,
session state or SDK thread store**. No service is registered as a second
orchestrator and no legacy cancellation authority was imported.

## Operator activation (do not enable for consumer traffic yet)

1. Apply and verify migrations 43, 44, 45 and 46 in order through the canonical Supabase PostgreSQL migration pipeline; ensure tenant/user RLS is effective for runtime transactions.
2. Set `KARI_ENABLE_AG_UI_BRIDGE=true` only in a scoped integration environment.
3. Set `KARI_ENABLE_AG_UI_DURABLE_RUNS=true` there, never on an unverified installation.
4. The validated timing options are `KARI_CHAT_RUN_LEASE_SECONDS=120` (30–3600) and `KARI_CHAT_RUN_HEARTBEAT_SECONDS=10` (1 to a third of the lease).
5. Execute signed-in model → stream → PostgreSQL read-back, worker restart,
   concurrent duplicate-run, permission-revocation and fault-injection tests.
6. The CK-07B SDK route `POST /api/copilotkit/agent/default/stop/:threadId`
   requires the JSON body `{"runId":"..."}`; thread-only stop is denied.
   The canonical backend endpoint is
   `POST /api/chat/ag-ui/runs/:threadId/:runId/cancel`.
   Both are disabled whenever either AG-UI or durable runs is disabled.
7. Before enabling consumer stop, prove real multiworker cancellation and
   stop/completion races against live PostgreSQL and an authorized model.

8. After dedicated PostgreSQL validation, the strictly internal CK-07E0
   event journal can be trialed in an isolated environment by setting
   `KARI_ENABLE_AG_UI_EVENT_JOURNAL=true`; it remains **false** in shipped
   configs. This does not switch the consumer UI or authorize model resume.

All three AG-UI flags default **false**. Failure of admission while enabled results
in an explicit error before model execution, not a fallback that bypasses the
ledger. A reused scoped SDK transport ID produces 409; the same ID in another
tenant or user scope does not alias the old execution.

## Lifecycle truth

- **Admission:** Canonical conversation ownership and authenticated principal
  are rechecked before the SQL insert. PostgreSQL uniqueness combines tenant,
  user, conversation and SDK transport runId. An internal execution UUID and
  fencing token are always generated on the server.
- **Heartbeat:** CAS renewal matches execution UUID, tenant/user/conversation,
  fencing token, active state, non-expired lease and absent cancel intent. The
  worker renews while the provider is blocked, not only after tokens arrive.
- **Finality:** `completed`, `failed` and `cancelled` are terminal states.
  CK-07C0 now extends the EXISTING canonical `PostgresConversationRepository`
  completed-turn transaction: it locks the scoped run BEFORE the owned
  conversation, inserts both idempotent messages, and updates the SAME
  run row to `completed` in the SAME PostgreSQL transaction. Stop requests
  serialize on that exact row. There is no independent `completed` update
  in `SqlChatRunRepository.finish()`; that path explicitly rejects it.
  The runtime projects `RUN_FINISHED` only after it read-verifies the
  completed run and both canonical message IDs under tenant/user RLS.
  A lost lease or a failed insert/terminal update cannot produce a success.
- **Disconnection:** The stream's cancellation/closure requests a cancelled
  transition; there is no fake successful model answer.
- **Worker loss:** When an authenticated actor next admits a run, expired
  leases for that actor are marked `orphaned`. This does not yet implement
  automatic cross-worker cancellation or ownership takeover.
- **Stop request:** A second authenticated worker can atomically request
  cancellation with a row lock scoped to tenant, user, conversation and exact
  run ID. Duplicate requests preserve the initial stop timestamp. The owning
  worker periodically checks the durable intent, even on fast streaming or
  blocked provider I/O, unwinds its upstream generator and performs fenced
  `cancelled` finalization. Completed/expired run outcomes are never reported
  as successful cancellations. Tenant/user ownership is checked again through
  the canonical ConversationRuntimeGateway at the point of cancellation.
- **Replay:** Existing CK-06 completed plaintext history reconnect remains
  unchanged. A durable execution record is not an event cursor, and does not
  restore in-progress tokens or rich presentation payloads.

## Explicitly incomplete (P0)

1. **CK-07B:** The authorized SDK stop adapter, PostgreSQL cancel intent,
   runtime worker observation and model-task unwind are now implemented behind
   the disabled-by-default feature. Cross-worker behavior is covered only by
   component/unit tests, NOT verified against actual multiple worker processes
   and live PostgreSQL. A 202 stop response is `cancelling` only; a worker
   terminal record is required to confirm `cancelled`. SDK clients that omit
   `runId` receive 422 rather than cancelling an arbitrary thread run.
   Operator activation remains blocked pending E2E proof.
2. **CK-07C0:** Atomic transcript + completed-run finality is implemented
   using the canonical PostgreSQL conversation repository with one transaction,
   owner checks, fencing, and read-after-write verification. Durable-run memory
   writes now occur AFTER successful transcript/terminal commit. Unit rollback
   and isolated PostgreSQL stop-versus-commit race tests are checked in.
   **Still unproven**: live dedicated-DB CI execution, post-commit process
   crash/restart reconciliation and atomicity of external tool side effects,
   which are governed separately by their canonical services.
3. **CK-07D:** Authenticated completed-history replay now has a backend
   owned projection under `GET /api/chat/ag-ui/threads/{threadId}/history`,
   strictly enabled only by the canonical bridge + durable-run feature flags.
   Forward-only migration 44 binds the exact user and assistant message IDs
   to a completed run inside the existing canonical transcript transaction.
   Migration 45 separately stores SHA-256 of the exact saved assistant message
   identity, content and complete metadata inside that transaction. Existing
   completed runs without saved fingerprints remain non-replayable; migration
   does not backfill inferred proof.
   `SqlChatRunRepository.completed_replay_attestations()` verifies both
   messages, request identity, tenant/user ownership and completed run state.
   The read-only `owned_history_projection.py` recomputes the canonical
   assistant digest and fails replay on even a post-commit content, receipt,
   or verified-presentation metadata change; a matching message ID or claimed
   runtime `source` is NEVER sufficient attestation.
   `owned_history_projection.py` reuses AGUIEventProjection and
   validate_presentation; it publishes only the original saved text,
   supported versioned presentation and bounded execution/integrity receipts,
   never raw SQL metadata, tool arguments or unapproved client actions.
   CopilotKit capability discovery selects either the existing CK-06 plaintext
   path or the new governed projection; reconnect emits one verified
   MESSAGES_SNAPSHOT, then associated CUSTOM events and a synthetic
   replay-only RUN_FINISHED. Nothing invokes a provider during replay.
   **Still missing:** live provider reattachment,
   partial-run continuation after worker crash and visual browser parity.
   The complete replay rejects unverified/legacy rich content instead of
   silently dropping it.
4. **CK-07E0:** An explicitly disabled-by-default runtime event journal now
   persists only **observed AGUIEventProjection output** with per-run monotonic
   `event_seq` assigned under the canonical run-row lock. Migration 46 adds
   `public.runtime_chat_run_events` with a compound tenant/user/conversation
   foreign key to `runtime_chat_runs`, forced RLS, allowed event types,
   a maximum of 2,048 events per execution and 32 KiB per event. The backend
   also enforces an 8 MiB total per run. `KARI_ENABLE_AG_UI_EVENT_JOURNAL=true`
   requires both existing AG-UI flags, migration 46, and isolated proof.
   The stream records each projected event BEFORE sending its SSE data and
   publishes the committed sequence as an SSE `id:`. Journal startup failures
   do not launch a model. Completed transcript truth remains owned by the
   existing atomic conversation transaction; only canonical final-envelope
   events may be appended after `completed`. The event log itself never
   authorizes an `RUN_FINISHED` or resumed execution.

   The authenticated read-only backend endpoint
   `GET /api/chat/ag-ui/runs/{threadId}/{runId}/events?after=0&limit=50`
   rechecks canonical conversation ownership, matches owner/tenant/run in SQL,
   pages only committed projections and reports expired running leases as
   `interrupted`, with `terminalConfirmed=false` and
   `continuationAvailable=false`. Missing journal terminals are not invented
   from a model label or client state. This endpoint is **not** an SDK
   consumer connection route. The existing CopilotKit route remains closed
   to ungoverned `/threads/:id/events` requests.

   **Still missing:** real provider-process reattachment (which may never be
   safe for all engines), governed frontend cursor consumption/acknowledgment,
   retention/deletion coupling, actual PostgreSQL cross-process proof,
   and UI feature/voice/persona/draft/scroll parity.
5. **CK-07E1 (partial):** Canonical conversation deletion now requires an
   authenticated owner and performs run-ledger deletion before deleting the
   conversation in the SAME PostgreSQL transaction. Journal rows cascade
   from their run records by FK; a failed journal/run deletion rolls back
   transcript deletion instead of leaving recoverable private output. The
   repository detects pre-CK-07 databases using `to_regclass` rather than
   pretending an absent ledger was erased. Unit rollback and tenant/owner
   contract tests are checked in; **the dedicated real-PostgreSQL explicit
   deletion assertion is still outstanding**.

   The opt-in CopilotKit gateway also exposes a narrow non-SDK-standard
   `GET /api/copilotkit/threads/{threadId}/runs/{runId}/events?after=0&limit=50`
   **JSON observation endpoint** only if the canonical
   `observed_event_journal` capability is true. It repeats canonical auth,
   verifies tenant and user identity, bounds the bytes and events, enforces
   contiguous event cursors, and refuses unsupported tool/action event
   types rather than dropping private/complex state. This endpoint **does
   not** reconnect or resume a live model through `agent.connect()`; partial
   observed content remains labeled interrupted without a synthetic
   `RUN_FINISHED`. Consumer adoption is still disabled.

   Automatic retention schedules and erasure propagation to any separately
   governed backup/analytics destinations must follow the existing
   NeuroVault privacy/retention authority. Neither a hardcoded TTL nor an
   unaudited background deletion loop is introduced here. Prove the
   complete retention and legal-hold policy before enabling consumers.

## Proof entry points

```bash
python -m compileall src
pytest tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py tests/api_routes/test_chat_run_atomic_transcript.py tests/api_routes/test_chat_ag_ui_transport.py tests/api_routes/test_chat_run_event_journal.py tests/api_routes/test_owned_history_projection.py tests/api_routes/test_ag_ui_governed_history.py -q
cd src/ui_launchers/Karen-AI-Theme && pnpm exec vitest run tests/copilotkit-owned-run-stop.test.ts tests/copilotkit-owned-thread-history.test.ts tests/copilotkit-owned-thread-connect.test.ts tests/copilotkit-governed-history.test.ts
ruff check src/ai_karen_engine/core/runtime/chat_run_lifecycle.py src/ai_karen_engine/persistence/repositories/chat_run_repository.py src/ai_karen_engine/api_routes/chat/runtime.py tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py
pytest tests/architecture/test_copilotkit_migration_wiring.py -q
```

A dedicated non-production PostgreSQL concurrency test is also checked in:
`tests/integration/test_runtime_chat_stop_concurrency_postgres.py`. It exercises
the real migration, PostgreSQL row locking, tenant/user scoped cancellation,
duplicate stop, stop-versus-completion race, lease expiry and fenced finality.
The test applies migrations 43, 44, 45 and 46 and verifies atomic saved message
IDs against the authenticated completed-run replay attestation, plus
principal-scoped event cursors across simulated independent worker instances. It
**requires** `CHAT_RUN_TEST_DATABASE_URL` pointing to a disposable
database whose name is exactly `karen_chat_run_test`. It skips rather than
claiming success when that resource is absent. It destroys test tables only in
that dedicated database. Example execution after provisioning the isolated DB:

```bash
pytest tests/integration/test_runtime_chat_stop_concurrency_postgres.py -q
```

These component tests and the dedicated DB test still **cannot** substitute
for an actual provider abort, a multi-process deployment, SDK browser stop
flow or read-after-write presentation continuity. Preserve PR #556 as draft
and leave the existing assistant-ui mounted until all migration gates pass.
