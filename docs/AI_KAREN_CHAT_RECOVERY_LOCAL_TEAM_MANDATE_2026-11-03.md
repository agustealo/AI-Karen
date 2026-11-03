# AI-Karen | KCHAT-P0 Recovery Mandate

**Revision:** 1.0  
**Issued:** 2026-11-03  
**Audience:** Local engineering team, backend/runtime owners, database owner, frontend/CopilotKit owner, CI/release owner  
**Repository:** `agustealo/AI-Karen`  
**Audited main:** `3914caa25d6315927b4e621910a402d6b93b1b7f`  
**Mission:** Restore the actual end-to-end consumer chat response path and establish release-grade, reproducible proof. Do not substitute green contract tests for authenticated model-backed behavior.

## Command decision

**P0 is the first complete model-backed chat turn**: authenticated user submits text, canonical draft and conversation permissions are honored, the request enters CopilotKit AG-UI, ChatRuntime performs a real model execution, nonempty assistant text reaches the browser, exact execution provenance is persisted with the turn, and the identical response survives reload. The system remains **not consumer-ready** until this passes.

This is a **recovery and consolidation** task. No new orchestration stack, duplicate conversation database, alternate API endpoint, fake response text, front-end provider selector, RLS bypass, or blanket admin grants. Start with observation, reproduce the first failing boundary, repair only its authoritative owner, and prove the complete path afterward.

### What is known vs. what must be proved

| Surface | Evidence as of the audited head | Classification |
| --- | --- | --- |
| Local login | User logs show `POST /api/auth/login` HTTP 200 | Observed success for authentication only |
| JWT role/permission collision | PR #624 merged into main at `3914caa` | Source defect repaired; local running tokens/process not verified updated |
| CI | Main Quality Gate, Auth Security, Database Baseline, First-Boot Smoke, Automation Authority passed on audited main | Green repository/isolated-environment evidence |
| Local composer draft | Earlier live Docker incident documented GET draft HTTP 503; known prerequisite for sending | Suspected active local blocker; needs current logs and DB inspection |
| AG-UI availability | `enable_ag_ui_bridge` defaults to `false`; SDK path rejects disabled bridge | Confirmed gate, effective Docker value unknown |
| Local model execution | Not observed from supplied logs | Not proved |
| Real browser rendering/reload | No end-to-end evidence from current local installation | Not proved |
| Vercel production | READY frontend at audited main; runtime errors report `canonical_backend_configuration_invalid`, `target_status: missing`, on auth proxy | Confirmed separate deployed backend-target issue; not proof of local Docker fault |
| Production real chat | No successful authenticated execution verified | Blocked |

**Explicit distinction:** A passed CI first-boot smoke provisions a fresh isolated PostgreSQL database and conditionally runs model tests only with an explicit model target. It does not prove the migrated state of a preexisting Supabase instance, a local browser, or a persistent deployment.

---

## 0. Non-negotiable architecture and security invariants

1. **Thin ingress:** FastAPI and Next.js validate transport, resolve authenticated principals and tenant context, delegate, and translate sanitized errors. Neither selects providers, builds prompts, writes imitation answers, executes plugins, or implements retry/fallback decisions.
2. **One chat authority:** `src/ai_karen_engine/core/runtime/chat_runtime.py` owns chat execution. CORTEX decides. LangGraph is used only for workflows requiring graph orchestration. Do not create a second agent runtime.
3. **One conversation/draft authority:** Canonical `ConversationRuntimeGateway` and `PostgresConversationRepository`; migrations remain under `supabase/migrations`. Never invent a second localStorage or Supabase duplicate transcript.
4. **One provider registry/policy:** Backend owns requested/actual model eligibility and ordered fallback. A UI selection is a request, not an execution receipt.
5. **No cross-principal state:** Enforce tenant, user, session, conversation and persona scope in backend. Ownership failures may map to 404; actual storage outages must remain 503 and visible.
6. **No fake success:** No synthetic streamed text, saved-message acknowledgments, stale optimistic status, fabricated model attribution, or empty-success terminal events.
7. **Privacy:** No access tokens, cookies, full request bodies, drafts, personal messages, SQL strings or stack traces in shared logs/screenshots. Redact and classify failures. Keep exact per-run correlation IDs.
8. **No unsafe emergency changes:** No dropping/recreating tables, disabling RLS, bypassing `ChatRuntime`, relaxing authorization, enabling public Copilot, or setting production env secrets in committed files.
9. **Consolidation before new files:** Search for existing owner and tests. Reuse. New diagnostic/test files are acceptable; duplicate orchestration/services are not.
10. **Every PR has proof:** Full tests and exact-head acceptance evidence, impacted files, rollback risk, and an explicit statement of still-unverified behavior.

