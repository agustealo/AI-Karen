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
   retention/deletion coupling and a genuine process-kill/restart proof,
   as distinct from two independent repository instances operating against
   the same real PostgreSQL database, plus UI feature/voice/persona/draft/scroll
   parity.
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

## CK-07E2: browser protocol proof and protected dispatch authority

The guarded `KarenCopilotHistoryGate` refuses unsupported roles, duplicate
message IDs, invalid history bounds, and unverified CUSTOM events **before**
mutating SDK state. CK-07E3 adds a native CopilotKit assistant-message slot
for supported attested rich presentations/receipts. All other rich content
remains fail-closed. The mounted assistant-ui is still the consumer surface.

`e2e/karen-copilotkit-protocol-acceptance.spec.ts` is checked in for a
real HTTPS sanitized deployment: authenticated canonical history and
`agent/default/connect` must reproduce only persisted messages and
backend-attested CUSTOM events, and a real event journal cursor must
report truthful interruption/terminal state with no model replay or
tool execution. The spec uses no trace, screenshots or video and must
never run with fabricated credentials or an invented journal run ID.

**Security update from main (commit 33f60a97):** The canonical protected
`.github/workflows/karen-history-browser-acceptance.yml` is now
**default-branch-only** and exposes only its reviewed `history`
scenario. Its credentials are supplied to just the authorized
configuration check and real browser test steps, never dependency
installation or an unreviewed PR checkout. New
`tests/architecture/test_browser_acceptance_dispatch_security.py`
enforces that boundary. This takes precedence over an older draft
workflow from #556 that exposed PR `search/copilotkit` options with
job-wide secrets. We explicitly removed that unsafe dispatch in the
forward merge of `main` rather than retaining a second authorization
owner. Any additional acceptance scenarios must first be reviewed and
authorized **on the default branch**, with revision attestation and
step-scoped credentials. Do not create another secret-bearing PR
workflow to unblock this proof.

The single read-only deployment revision route is owned by PR #550;
do not duplicate it. Running the CopilotKit protocol/visual parity
spec on a sanitized exact-revision deployment remains **unverified**
and is an explicit consumer-cutover and merge-release blocker. The
presence of a Playwright spec or a skipped workflow is not acceptance.

## CK-07E3: CopilotKit v2 native rich-message slot (unmounted)

The unmounted `KarenCopilotChat` now uses CopilotKit v2's documented
`messageView.assistantMessage` slot, preserving CopilotKit's original
assistant bubble, toolbar, composer and scroll components. The slot attaches
only the backend's verified, saved `replayEvents` to the **matching canonical
assistant message ID**, through `KarenCopilotHistoryGate`. It reuses the
existing Karen presentation registry for weather, time, planner and
compositions, rather than inventing a second renderer or SDK transcript.
The execution and response-integrity receipts were moved to a **single**
render-only component shared by the incumbent assistant-ui and CopilotKit.

Rich playback performs full pre-hydration validation of event type,
assistant-message binding, presentation schema/evidence, size and repetition,
execution/integrity receipt allowlists, and duplicate presentation IDs.
Malformed or unsupported content refuses the entire history BEFORE
`agent.setMessages()`; no partial replay is counted as a successful
restoration. There is no frontend authority to approve actions, select
providers, rerun saved tools or manufacture presentation evidence.

**This does not complete consumer parity.** CopilotKit remains unmounted:
native component-level no-auto-run guards exist, but actual deployed browser
verification, partial-stream/live CUSTOM event parity and restart proof are
still missing. Persona, voice, attachment,
draft, responsive-scroll, focus, conversation-switch and cross-workspace
contracts must be verified against the existing UI before consumer cutover.
Do not remove assistant-ui or enable new flags on the strength of component
tests alone.

## CK-07E4: controlled native SDK view and durable post-run read-back

CopilotKit v2 documents that high-level `CopilotChat` invokes `runAgent`
automatically on first mount. That is unsafe for an already-saved Karen
conversation. The unmounted shell now instead composes the SDK's
`CopilotChatView` (native message list, scrolling, input, accessibility and
assistant-message slots) with `useAgent` and `useCopilotKit`. Only
`CopilotChatInput.onSubmitMessage`, invoked by explicit composer submission,
adds a bounded user message and calls `copilotkit.runAgent({ agent })`.
An unverified thread, blank/oversized input or a currently active agent
does not execute. The canonical runtime remains the only model, tool,
memory, policy and persistence owner. SDK stop is requested only if the
agent reports an active run, but exact durable stop/receipt parity remains
a separate browser gate.

