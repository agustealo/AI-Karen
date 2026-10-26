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

1. Apply and verify migration 43 using the canonical Supabase PostgreSQL migration pipeline; ensure tenant/user RLS is effective for runtime transactions.
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

Both feature flags default **false**. Failure of admission while enabled results
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
- **Finality:** `completed`, `failed` and `cancelled` are terminal states
  enforced in SQL; one server lease can transition the row once. `RUN_FINISHED`
  may be projected only after the runtime's canonical completion and successful
  database terminal commit. A lost lease cannot produce a successful finish.
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
2. **CK-07C0:** Harden completion/cancellation races across persistence,
   tool side effects and worker lease transitions.
3. **CK-07D:** Governed, versioned presentation/execution receipt restoration,
   ordered replay cursor and live-stream continuation.
4. **CK-07E:** Real PostgreSQL, actual model, multiple workers and browser
   continuity proof; UI feature/voice/persona/draft/scroll parity.
5. Govern ledger retention/deletion and inactive-run reconciliation through
   existing privacy and audit policy before enabling the feature beyond tests.

## Proof entry points

```bash
python -m compileall src
pytest tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py tests/api_routes/test_chat_ag_ui_transport.py -q
cd src/ui_launchers/Karen-AI-Theme && pnpm exec vitest run tests/copilotkit-owned-run-stop.test.ts
ruff check src/ai_karen_engine/core/runtime/chat_run_lifecycle.py src/ai_karen_engine/persistence/repositories/chat_run_repository.py src/ai_karen_engine/api_routes/chat/runtime.py tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py
pytest tests/architecture/test_copilotkit_migration_wiring.py -q
```

These component tests use controlled repositories/streams. Their success
**cannot** substitute for live database migrations, RLS, multiworker tests,
provider stream cancellation or browser tests. Preserve PR #556 as draft and
leave the existing assistant-ui mounted until all migration gates pass.