## 1. Canonical request path and failure localization

```text
Browser: KarenCopilotConsumerChat
  → KarenCopilotChat / CopilotKitProvider
  → KarenCopilotHistoryGate verifies owned conversation + replay
  → useKarenPersistedDraft reads/writes durable draft with CAS
  → KarenCopilotControlledChat blocks send until verified/synced
  → clearBeforeSubmit confirms revisioned draft clearance
  → agent.addMessage + copilotkit.runAgent
  → Next.js /api/copilotkit/agent/default/run
  → verifies /api/auth/me + /api/chat/ag-ui/capabilities
  → CopilotKit HttpAgent → FastAPI /api/chat/ag-ui
  → bounded request parsing + principal/tenant/thread verification
  → optional durable run admission/journal
  → ChatRuntime.execute_stream
  → CORTEX, prompt/context, provider selection/inference, persistence
  → AGUIEventProjection (RUN_STARTED, TEXT_*, RUN_FINISHED|RUN_ERROR)
  → browser renders same canonical assistant message
  → authenticated history reread and reload restores same persisted turn
```

**Caution:** `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts` is an additional frontend proxy. The consumer's main SDK handler at `src/app/api/copilotkit/[[...slug]]/route.ts` creates an `HttpAgent` against the canonical FastAPI origin. Fixing the standalone `/api/chat/ag-ui` proxy does not automatically repair the SDK path. Audit both consumers, do not delete either until a complete reference/contract scan proves redundancy.

### Deterministic failure tree

| First broken boundary | User-visible effect | Evidence to capture (sanitized) | Owner |
| --- | --- | --- | --- |
| `/ready` or web `/api/health` fails | Services boot but are not ready | exact response status, ready components, deployment SHA | Runtime/deployment |
| Auth/tenant resolution fails | user appears logged in but requests are denied | `/api/auth/me` status, sanitized principal context | Auth |
| History ownership read fails | chat cannot mount or switches fail | owned thread read status, scope-safe reason | Conversation gateway |
| Draft GET/PUT returns 404/409/503 | Send is blocked before any model call | HTTP status, SQLSTATE `failure_class`, revision outcome | DB/repository |
| AG-UI capability says disabled | SDK refuses to start | boolean feature flags from running API | Runtime config |
| SDK `/run` returns 401/404/415/422/503 | No runtime execution | route/status, bounded shape validation, sanitized error | Next.js/AG-UI ingress |
| AG-UI admits, no model activity | spinner or terminal error | correlation ID, CORTEX/routing policy/provider attempt | ChatRuntime/model runtime |
| Model emits but SSE fails | partial/empty assistant | first/last event, interruption code, no fake `RUN_FINISHED` | AG-UI projection/proxy |
| UI receives terminal but no text | blank rendered response | SDK messages vs canonical event IDs vs UI | Consumer UI |
| UI renders but reload loses answer | transient false completion | canonical committed user/assistant pair, history replay | Conversation persistence |
| Only Vercel fails | frontend READY but auth/chat proxy 503/502 | `KAREN_BACKEND_URL` target classification and backend readiness | Deployment |

**Diagnostic precedence:** Use the *first* failing stage; a later error is usually fallout. A login 200 does **not** validate chat readiness.

---

## 2. Task KCHAT-P0-01: Source, deployment and running configuration attestation

**Objective:** Eliminate stale source, stale containers, stale tokens, disabled feature flags and environment drift as ambiguous explanations.

**Do:**
- Capture `git status --short`, current commit and `origin/main` SHA before touching local work. Preserve uncommitted changes. Do not force-reset.
- On a reviewed repair branch from audited main, build/recreate only the necessary local API/web services after preserving config and database state. Do not assume a file bind mount reloads imported modules in an already-running Python process.
- Verify actual container image revision if labeled, the running Python module location, and effective flags returned by `get_runtime_settings()`. Compare `.env`, compose interpolation, and overridden runtime settings without printing values of secret-bearing keys.
- Confirm root Docker Compose's API DB DSN targets the intended local Supabase PostgreSQL. Root development compose has explicit values that can override `.env`. Do not edit production overlay as a local workaround.
- Confirm `KARI_ENABLE_AG_UI_BRIDGE` for the running API. Its default is false; treat capability status as backend truth. Activate only on an environment with all prerequisites and protected test scope.
- Reauthenticate after PR #624. Tokens issued by the old process can continue to contain role names under `permissions` until replaced. No unsigned JWT workarounds.

**Reuse:** `src/ai_karen_engine/config/runtime.py`, `docker-compose.yml`, `deploy/compose/docker-compose.prod.yml`, canonical `/ready`, `src/ai_karen_engine/services/auth/auth_service.py`, existing Auth Security suite.