`KarenCopilotHistoryGate` subscribes to the **real ready agent** through
the supported AG-UI `onRunFinalized` and `onRunFailed` callbacks. These
events never become an authority for saved metadata. Instead they trigger
a fresh authenticated `/api/copilotkit/threads/{id}/messages` read,
validate all backend-attested `replayEvents`, and replace SDK messages
only after complete verification. A failed read fails closed. Cleanup
unsubscribes on thread switch/unmount; stale responses are ignored.
This intentionally presents rich results **after durable commit/read-back**,
not prematurely during an unverified stream.

Unit tests prove no `runAgent` on mount, explicit-submit-only execution,
active/foreign-thread/input rejection, no fake provider errors, SDK stop
gating, and committed-history recheck on run finalization/failure. The
existing protected browser scenario remains required for actual SDK
behavior, keyboard/draft retention and other UI parity before cutover.

## CK-07E5: persona and renderer-neutral voice-to-unsent-draft parity

The unmounted controlled CopilotKit view now uses the **existing**
`KarenPersonaSelector` in its sticky footer. It reads the canonical
persona catalog/preferences and posts a preference switch only through
`/api/personas/preferences/switch`, retaining the previous selection
if server persistence is not confirmed. No new persona store, selection
registry, role bypass or UI-only "saved" state was created.

Existing `KarenLocalDictation` and optional `KarenBrowserDictation` now
remain thin **assistant-ui adapters** over `KarenLocalDictationCapture`
and `KarenBrowserDictationCapture`. The capture implementations share
`KarenVoiceDraftPort` (`readText/writeText`) and
`mergeDictatedText`; microphone permission, local WAV encoding, real
backend transcription, browser-vendor opt-in, stale-generation/cancel
fencing and no-auto-send behavior were preserved from the incumbent UI.

CopilotKit `CopilotChatView.input` now supplies SDK-supported controlled
`value/onChange` plus explicit `onSubmitMessage/onStop`; the two
shared capture components write only the unsent draft, **never** call
`runAgent`. Blank/oversized drafts are rejected. Submission clears
the current visible draft; failure restores it only when another draft
has not been entered. The private view is keyed to the canonical
conversation UUID so switching conversations unmounts/cancels any old
microphone capture before it could change another thread's input.

**Not yet claimed:** persistent drafts across reloads/windows/sessions or
multiple signed-in accounts. The current draft is a per-conversation
in-memory controlled input and MUST NOT be represented as durable.
Adding persistent cross-window drafts requires one authenticated,
tenant/user/conversation-scoped owner with deletion/revocation behavior,
not an ad-hoc unscoped `localStorage` mirror. Rich live streaming,
real-browser voice/microphone, keyboard/focus, and SDK stop parity also
remain release blockers. No consumer feature flags are enabled.

## CK-07E6: canonical authenticated cross-window drafts (migration 47)

The canonical `ConversationRuntimeGateway` and existing
`PostgresConversationRepository` own unsent draft reads and
compare-and-swap updates. Migration
`20261026010000_47_conversation_composer_drafts.sql` creates one
`public.conversation_composer_drafts` row per canonical conversation,
owned by the **same tenant and user**, with forced PostgreSQL RLS,
bounded UTF-8 text (65,536 characters/262,144 bytes), monotonically
increasing revisions, and `ON DELETE CASCADE` to the conversation.
A nonexistent row has a virtual empty draft at revision 0.
Drafts never appear in transcript, memory, tools, observability payloads,
AG-UI runs, presentation receipts or model outputs.

Thin authenticated `GET/PUT /api/conversations/{conversation_id}/draft`
routes recheck canonical owner via the runtime gateway. A PUT must include
`expected_revision` and receives a new revision only when the atomic SQL
CAS succeeds. Concurrent stale-window writes return **409**; missing/foreign
conversation returns **404**; missing migration or storage failure returns
**503**, not fake persistence. Both successful responses include
`Cache-Control: private, no-store`. The server never logs draft content.

The unmounted CopilotKit composer now uses the single
`useKarenPersistedDraft` adapter to read the canonical backend,
autosave bounded typed and voice-dictated edits, and refresh clean drafts
on focus/periodic checks. A dirty local draft is NEVER overwritten by
background refresh. Revision conflicts stop writing and show a read-only
copyable local draft plus an explicit discard/reload choice; unavailable
storage is truthfully reported and the input cannot silently imply a
save. Local text is cleared from memory on unmount/logout and is never
mirrored to localStorage. Drafts persist in the canonical database while
their conversation exists, including across new windows/sessions.