**Proof:** Local API `/ready` is 200 with configuration/database ready; web `/api/health` is 200 with `backend_ready: true`; login and `/api/auth/me` succeed; new JWT is issued by fixed service; RBAC warnings do not reappear; the AG-UI capabilities endpoint reflects the intended effective flag. Do not claim model health from `/ready`.

**Stop conditions:** Unknown deployed revision, missing DB, unreviewed configuration, auth bypass, or tenant scope missing. Resolve before advancing.

## 3. Task KCHAT-P0-02: Repair existing PostgreSQL schema/role drift without bypass

**Objective:** Make the *currently used* database satisfy canonical migration 47 and authenticated draft access.

**Own files:**
- `supabase/migrations/20261026010000_47_conversation_composer_drafts.sql`
- `src/ai_karen_engine/services/database/repositories/postgres_conversation_repository.py`
- `src/ai_karen_engine/core/runtime/conversation_runtime_gateway.py`
- `src/ai_karen_engine/api_routes/chat/conversation.py`

**Do:**
1. Run the accompanying `karen_chat_p0_readonly.py` from the real API container. It uses `get_postgres_engine`, a read-only transaction, reports only sanitized status/SQLSTATE, and never modifies tables.
2. Inspect migration tracking for this specific local Supabase database. Do not infer migration completion from the repository file existing.
3. Confirm `public.conversation_composer_drafts` exists with: conversation FK (ON DELETE CASCADE), tenant/user FK, `draft_text`, `revision BIGINT`, primary key, enabled **and forced** RLS, canonical owner policy, and grants for the actual application DB role.
4. Confirm the `conversations`, `auth_users`, `tenants` relationships are valid in the *same database*.
5. Confirm read and write repository operations set `app.current_tenant_id` and `app.current_user_id` transaction-locally and perform owner-bound CAS. Check effective SQL role; superuser/BYPASSRLS in local dev is not evidence of production RLS correctness.
6. Map failures via `failure_class` already added by PR #621: `draft_schema_missing`, `draft_permission_denied`, `draft_schema_incompatible`, `database_connection_unavailable`, `draft_integrity_failure`, or `database_failure_unclassified`. Some PostgreSQL drivers wrap `.orig` more than once; extend safe classification only if observed and supported by tests.
7. If migration 47 is absent, apply **only** the canonical unapplied migrations through the supported local migration workflow after a backup and dry review. Do not paste `CREATE TABLE` manually into the running database and do not replay a non-idempotent migration blindly.
8. Ensure tenant isolation/owner filtering still returns 404 for unauthorized/missing conversations; do not translate infrastructure failures to 404 or empty drafts.
9. Prove GET returns `{text: "", revision: 0}` only for an existing **owned** empty draft, PUT increments revision atomically, stale CAS returns 409, conflict cannot overwrite newer text, clear increments revision, and outage returns 503 without claiming success.

**Security proof:** Wrong tenant, wrong user, missing conversation, stale revision, RLS refusal, non-superuser DB role, large UTF-8 input and simultaneous edits.

**Tests:** `tests/api_routes/test_composer_drafts.py`, `tests/integration/test_chat_transcript_postgres_isolation.py`, targeted repository tests and a **real scoped DB integration** using a disposable tenant/conversation with cleanup. Do not use a mock for the final readiness claim.

**Acceptance:** Both draft GET/PUT and revisioned clearance succeed in a real authenticated browser against the existing local DB, and no unexplained 503 is present. Document migration version, verified schema and scoped table permissions without sharing credentials.

## 4. Task KCHAT-P0-03: Composer and history gate recovery

**Objective:** Restore a usable send experience without corrupting unsent user text or weakening persistence truth.

**Own files:**
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotControlledChat.tsx`
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/useKarenPersistedDraft.ts`
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotHistoryGate.tsx`
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotConsumerChat.tsx`

**Do:**
- Confirm mount ordering: verified history precedes agent, verified draft precedes send.
- Trace the submit gate: `draftStatus === "ready"`, `draftSynced === true`, matching thread and not running; `clearBeforeSubmit` must succeed before `agent.addMessage` and `runAgent`.
- **Do not delete this gate** to make chat appear operational. Resolve the underlying DB/transport fault. Preserve user text, conflict recovery, safe retry, and failure feedback.
- Distinguish initial loading, permission denied, unsaved draft, 409 conflict, unverified history, running model, interrupted stream, and completed answer in the UI. Avoid an indefinite generic “Saving draft…” if storage has already failed.
- Enforce no duplicate sends under rapid Enter, double-click, refresh, network retry or concurrent tab; never execute after stale thread selection.
- Keep keyboard, mobile, accessible alert semantics and voice draft reuse. The right answer is a truthful recoverable state, not fabricated text.