Crucial submit boundary: `clearBeforeSubmit` requires an **acknowledged
revision-fenced empty-draft PUT** before `agent.addMessage` or
`copilotkit.runAgent`. It refuses conflicting, unavailable, pending or
unverified state; an SDK append/run error restores the unsent text
without inventing model completion. A caller cannot silently lose a
newer draft from another window by sending a stale one.

**Proof**: `tests/api_routes/test_composer_drafts.py` verifies owner
checks, missing/foreign scope, storage errors, API 409/503, and bounded
inputs. The existing dedicated PostgreSQL job now applies migration 47
and verifies actual multiworker CAS, least-privilege tenant/user RLS,
and physical erasure following canonical conversation deletion.
`tests/karen-copilotkit-persisted-draft.test.tsx` tests real hook
loading, autosave acknowledgments, conflicts, cross-window refresh,
unavailable storage and invalid receipts. Additional controlled view
tests verify no inference unless clear is durably confirmed.

**CK-07E6 adversarial follow-up:** the private CopilotKit SDK provider is
now keyed by the authenticated `tenant_id`, `user_id` and canonical
conversation UUID. If authentication is loading, revoked, or incomplete,
no provider, agent, draft or recorder mounts. Switching user/tenant with
the same conversation ID destroys the previous SDK tree and its unsent
local state. Component tests prove logout and both scope changes remount
and clear the old provider rather than reusing it.

The authenticated draft hook additionally fences parallel focus/interval
reads with monotonic read generations. Any new read invalidates older
responses, and a confirmed CAS write or durable submit-clear invalidates
all pre-write reads. A regressed revision or changed text without a new
revision fails closed instead of replacing verified content. Focus-order,
post-write stale-read and revision-regression tests verify that protection.
The runtime gateway now emits structured, correlated read/success,
CAS/success and stale-window conflict log events with request, correlation,
tenant, user, conversation and revision metadata, **never draft contents**.
The draft repository methods also use the canonical
`instrument_repository` wrapper. That wrapper currently has its event-emitter
call commented out, so Prometheus/emitter integration is still an existing
observability debt and **is not** claimed as proven by these logs. A unit
test asserts the events omit private text.

**Privacy/acceptance limits**: no dedicated background purge of abandoned
draft rows is claimed; retention follows the canonical parent conversation,
including explicit conversation/user erasure. Unsent drafts intentionally
survive logouts on the *server* until erased with their parent, but logout
does not keep a readable local copy. Cross-window synchronization is
eventually consistent through backend rereads, not a real-time collaboration
editor. Migration 47 must be applied before any consumer rollout;
an uninstalled migration fails closed. Real-browser account switching,
logout, network loss, conflicting tabs and keyboard/focus/voice parity
remain required before the still-unmounted CopilotKit cutover.

## CK-07E7: default-branch protected CopilotKit protocol acceptance

The existing `KAREN Browser Acceptance` workflow now offers a separate
`copilotkit-protocol` scenario. This is a **read-only protocol proof**,
not a CopilotKit consumer UI cutover. Its exact reviewed `target_sha` must
match both the dispatched **current `main`** revision and the running Vercel
deployment, verified through both the canonical revision endpoint and
independent platform provenance **before and after** authentication.

This uses the existing sanitized-credential environment, immutable-host
deployment-bypass-cookie fixture, no-redirect preview authorization and
read-only `karen-copilotkit-protocol-acceptance.spec.ts`. Credentials are
scoped to validation and browser proof steps, never job-wide or dependency
installation. Browser navigation verifies the approved HTTPS origin
**before typing the password** and after sign-in. Browser traces,
screenshots, videos and uploads are disabled for the authenticated proof.
No PR-ref credential dispatch, unreviewed deployment or extra workflow
was introduced.

Required operator-controlled environment variables are
`KAREN_COPILOTKIT_ACCEPTANCE_URL`,
`KAREN_COPILOTKIT_CONVERSATION_ID` and
`KAREN_COPILOTKIT_OBSERVED_RUN_ID`; the protected workflow also
requires its existing `KAREN_UX_EMAIL`/`KAREN_UX_PASSWORD`,
Vercel verification and bypass credentials. Missing or mismatched
source, deployment, credentials, saved conversation or actual observed
run **fails closed**. The source spec never manufactures a provider
run or saved assistant content. It checks owned history snapshots,
attested replay-only CUSTOM events, ordered journal cursor and
absence of invented RUN_FINISHED for incomplete runs.