**Proof:** Save succeeds, send allowed only after revision receipt, failure leaves draft recoverable, successful send clears exactly once, browser recovers after transient 503, no foreign history, no duplicate assistant output. Reuse existing `karen-copilotkit-persisted-draft.test.tsx`, `karen-copilotkit-controlled-chat.test.tsx`, `karen-copilotkit-history-gate.test.tsx` and corresponding e2e scenarios.

## 5. Task KCHAT-P0-04: Prove actual SDK-to-runtime AG-UI transport

**Objective:** Know precisely where the real consumer request travels, with no guessing about proxy patches.

**Own files:**
- `src/ui_launchers/Karen-AI-Theme/src/app/api/copilotkit/[[...slug]]/route.ts`
- `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts`
- `src/ai_karen_engine/api_routes/chat/runtime.py`
- `src/ai_karen_engine/core/runtime/ag_ui_event_projection.py`

**Do:**
- Capture sanitized browser Network request method/status for `/api/copilotkit/agent/default/run`, Next.js internal `/api/auth/me` verification and `/api/chat/ag-ui/capabilities`.
- Confirm `HttpAgent` reaches canonical FastAPI `/api/chat/ag-ui` with authenticated headers and preserved correlation ID. Preserve manual redirects and disable retry of mutation POSTs.
- Verify the bounded parser from PR #623 accepts valid JSON with missing/text/plain/application/json media types while rejecting malformed/oversized bodies and client-supplied tools/state/context; accept no unreviewed privilege-bearing forwarded props.
- Verify AG-UI bridge flag is enabled only after DB and run-admission prerequisites are satisfied. If durable runs are selected, verify migrations 43–46, feature dependencies, ownership, event journal, lease and cancellation semantics separately.
- Trace and document whether the standalone Next `/api/chat/ag-ui` route is active for any remaining caller. Remove redundant transport only with full caller audit and passing compatibility tests.
- Confirm upstream error status and code reach the SDK/consumer as an actionable error, not a permanent spinner.

**Proof:** One protected send yields exactly one backend `chat_stream_started` with matching correlation/conversation identity, one observed `RUN_STARTED`, one or more text deltas from ChatRuntime, and exactly one verified terminal `RUN_FINISHED` or `RUN_ERROR`. Any upstream dropped connection becomes an explicit interruption, never a successful finish.

**Tests:** `tests/api_routes/test_chat_ag_ui_transport.py`, `tests/api_routes/test_chat_run_lifecycle.py`, `tests/api_routes/test_chat_run_event_journal.py`, `src/ui_launchers/Karen-AI-Theme/tests/copilotkit-runtime-sdk-run.test.ts` and `tests/api-stream-incomplete.test.ts`.

## 6. Task KCHAT-P0-05: Restore **real** provider execution with truthful receipts

**Objective:** A model produces the assistant text, with source-of-truth attribution, safe fallback and bounded latency.

**Own files:**
- `src/ai_karen_engine/core/runtime/chat_runtime.py`
- `src/ai_karen_engine/core/runtime/composition.py`
- `src/ai_karen_engine/core/runtime/provider_runtime.py`
- `src/ai_karen_engine/core/model_runtime/provider_registry_service.py`
- `src/ai_karen_engine/core/model_runtime/provider_execution.py`
- `src/ai_karen_engine/core/model_runtime/routing/` (inspect existing members before editing)

**Do:**
- Identify one installed and healthy local provider/model from backend registry and runtime health. Do not assume a model exists from configuration or frontend selection.
- Trace CORTEX decision, prompt/context assembly, memory reads, provider eligibility, invocation and emitted chunks through one correlation ID. Instrument the existing observability emitter; do not add print-debug logs containing prompts.
- Keep model fallback order registry/config-driven, honoring requested model eligibility, local-first policy, available engines, external opt-in and security gates.
- Require `requested_provider`, `requested_model` (where present), `actual_provider`, `actual_model`, `runtime_engine`, `response_source`, `fallback_level`, `degraded_mode`, `degradation_reason`, `correlation_id` and latency evidence consistent with the **actual** executor.
- Enforce no reported success if the provider returns blank/whitespace-only content, raises before text, raises after partial text, times out or emits no canonical completion. Never switch providers after partial text is already exposed.
- Preserve assistant streaming, memory formation rules and completed-turn atomic persistence. Persistence failure cannot be relabeled model success.
- Reject fabricated emergency assistant responses. An unavailable backend is an explicit unavailable state.

**Proof:** Real model returns nonempty original answer to a unique test prompt, with a traceable provider attempt and actual model receipt. Two turns in one scoped conversation demonstrate continuity; invalid provider or mid-stream failure becomes honest error/degraded metadata. Test with genuine Ollama/LM Studio/other configured provider, not a dummy ChatRuntime object.

**Tests:** `scripts/beta_live_model_smoke.py` for provider-only diagnostics (never sufficient by itself), `tests/core/runtime/test_chat_runtime_stream_contract.py`, `tests/integration/test_fallback_chain.py`, `tests/integration/test_chat_transcript_continuity.py`, and `tests/beta/test_real_model_wiring.py`.

## 7. Task KCHAT-P0-06: AG-UI terminal integrity and transcript durability

**Objective:** One durable user/assistant turn, never a phantom response.

**Do:**
- Compare actual runtime chunk order against AG-UI event projection and Next.js streaming framing.
- On successful generation, require `RUN_STARTED`, `TEXT_MESSAGE_START`, `TEXT_MESSAGE_CONTENT`, `TEXT_MESSAGE_END`, then **one** `RUN_FINISHED`. `RUN_FINISHED` may only follow verified ChatRuntime completion.
- On exception, disconnect, cancelled run, lease loss, event journal failure or incomplete stream, emit/record an honest `RUN_ERROR`. No fake completion. No continuation with a different provider after content has streamed.
- Ensure journal write-through semantics align with the persisted completed turn, run ID and tenant; no cross-tenant or cross-thread replay.
- Confirm `persist_completed_turn` is the canonical writer for complete user/assistant pairs. Ensure duplicate retries cannot create a second user or assistant row for the same request identity.
- Restore the complete server-backed response, verification receipts and supported rich presentations after refresh. Do not silently discard unsupported rich content or pass off rehydrated text as a fresh model run.
- Verify Stop differentiates cancellation requested, worker termination confirmed, and already-finished executions.

**Proof:** Immediate render and reload display the same exact assistant text, one turn pair and matching `karen.execution_receipt.v1`. Repeated refresh, multiple tabs, user switch, corrupt event, halfway disconnect and interrupted provider fail safely.

## 8. Task KCHAT-P0-07: Production proxy connectivity (separate track)

**Objective:** Remove the confirmed production `KAREN_BACKEND_URL` missing-target failure without treating Vercel READY as API ready.

**Do:**
- Inspect the `ai-karen` Vercel project in the correct team/target environment. Confirm server-only `KAREN_BACKEND_URL` is actually available and resolves to the separately deployed FastAPI origin. Do **not** echo its value, insert localhost/Docker addresses, embed authentication data in URLs, or expose a backend via insecure HTTP.
- Confirm the API is independently deployed, stable, accessible from Vercel's network, TLS-valid and secured. `/ready` must report configuration and database ready.
- Build candidate deployment from exact reviewed SHA. `GET /api/deployment-revision` must match it; `GET /api/health` must return `{"status":"ok","backend_ready":true}` with no-store and no redirect.
- Only after connectivity and security proof, run the existing protected Playwright consumer acceptance. Do not issue real credentials to a preview known to have no backend.
- Keep this track separate from local Compose repairs. Configuration on Vercel does not repair the existing local PostgreSQL instance.

**Reuse:** `docs/operations/vercel-backend-connectivity.md`, `scripts/ci/verify_backend_target.py`, `scripts/ci/verify_deployment_revision.py`, `.github/workflows/karen-history-browser-acceptance.yml`. Promotion/release requires an explicit approved release decision, not this audit alone.

## 9. Task KCHAT-P0-08: Consolidate tests into a single **truthful** release gate

**Objective:** Preserve unit coverage while adding real authenticated execution evidence at the exact shipped SHA.

**Existing, do not duplicate:**
- `src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts` is a real-model consumer path test: requires deployment revision, backend health, owned conversation, saved draft, assistant persistence, execution receipt, immediate rendering and reload.
- `src/ui_launchers/Karen-AI-Theme/e2e/karen-copilotkit-native-acceptance.spec.ts` tests the native controlled view, draft CAS, no auto-run and other governed behaviors.
- `.github/workflows/karen-history-browser-acceptance.yml` supports `copilotkit-consumer` through protected workflow dispatch.
- `.github/workflows/chat-system-burn.yml` checks runtime and PostgreSQL contracts.
- `.github/workflows/production-first-boot-smoke.yml` checks a fresh isolated deploy, with optional model execution.