The Docker acceptance contract now verifies **each job's** protected
environment, rather than enforcing a fixed job count. The existing
signed Docker host proof and its credentials-on-host prohibition
remain unchanged.

**Unproven:** This scenario does not mount the CopilotKit view.
SDK-native composer/keyboard/focus/scroll/voice/persona/attachment
UX, multiwindow interactive CAS, actual model start/stop and human
visual parity need their own approved browser verification. Do not
enable AG-UI/consumer flags, delete assistant-ui or merge #556
based on this read-only protocol scenario.

## CK-07E6 follow-up: honest composer recovery

When an SDK message append fails after a successful durable draft
clear, newer text typed during the await is preserved, and the failed
original remains explicitly copyable until acknowledged. Retry tests
require a conscious user action. Clean draft read failures now require
a real authenticated reread; dirty draft write failures can only retry
with their already confirmed CAS revision. Neither path invents a
"saved" receipt. New tests cover first-read outage recovery, stale
clean refresh and failed-write recovery without discarding text.

## CK-07E8: isolated, server-disabled native browser acceptance

**Acceptance-only, not a consumer feature:** the Next.js App Router page at
`/acceptance/copilotkit/{owned-conversation-uuid}` mounts the existing
`KarenCopilotChat` candidate with its actual CopilotKit v2 stylesheet
**only** when the deployment explicitly sets both
`KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED=true` and
`KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_HOST=<exact-hostname>`.
Any missing flag, incorrect HTTP Host header, invalid configured host
or invalid UUID yields 404. These are server-only environment variables;
a URL parameter or browser cookie cannot activate the page. It is
excluded from search indexing. `AuthWrapper` and the normal
CopilotKit canonical history/run/draft APIs retain their existing
tenant/user authorization; the page does not introduce a privileged
execution, history or persistence service.

The CopilotKit v2 stylesheet is a compiled **Tailwind v4** browser asset.
Importing it directly into Karen's **Tailwind v3** PostCSS build caused
an observed Web pnpm 11 Build Proof failure (`@layer base` without a
matching v3 `@tailwind base` directive). Do not bypass the error or
replace the consumer design system to accommodate an acceptance page.
Instead, `tools/prepare-copilotkit-styles.mjs` resolves the exact
installed, locked CopilotKit package CSS locally, validates its content
and generates `public/vendor/copilotkit-v2.css` at `npm/pnpm run dev`
and `npm/pnpm run build`. That generated asset is gitignored, loaded
only by the acceptance route, and the browser scenario insists that
its URL returns HTTP 200 with a CSS content type. There is no runtime
CDN, checked-in vendor fork, global Tailwind upgrade or separate UI
renderer. This fix still requires a fresh exact-head build check.

The normal dashboard still mounts exactly one assistant-ui chat. An
acceptance page is **not** proof that CopilotKit is usable or ready.
Never enable the preview on a consumer deployment or broad production
hostname. Use an approved immutable, sanitized, revision-matched
Vercel preview for the specific reviewed `main` commit; disable the
preview environment variables when acceptance ends.

The existing `KAREN Browser Acceptance` workflow now accepts
`scenario=copilotkit-native` and reuses the same main-only SHA pin,
independent Vercel provenance and public running revision checks
before and after browser execution. The sibling
`copilotkit-protocol` scenario remains read-only and requires an
observed run cursor. For the native scenario,
`KAREN_COPILOTKIT_ACCEPTANCE_URL` must point to the exact preview,
`KAREN_COPILOTKIT_CONVERSATION_ID` must be a dedicated owned
sanitized conversation, and the canonical draft for that fixture
must initially be empty. Browser credentials and the Vercel bypass
are used only in approved test steps; no screenshots, traces,
videos, stored auth state, HTTP request interception or artificial
AI results. The test verifies:

- Real authenticated controlled view, SDK message area and persona
  footer are visible while the current dashboard remains assistant-ui.
- No `/api/copilotkit/agent/default/run` POST on mount, typing,
  draft saving, or reload.
- An unsent draft is actually committed to the canonical draft
  endpoint, restored across page refresh, then cleared.
- Input can receive keyboard focus. It does not invoke a model,
  click Send, alter a real user conversation or claim agent completion.