**Do:**
1. Ensure the release path invokes all existing gates at the exact reviewed head, not a stale success from another SHA.
2. Confirm the browser acceptance *actually executes*, not `skip`, and its assertions observe the real app on an approved isolated environment.
3. Add missing coverage only: DB migration drift detection on existing state, effective AG-UI flag, disable-on-outage UI, end-to-end provider attempt trace, uninterrupted and interrupted streams, exact attribution and no-duplicate sends.
4. Record deploy image and web/server revision. A HEAD changed during acceptance invalidates the final claim.
5. Block consumer release if UI displays a success without saved server truth, or if secrets/model output are leaked to logs/artifacts.
6. Don't make packaging/distribution a prerequisite before the functional acceptance is green. Distribution build is for explicitly approved release.

### Non-negotiable acceptance matrix

| Scenario | Required outcome |
| --- | --- |
| New authenticated chat | one real assistant reply, rendered immediately and saved |
| Two-turn follow-up | second reply uses authorized prior context, no cross-chat leakage |
| Refresh/reopen | same user and assistant text, stable IDs and verified receipt |
| Draft outage | no model send, unsent content preserved, clear actionable recovery |
| Draft conflict | 409, no overwrite, revision-respecting recovery |
| Wrong owner/tenant | 404/deny without data leakage |
| AG-UI disabled | explicit capability error, zero fake model calls |
| Empty/whitespace-only model | no successful assistant terminal |
| Mid-stream failure | `RUN_ERROR`, no fake success/fallback text splice |
| Model fallback | actual executor and fallback reason truthfully attributable |
| Stop/cancel | requested status distinct from confirmed cancellation |
| Rapid double submit | no duplicate provider execution or duplicate transcript rows |
| User/conversation switch | no wrong-thread completion, draft, persona or memory leakage |
| Vercel backend unreachable | hard readiness failure, not a READY-based false pass |
| CSS chunk and UI | no CopilotKit web-inspector unexpected import/chunk error |
| Mobile/keyboard/accessibility | composer and failure recovery usable, alerts announced |

## 10. Task KCHAT-P0-09: Observability and diagnosis contracts

**Objective:** A developer can identify the precise failing stage from a correlation ID in one pass.

**Use existing structured emitters and logs.** Record stage transitions, timestamps, outcome and safe reason codes for: authenticated ingress, conversation verification, draft read/write/CAS, feature eligibility, AG-UI admission, CORTEX decision, prompt/context assembly, provider selection, provider attempt/result, SSE start/text/terminal, completed-turn persistence, history projection, and final browser acknowledgment where available.

**Required safe fields:** `request_id`, `correlation_id`, scoped `session_id`, `conversation_id`, `tenant_id`, `user_id` (in secured logs only), `intent`, `provider_requested`, `model_requested`, `provider_actual`, `model_actual`, `runtime_engine`, `fallback_level`, `degraded_mode`, `response_source`, `memory_recall_count`, `latency_ms`, `status`, `error_code`, and owner/stage. All attributed to trusted backend sources, never UI guesses.

**Forbidden:** plaintext prompt/draft, passwords, bearer token, cookies, SQL statements, vector memory contents, unbounded exception messages, automatic retries of mutating chat POSTs.

**Failure taxonomy:** `AUTH_CONTEXT_UNAVAILABLE`, `CONVERSATION_NOT_OWNED`, `DRAFT_SCHEMA_UNAVAILABLE`, `DRAFT_RLS_DENIED`, `DRAFT_CONFLICT`, `AGUI_DISABLED`, `AGUI_INPUT_INVALID`, `RUN_ADMISSION_UNAVAILABLE`, `PROVIDER_UNAVAILABLE`, `MODEL_EMPTY_RESPONSE`, `STREAM_INTERRUPTED`, `TERMINAL_UNVERIFIED`, `PERSISTENCE_FAILED`, `REPLAY_UNAVAILABLE`. Map new codes to existing canonical error types rather than introducing an independent taxonomy if equivalents already exist.

## 11. Task KCHAT-P1-10: Secondary defect intake without losing the P0 target

During the recovery pass, capture every additional observed issue with severity, first failing boundary, correlation ID, reproduction, current source owner, existing implementation, affected tests, and proof status. Review rate limiting on voice/capability requests, stale CopilotKit chunks/CSS, persona preference revision/migrations, model settings availability, loading/stop race conditions, and presentation/history parity only where logs or browser traces show a reproducible fault.

Do not bundle unrelated UI redesigns or speculative architectural refactors into the P0 repair PR. Anything not preventing a real chat turn or compromising isolation is a separate P1/P2 item.

---

## 12. Local operator execution runbook

**Safety:** Start read-only. Do not paste `.env` values, token payloads, passwords or user chat text into shared tickets. Use a sanitized disposable account/conversation for mutation tests. Review working tree before changing branches.