The native scenario also verifies a second real browser tab's stale
revision cannot overwrite an independently committed same-principal draft.
One authenticated tab advances the canonical server revision while the other
remains focused; the stale writer receives a real 409, preserves its text
in the read-only copyable field, and must explicitly choose the server draft
before continuing. The saved server value and no-run network evidence are
checked. Persona selector visibility/selection is compared with the actual
backend preference without switching personas, and a 375px mobile viewport
must keep the input and footer accessible without horizontal overflow.
Both native tests use shared revision-fenced cleanup of only their known
sanitized text; they never indiscriminately clear an unknown third-party edit.
These tests remain *written, not executed* in the approved protected browser
environment as long as the candidate remains draft and main-only dispatch
cannot be run against the same exact reviewed deployment.

A third native browser scenario checks real local microphone permission
denial only where the backend explicitly advertises transcription as
available. The browser explicitly denies permission for the approved
origin, requires a visible error and inactive recording state, and proves
that no audio upload or model execution POST occurred and that the
canonical draft was unchanged. An environment reporting disabled
transcription marks that scenario as *skipped/unverified*, not passing
voice parity. Browser-vendor dictation is not enabled or tested here.

Persona mutation acceptance is **separately opt-in** with the protected
environment variable `KAREN_COPILOTKIT_PERSONA_MUTATION_REQUIRED=true`
and a sanitized dedicated principal. The native selector must submit a
real revision-fenced backend preference update, receive an incremented
revision, survive browser reload, and trigger no model execution.
The browser test then uses the same canonical CAS endpoint to restore
the principal's original persona only if its own revision still wins.
Missing opt-in is explicitly marked skipped/unverified. A competing
persona writer is never overwritten to make acceptance artificially green.
This reuses the same Persona Studio revision owner, rather than
implementing another persona persistence API or preference store.

CK-07F native cancellation acceptance now includes an authenticated
**negative-path gateway probe** in the protected browser suite. It obtains
canonical history/draft from a dedicated owned conversation, rejects a
thread-only stop with HTTP 422, and rejects a cryptographically fresh,
nonexistent run ID with HTTP 404. Rechecking both canonical resources and
the browser request journal proves no draft or transcript mutation and
no inference request. It does **not** simulate a RUN_STARTED event,
manufacture a successful stop receipt, or claim a model worker cancelled.
Real cross-worker cancellation, final PostgreSQL terminal evidence and
rendered pending/confirmed UI require a separate operator-approved
live execution with a disposable test conversation.

The suite **has not been executed against a deployed preview** merely
because it is present in the repository. Feature parity remains
incomplete: no genuine native Send-to-persisted-response, multi-tab
CAS conflict, browser microphone permission, speech cancellation,
persona-switch side effects, scroll-stickiness, mobile viewport and
cross-worker cancellation burn have been proven. Those need scoped
real-browser tests and human aesthetic review before consumer cutover.

## Proof entry points

```bash
python -m compileall src
pytest tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py tests/api_routes/test_chat_run_atomic_transcript.py tests/api_routes/test_chat_ag_ui_transport.py tests/api_routes/test_chat_run_event_journal.py tests/api_routes/test_composer_drafts.py tests/api_routes/test_owned_history_projection.py tests/api_routes/test_ag_ui_governed_history.py -q
cd src/ui_launchers/Karen-AI-Theme && pnpm exec vitest run tests/copilotkit-owned-run-stop.test.ts tests/copilotkit-owned-thread-history.test.ts tests/copilotkit-owned-thread-connect.test.ts tests/copilotkit-governed-history.test.ts tests/karen-copilotkit-history-gate.test.tsx tests/karen-copilotkit-rich-history.test.tsx tests/karen-copilotkit-controlled-chat.test.tsx tests/karen-copilotkit-persisted-draft.test.tsx tests/karen-voice-draft-port.test.tsx tests/karen-copilotkit-shell.test.tsx tests/copilotkit-observed-run-events.test.ts
ruff check src/ai_karen_engine/core/runtime/chat_run_lifecycle.py src/ai_karen_engine/persistence/repositories/chat_run_repository.py src/ai_karen_engine/api_routes/chat/runtime.py tests/api_routes/test_chat_run_lifecycle.py tests/api_routes/test_chat_run_repository.py
pytest tests/architecture/test_copilotkit_migration_wiring.py -q
```

A dedicated non-production PostgreSQL concurrency test is also checked in:
`tests/integration/test_runtime_chat_stop_concurrency_postgres.py`. It exercises
the real migration, PostgreSQL row locking, tenant/user scoped cancellation,
duplicate stop, stop-versus-completion race, lease expiry and fenced finality.
The test applies migrations 43, 44, 45, 46 and 47 and verifies atomic saved message
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