### A. Verify source and running stack

```bash
set -euo pipefail
git status --short
git rev-parse HEAD
git fetch origin main
git rev-parse origin/main

docker compose config --services
docker compose ps

curl --silent --show-error --max-time 10 --output /dev/null --write-out 'api /ready HTTP %{http_code}\n' http://localhost:8000/ready
curl --silent --show-error --max-time 10 --output /dev/null --write-out 'web /api/health HTTP %{http_code}\n' http://localhost:8010/api/health

docker compose exec -T api python -c '
from ai_karen_engine.config.runtime import get_runtime_settings
f = get_runtime_settings().features
print("AG-UI bridge:", f.enable_ag_ui_bridge)
print("AG-UI durable runs:", f.enable_ag_ui_durable_runs)
print("AG-UI event journal:", f.enable_ag_ui_event_journal)
print("Streaming:", f.enable_streaming)
'
```

If this fails, **record actual failure status** instead of bypassing it. Before restarting containers, preserve current changes and know what build/revision each one runs.

### B. Run canonical database prereq check

Copy the accompanying full `karen_chat_p0_readonly.py` into `scripts/diagnostics/chat_p0_readonly.py` on the local checked-out branch, then run:

```bash
docker compose exec -T api python scripts/diagnostics/chat_p0_readonly.py --pretty
```

This is read-only and limited. It verifies current database connectivity, expected tables, draft revision type, FK count, RLS flags, owner policy, role privileges and effective runtime flags. It does **not** write a test draft, verify current user permissions, send a model prompt or certify the UI. Treat a superuser DB role as a security warning that requires least-privilege verification for release.

### C. Inspect sanitized failure indicators

```bash
docker compose logs --since=20m api web 2>&1 \
  | grep -E 'get_composer_draft failed|put_composer_draft failed|failure_class|chat_stream_started|AG-UI|ChatRuntime.execute failed|RUN_ERROR| 401 | 404 | 409 | 422 | 503 ' \
  || true
```

Prefer a structured log export filtered by correlation ID. Do not dump unrestricted logs to public artifacts.

### D. Run targeted tests in repository root

```bash
python -m compileall -q src
pytest tests/services/auth/test_auth_service.py -q
pytest tests/api_routes/test_composer_drafts.py -q
pytest tests/api_routes/test_chat_ag_ui_transport.py -q
pytest tests/api_routes/test_chat_run_lifecycle.py -q
pytest tests/api_routes/test_chat_run_event_journal.py -q
pytest tests/core/runtime/test_chat_runtime_stream_contract.py -q
pytest tests/integration/test_chat_transcript_postgres_isolation.py -q
ruff check src tests
mypy src
```

Database/live tests require the repository's documented DB services, fixtures and runtime dependencies; do not alter test expectations to hide absent infrastructure. `mypy src` and broad lint may report unrelated preexisting issues; classify and report rather than blanket-ignore.

### E. Run frontend checks from Next.js project root

```bash
cd src/ui_launchers/Karen-AI-Theme
npm ci --no-audit --no-fund
npm run lint
npm run typecheck
npx vitest run tests/karen-copilotkit-persisted-draft.test.tsx \
  tests/karen-copilotkit-controlled-chat.test.tsx \
  tests/karen-copilotkit-history-gate.test.tsx \
  tests/copilotkit-runtime-sdk-run.test.ts \
  tests/api-stream-incomplete.test.ts
npm run build
```

The package currently has `npm run lint`, `typecheck` and `build`, but **does not define an `npm test` script**. Use `npx vitest run` for unit tests. Avoid triggering authenticated Playwright against personal data.

### F. Execute **real authenticated browser** acceptance on reviewed candidate

Use the existing `KAREN Browser Acceptance` workflow `copilotkit-consumer` scenario against an approved sanitized installation. It requires deployment SHA attestation, a real reachable backend, approved credentials and a real available model. Its canonical test is `e2e/copilotkit-consumer-boot.spec.ts`. Require a non-skipped test run at the reviewed SHA, then review all assertions including saved draft, model response, execution receipt, immediate rendered answer and reload restoration. Never claim acceptance from test discovery, compilation, UI-only mocks, Vercel READY, or conditional model checks that did not actually run.

### G. Safe branch and merge procedure

- Keep local uncommitted work; never use `git reset --hard`, force push or delete a migration to align with main.
- Each PR changes one authority at a time. State observed failing boundary, cause, exact files, test evidence, guardrails and follow-up risks.
- Rebase/merge review must include changed migration paths, auth/RBAC, model registry, SDK proxy, UI hooks and history projection where relevant.
- Check exact PR-head CI. If CI green and acceptance appropriate to changed scope is met, merge without breaking main. After merge, verify main-head CI and real reviewed deployment; don't conflate them.
- No unapproved production rollout, secrets edits, schema mutation or deletion as an automatic consequence of this mandate.

---

## 13. Kiro-style assignment cards

| Task | Role | Do | Reuse | Avoid | Proof | Risk |
| --- | --- | --- | --- | --- | --- | --- |
| P0-01 revision and config | Deployment/backend | Match source, running service flags and fresh tokens | Runtime settings and `/ready` | Claiming READY=model ready | Deployed SHA, 200 readiness, effective capabilities | Low-medium |
| P0-02 draft schema | DB/runtime | Verify and correct migration/role/RLS drift | Migration 47, repository/gateway | Manual unsafeguarded DDL, RLS bypass | Real CAS and scoped DB tests | High |
| P0-03 composer | Frontend | Repair trustworthy draft/send recovery | Existing hooks and tests | Unsaved optimistic messages, duplicate state | Send only after confirmed clear | Medium |
| P0-04 transport | Full stack | Prove SDK -> API AG-UI with bounded validation | Existing HttpAgent bridge/parser | Duplicate orchestrators, POST replay | Real RUN_STARTED -> terminal | High |
| P0-05 model | Runtime | Confirm provider attempt and actual receipt | Registry, ChatRuntime | Fake fallback, configured-as-actual model | Nonempty real-model response | High |
| P0-06 persistence | Runtime/data/UI | Atomic turn, event integrity and replay | Conversation gateway/projection | Fake terminal, cross-tenant replay | Immediate render + exact reload | High |
| P0-07 production connectivity | Deployment | Reach real secured FastAPI via server-only target | Existing backend proxy and docs | Docker/localhost Vercel target, auth bypass | exact SHA, `/ready`, web `/api/health`, browser proof | High |
| P0-08 release gates | QA/release | Execute non-skipped real end-to-end acceptance | Existing Playwright/workflows | Passing mocks as live proof | exact-head acceptance matrix | Medium |
| P0-09 observability | Cross-cutting | Trace stages by correlation | Existing structured events | Logs containing secrets/content | Actionable safe error classification | Medium |
| P1-10 secondary bugs | Triage | Classify verified defects | Existing issue/test ownership | P0 scope creep | Independent reproduction/proof | Variable |

## 14. Final done definition and sign-off

The recovery is **DONE** only when all are true:

- [ ] Running source and tested source SHA match, with explicit service/container evidence.
- [ ] New authentication tokens separate roles from permissions; no phantom grants.
- [ ] The real local PostgreSQL database has migration 47 semantics, scoped permissions and verified RLS.
- [ ] An owned unsent draft reads, writes, conflicts, clears and recovers truthfully.
- [ ] AG-UI bridge is enabled by governed config on the intended runtime and passes eligibility checks.
- [ ] The main CopilotKit `/run` request reaches the canonical authenticated ChatRuntime exactly once.
- [ ] A real healthy local model produces nonempty original content, not a canned response.
- [ ] Backend returns a verified actual-model receipt with correct source/fallback semantics.
- [ ] Browser renders the same assistant answer immediately; no spinner/fake success.
- [ ] The user/assistant turn and receipt are persisted and restored after reload.
- [ ] Stop, failure, stale CAS, wrong tenant, double-send, invalid request and stream interruption fail safely.
- [ ] Main quality/security/chat/database gates pass on exact reviewed SHA.
- [ ] Authenticated non-skipped real-model CopilotKit browser acceptance passes on an approved isolated candidate at that SHA.
- [ ] Production connectivity is repaired independently and reverified before any consumer-release claim.
- [ ] Release notes list every unresolved defect, skipped test and environment limitation without hiding them.

### Local team final report format

```text
KCHAT-P0 RECOVERY REPORT
Reviewed main SHA:
Running API SHA / web SHA:
Environment (local / approved candidate):
First failing boundary before fix:
Root cause and canonical owner:
Source files modified:
Migration actions (if any) and rollback notes:
RBAC, tenant/RLS, secrets and audit verification:
Provider and actual model receipt (sanitized):
Browser live send / terminal / reload proof:
Tests executed (pass/fail/skip, exact SHA):
Remaining blockers/risks:
Merge PR URL and final merged SHA:
Readiness decision: BLOCKED / READY FOR SANITIZED REVIEW / APPROVED FOR RELEASE
```

**Architectural closing directive:** Protect the one runtime. Restore the source of truth before adding features. No fake saved drafts, no fake model answers, no authorization bypass. The first verified local round trip is the immediate objective; a full release requires exact-head, authenticated, model-backed, durable consumer proof.
