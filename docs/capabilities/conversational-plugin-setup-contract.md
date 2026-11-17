# KPLUG-CONV-01: Conversational plugin discovery, setup and execution

Status: **architecture and acceptance contract; not yet fully implemented**.
Owner: ChatRuntime for conversation/orchestration, CORTEX for decisions,
PluginKernel for installed catalog and standard extension execution,
ChannelHost for communication-channel lifecycle. No new setup orchestrator.

## User outcome

The user can ask Karen to **use** a plugin and manage its lifecycle in
normal conversation, including:

- "Set up my Telegram."
- "Is my Telegram connected?"
- "Continue setting up Telegram."
- "What Telegram features can you use?"
- "Enable my Telegram bot" and "Disable it."
- "Which plugins can do this?" or "Use the eligible installed plugin to do X."

The user should not need to manually search plugin screens for every action.
Karen discovers actual installed capabilities, explains prerequisites, and
executes **only** eligible, authenticated, approved, observable actions.
The UI remains a trusted input/output surface for secrets, approvals and
capability/status display; it is not the orchestration authority.

A request is not permission to bypass policy or to silently perform an
irreversible provider mutation. "Set up my Telegram" starts a governed setup
session; it does not prove that any credentials, provider accounts or
messages are already connected.

## Source-of-truth inventory

| Responsibility | Canonical owner |
| --- | --- |
| Recognize setup/use/manage intent | CORTEX intent/eligibility decision |
| Choose and run action, maintain turn context | ChatRuntime |
| Available plugin packages/features and manifests | PluginKernel / PluginService |
| Generic, permitted plugin action | Existing runtime tool/plugin executor and ActionExecutionGate |
| Telegram and other communication-channel lifecycle | ChannelHostServices / ChannelActivationService |
| Action permission | Current user, tenant, RBAC, RuntimePolicy, fresh authorized plan |
| Provider credentials | Existing Vault/credential reference flow, never the LLM |
| Connection, identity binding, revisions and outcomes | Tenant-scoped canonical SQL and channel repository |
| Natural-language response/status UI | Projections of host-confirmed state |
| Audit/correlation | Existing structured runtime/channel telemetry |

**Mandatory constraint:** Communication-channel transports remain intentionally
unavailable through unrestricted generic plugin execution. ChatRuntime may
request a ChannelHost action only after an action-specific policy decision.
Do not add another Telegram conversation worker, startup scanner, settings
store, tool registry, provider router, plugin loader or provider fallback.

## Intent and capability contract

1. CORTEX recognizes a **generic plugin.setup / plugin.manage / plugin.use**
   family with an explicit capability target. This is not a hardcoded
   string-to-"telegram-bot" bypass. Resolve candidates from actual manifest
   metadata and a canonical capability registry.
2. ChatRuntime applies eligibility and feature availability from the
   installed catalog, tenant configuration, current principal and actual
   host connection state. A plugin named in user text is a requested
   target, not permission for invocation.
3. Setup planning is a structured, typed result: installation, capability,
   action, required role/policy, current revision, prerequisite status,
   next safe step, any approval input and evidence source. Plugin output
   cannot mutate this plan.
4. Read-only inventory/inspection comes before mutations. If the target is
   missing, disabled or not registered, report that accurate state rather
   than claiming it was discovered or auto-enabled.
5. Every mutation needs a new/fresh runtime-specific authorization that
   matches tenant, principal, session, installation, action and current
   revision. Re-check immediately before host execution, not just on intent.
6. Maintain multi-turn continuity with existing session/STM and persisted
   backend evidence. A resumed "continue setting it up" re-reads the
   canonical state. Do not treat chat text as a durable setup completion
   record or replay old approvals.

## Telegram example: progressive setup contract

The exact order of allowed work is based on the current state, not a
hardcoded always-run recipe:

1. Inspect installed Telegram manifest, backend registration, permissions,
   connection/owner inventory, host availability, activation and webhook
   evidence. Show a truthful summary of blockers.
2. If the plugin is uninstalled/unregistered/disabled, request the eligible
   installation or registration action. Do not interpret a frontend bundle's
   presence as a registered executable backend.
3. Determine whether a verified, appropriately authorized operator can
   provision the connection. If not, present the required operator action
   instead of elevating the user through chat.
4. Capture bot token and webhook secret only through Karen's existing
   authenticated Vault-backed secret form/action, with no plaintext token
   inside normal chat, model prompts, transcripts, provider logs or
   general plugin arguments. Chat receives only redacted status/handle.
5. Use the existing host's provision/activate path with fresh
   channel.provision/channel.activate authorization and revision fencing.
   Provider getMe identity check is evidence for activation, not
   webhook registration or live reply.
6. Register/reconcile the exact authorized webhook through existing
   channel.webhook.register/channel.recover semantics. Do not reissue
   setWebhook after ambiguous or expired in_flight claims. The current
   verified uncertain-claim recovery path does not authorize in_flight
   recovery, bot transfer, deletion or provider retries.
7. Pair the Telegram sender via Karen's governed identity proof. A native
   Telegram ID or JSON-supplied user ID is not a trusted Karen principal.
8. Confirm independently: durable signed inbound admission, bounded worker
   claim, verified principal, ChatRuntime execution, staged outbox,
   authorized transport dispatch, Telegram message_id and persisted receipt.
   Explicitly distinguish acceptance, execution, SENT, DELIVERED, READ and
   unknown outcomes; Telegram's Bot API SENT alone is not delivery/read
   verification.

At each step, Karen says exactly what exists, what requires the user's
input or operator approval, and what it could actually do. Never assert
"Connected" or "I sent a test reply" without corresponding durable/proven
evidence. If safe UI input is unavailable, provide a supported setup action
without requesting raw credentials in chat.


## System-wide interaction invariant (KPLUG-CONV-01A)

This is a core Karen behavior, independent of Telegram and independent of
whether a plugin has a dedicated screen. User intent is interpreted once in
CORTEX and handed to ChatRuntime. Every plugin target, role, capability and
installation state comes from the registered PluginKernel manifest, not a
per-plugin natural-language alias table or a UI-only route.

The generic request family includes:

- Discover: "Show my plugins" / "Which installed plugins can I use to write articles?"
- Setup/resume: "Set up my X" / "Continue configuring X"
- Inspect: "Is my X ready?" / "What can my X plugin do?"
- Manage: "Enable X plugin" / "Disable X" / "Uninstall X"
- Use: "Use my X plugin to perform Y"

At the **read-only** KPLUG-CONV-01A stage, all these user requests resolve to
a single plugin.inspect preflight. That capability authorizes only inspection,
never a lifecycle mutation or execution. The requested operation/action is
returned separately and explicitly marked **not executed**. The presence of a
manifest or successful preflight is not proof that a requested plugin task
happened. Missing and ambiguous matches must be reported as such.

The next runtime stage must dispatch using existing owners, not Telegram
branches in ChatRuntime:

| Declared manifest family | Operational authority |
| --- | --- |
| General plugin actions and schemas | PluginService -> PluginKernel -> ExtensionExecutionService |
| Communication transports | ChannelHost / ChannelActivationService, with durable SQL ownership |
| Voice/STT/TTS plugin engines | VoiceRuntime engine catalog and governed synthesizer/transcriber |
| Future specialized plugin families | Their registered canonical host adapter, not an additional chat router |

Every path shares authenticated tenant/user/session, RuntimePolicy, manifest
RBAC, fresh action-scoped approval, schema validation, Vault-safe credential
handoff, persisted receipts and audit. Feature declarations are useful for
discovery but do not establish engine health, account ownership, active consent,
remote provider success, or live functionality.

A plugin may be installed and enabled while its operator role is unavailable
to the current user. A manifest-specified role match is only preliminary
eligibility; the plugin still cannot execute until the canonical action gate
grants an independently authorized plan. Unknown or unsupported capabilities
must never become model-generated claims of completion.

**Proof:** tests must be deliberately provider-neutral, covering arbitrary
newly registered general plugins, declared voice features, channel-host-only
features, role-denied requests, generic management/use intents, unknown or
ambiguous manifests, and zero side effects during preflight. These tests must
be invoked by exact-head CI, not merely checked into the repository.


## General plugin interaction contract

Conversational setup is only one use case. A user can also ask Karen to
**use** a supported plugin to accomplish an authorized task.

- Discovery resolves only registered, valid and eligible capabilities.
  Manifest prompt contracts, input/output schema and permissions are
  versioned and enforced by the canonical runtime.
- User intent selects a capability; CORTEX decides policy and eligible
  actions; ChatRuntime executes using the normal governed tool/plugin
  path with budget, timeout, idempotency and audit.
- Results are validated against the plugin output schema. Plugin-supplied
  text does not create permissions, change model/provider selection,
  invent an execution receipt or override safety policy.
- Side effects requiring consent/approval return a structured
  needs_approval/needs_input result; execution occurs only after fresh
  approval and authentication. Read-only actions may complete immediately.
- Failure produces a truthful result and allowed next step; no canned
  fake model response, invisible credential retry or ungoverned fallback.

This is a reusable feature for all installed plugins, not a permanent
Telegram-specific routing exception.

## State/result contract

A typed setup interaction should distinguish:

| Field | Meaning |
| --- | --- |
| intent / installation_id / requested_capability | Authenticated user's requested purpose and resolved catalog target |
| tenant_id / user_id / session_id / correlation_id | Trusted runtime context, not user-provided plugin claims |
| backend_registered / enabled / credential_ready | Independent canonical runtime and secret readiness |
| connection_revision / account_verified / webhook_verified | Fresh host/SQL/provider observations with source |
| sender_linked / runtime_execution_verified | Trusted binding and actual runtime evidence |
| provider_send_verified / provider_delivery_verified | Separately evidenced provider outcomes |
| needs_input / needs_approval / denied / unavailable | Incomplete or forbidden stage, never false success |
| action_receipt / policy_decision_id / next_action | Redacted persisted outcome and authorized next step |

Implement using the existing runtime response/presentation envelopes when
possible. Avoid adding fields that duplicate already authoritative types.
Do not surface secret handles or raw provider URLs in user-facing responses.

## Security and negative cases

- Wrong tenant, revoked owner/binding or locked principal: deny before
  mutation or model invocation.
- Wrong role or missing channel action: deny; no ability to mint policy
  permission from the request itself.
- Stale revision or credentials: stop before provider mutation.
- Invalid signature or no durable inbox receipt: no ChatRuntime turn.
- Provider returned an ambiguous send result: UNKNOWN and no automatic
  send retry. Do not display SENT.
- Registration claim expired in_flight: fail closed pending an independently
  proven recovery contract. Expired uncertain may use the existing
  observation-based verification path.
- Pasted secret in conversational user text: never reuse it as a credential.
  Credential collection must be host-secure and redacted from prompts,
  memories, telemetry and transcript surfaces under canonical redaction.
- The plugin is unavailable: do not invent or silently substitute one.

## Proof and release criteria

**Conversation acceptance**
- "Set up my Telegram" maps through CORTEX + ChatRuntime to the canonical
  registry and produces an actual, tenant-scoped readiness inspection.
- The missing-installation, unregistered, disabled, missing-credential,
  provisioned, activated, webhook-verified, linked, pending and denied
  branches return accurate next steps.
- Authorized setup actions invoke ChannelHost through RuntimePolicy and
  revision fencing. Generic PluginService.execute_plugin cannot operate
  the Telegram transport.
- Follow-up "Continue setting it up" resumes from durable state and does
  not replay an uncertain provider side effect.
- A separate generic "Use installed plugin X for task Y" request calls an
  approved capability and returns validated result with provenance.
- UI status and language model output match observed backend evidence.

**Regression and integration**
- Unit tests: typed intent/contract, manifest resolution, RBAC/approval,
  stale revisions, credential redaction, idempotency, revoked session.
- Integration: authenticated user chat -> intent/policy -> host action ->
  persisted change -> truthful chat response; cross-tenant denial.
- Existing PostgreSQL channel tests and full signed Telegram webhook ->
  ChatRuntime -> outbox -> provider parser contract remain green.
- Live pilot separately proves a real provider-confirmed send. A mocked
  provider, successful recovery schedule or registered webhook never passes
  live readiness.
- Exact-head quality, plugin backend/frontend/security, production boot and
  architecture authority checks pass before merge.

## Universal conversational read-action contract (intermediate execution slice)

The first executable chat contract is deliberately small and provider-neutral:
an installed, verified generic plugin may opt into a **fixed-parameter,
side-effect-free** operation through its canonical execution manifest. Chat
language such as "Use my Time Query plugin to tell me the time" can then
execute using the **same PluginService and ExtensionExecutionService as the
existing API**, not a Telegram, clock or application-UI special case.

For generic plugins, the authoritative field is
`governance.conversational_actions` in the loader-selected
`plugin_manifest.json` (not a similarly named UI manifest). Version 1
contains 1–16 distinct actions. Each action must declare exactly:

- `id`: a stable, scoped action identifier
- `utterances`: bounded, exact user-goal phrases normalized for whitespace,
  case and trailing punctuation
- `parameters`: bounded, literal scalar invocation inputs, never interpolated
  user text or credentials
- `side_effect_level`: exactly `none`
- `requires_confirmation`: exactly `false`

Example from the installed Time Query capability:

```json
{
  "conversational_actions": {
    "version": 1,
    "actions": [
      {
        "id": "clock.current_datetime",
        "utterances": ["tell me the time", "show current time"],
        "parameters": {"mode": "datetime"},
        "side_effect_level": "none",
        "requires_confirmation": false
      }
    ]
  }
}
```

The above is nested inside the existing manifest `governance` object.
Only the canonical manifest version is authoritative. Plugins that have not
opted in continue through the read-only inspection route, with a truthful
"not performed" answer. No arbitrary natural-language argument is passed
through this v1 action mechanism. Complex semantic extraction and dynamic
parameters require a future separately reviewed, typed prompt contract.

Execution is permitted only when *all* of the following are true: a unique
validated installed manifest resolves the plugin; the plugin is enabled and
eligible for generic execution; the authenticated principal's current roles
match its declared roles; exactly one fixed read-only action matches the goal;
the request's direct inspection plan is authorized and has remaining budget;
a separate fresh PluginService RuntimePolicy decision grants the actual plugin
action; the canonical executor validates invocation inputs and grants; and
the result returns a matching success receipt for plugin, user, tenant,
session, conversation, correlation and policy **and an explicit nested
plugin-level status of success without an error**. An outer executor receipt
with an empty, pending, malformed or error-only payload does not establish
completion. The inspection plan is **not** reused as an execution grant.

Communication transports and voice modality plugins are excluded from this
generic executor. ChannelHost and VoiceRuntime remain the only respective
host authorities. Setup, enable, disable, install, send, publish and delete
remain blocked until independently approved action contracts are implemented.
A plugin-returned error, missing receipt, mismatched identity or unverifiable
status never produces a success response.

Proof is in `tests/core/runtime/test_conversational_plugin_action.py`,
executed explicitly by Main Quality and Plugin Backend. Its sample receipt
fixtures are test-only; they are not evidence of a production plugin execution
or real provider delivery.


## Canonical owner-scoped channel inspection (KPLUG-CONV-01B)

The universal plugin.inspect route remains read-only. For an explicitly named,
validated communication-channel installation, ChatRuntime may consult the
existing ChannelHostServices to inspect that **authenticated user's** personal
connection records, using the existing tenant-RLS repository.

ChannelHost issues exactly one fresh channel.consent action plan tied to the
current chat session **before** querying SQL, including when the user has no
connections. It never trusts model-supplied tenant, user, session, plugin or
permission claims, and it does not forward provider account identifiers, bot
credentials, Vault handles, webhook URLs, or connection IDs to chat.

The response projects only owned count, persisted enabled count, revision,
the owner evidence source and a next-action hint. "Enabled" refers to a stored
SQL connection flag and does not attest live provider registration, local
adapter activation, sender binding, ChatRuntime execution or reply delivery.

The application lifespan attaches the real initialized ChannelHost to the
existing direct-capability executor, then revokes that reference **before**
host shutdown. With a disabled host, the connection status remains
not_inspected. Denied owner inspection and infrastructure unavailability
remain separate. No channel is provisioned, paired, activated or messaged.

Owner-state, missing-consent, cross-tenant, one-policy-check, runtime
projection, and host-binding regressions are in the existing
tests/core/runtime/test_conversational_plugin_inspection.py suite, explicitly
executed by both Main Quality and Plugin Backend.

## Global plugin lifecycle preflight (KPLUG-CONV-02A)

An authenticated message such as "Enable my X plugin" or "Disable my X
plugin" is an intent to change **application-global** plugin state, not a
tenant-local preference or an automatic execution grant.

CORTEX continues to route these requests to read-only plugin.inspect. For a
uniquely resolved manifest, the existing PluginService performs an additional
read-only lifecycle preview using the authenticated UserData and the same
ADMIN_PLUGINS_MANAGE permission used by the canonical plugin management API.
No role from user chat prose, model output, manifest tags or a frontend
checkbox may authorize this operation.

The preview explicitly distinguishes unsupported commands, invalid
installations, unavailable lifecycle states, absent permissions, already
satisfied state, and **needs_explicit_confirmation**. A confirmation-required
result identifies the already-existing authenticated Plugins & Tools
management surface as the separate place to finish a change. It does not
claim a currently working conversational confirmation endpoint or grant
RuntimePolicy permission by returning that hint.

Voice engines and communication-channel installations are delegated to the
existing VoiceRuntime and ChannelHost authorities. The global generic plugin
enable/disable path must not be used to activate a channel or substitute a
separate provider control plane.

The preview contains only installation ID, requested action, required
permission, global scope, current lifecycle state, static next-action hints
and denial/confirmation status. Every response sets approval_granted=false,
mutation_performed=false and action_receipt=null. It cannot be used as an
executable token or replayed approval. A later mutation must be newly
authorized, confirmed and audited through the canonical management owner.

The preflight and negative tests run in
tests/core/runtime/test_conversational_plugin_inspection.py, already invoked
directly by Main Quality and Plugin Backend.


## Attested management status across stream and saved history

The live consumer CopilotKit chat does not read arbitrary `structured_content`
values. On a completed canonical `plugin.inspect` run, Karen transports a
single bounded `karen.plugin_management_preflight.v1` event only when the
pure runtime contract verifies a non-executable, nonapproved lifecycle status.
Only the approved fields are projected, never the entire plugin inventory.

Saved rich replay requires the original assistant message to match the exact
completed-run message digest and a valid canonical request ID. Historical
status is rendered as an observation at that time, not a current approval or
live plugin state. Malformed/forged/unsupported metadata fails closed or
falls back to the original text; no API or UI action is inferred from it.
Explicit text-only continuation withholds the rich status event.

`tests/core/runtime/test_plugin_management_preflight_projection.py` verifies
live completion, failed persistence, schema denial, replay attestation,
mutation-claim rejection, and honest text-only restoration. The source test
runs in both Main Quality and Plugin Backend.

## Consumer presentation for management preflight (KPLUG-CONV-02B)

The canonical CopilotKit verified assistant slot and legacy chat renderer present verified `plugin_management_preflight` data as a
small status panel instead of exposing the raw backend JSON. The component
accepts only an application-global, nonexecuted and nonapproved preflight with
the canonical `admin.plugins:manage` permission and bounded plugin/action
identifiers. Invalid or unknown evidence cannot produce an action link.

For `needs_explicit_confirmation` with `permission_verified=true` and the
canonical `plugin.open_admin_management` hint, the panel may navigate to the
existing `/plugins` page. This is **navigation only**, not confirmation,
policy authorization, an enable/disable request or an execution receipt.
User-origin structured content can never produce the management panel.
The existing Plugins & Tools owner performs any later mutation after its own
authentication, authorization and verification checks.

Proof: `KarenPluginManagementPreflight.test.tsx` plus the canonical verified-history parse and replay suite tests the responsive chat
presentation, permission denial, unknown envelopes, forgery attempts and the
absence of execution claims. CI runs the standard frontend Vitest and TS
checks; no second settings or action owner is introduced.

## Application-global lifecycle claim ledger (KPLUG-CONV-02C2)

A backend-only, global PostgreSQL revision row now provides a **claim
reservation boundary**, separate from the tenant-scoped approval records.
`extension_lifecycle_revisions` stores the last host-observed PluginKernel
manifest checksum, state and revision. `extension_lifecycle_operations`
records the approval, tenant, actor, action, expected revision, correlation
identity and **prepared**/unknown status without plugin settings or secrets.

`PluginLifecycleLedger.initialize_observation` must be called only by a
trusted kernel owner after independently observing the installed manifest
and state. It never overwrites a conflicting existing row. The authorization
path uses the exact approved action payload, checks the expected revision
and manifest digest, and atomically consumes the one-shot approval with
a globally exclusive claim. The transaction rolls back entirely if the
receipt write fails. A claimed or unknown row remains unresolved until a
separate verified reconciliation. The ledger has no API route or plugin
execution method and cannot emit a success receipt.

**Status:** claim schema/repository and a disposable real PostgreSQL proof
are implemented in KPLUG-CONV-02C2. A backend-only, kernel-observed terminal
CAS and replay/rollback tests are introduced in KPLUG-CONV-02C3A below.
The governed execution entrypoint, cross-worker physical execution fencing,
fresh RuntimePolicy grant, unknown-outcome reconciliation, and chat-safe
completion projection are **not yet available**. Existing admin API mutations
must enter the same global fence before claiming installation-wide concurrency
safety. Do not expose a consumer chat confirmation control at this stage.

Proof:
`tests/integration/test_plugin_lifecycle_ledger_postgres.py` runs in
Plugin Backend against `/karen_plugin_lifecycle_test`, using a restricted
database role, two tenants with competing claims, exact approval matching,
rollback on failed insert, uncertain-outcome retention and direct client
read denial. This is not a substitute for a kernel mutation integration
test or a verified post-restart recovery test.

## Kernel-observed terminal ledger CAS (KPLUG-CONV-02C3A)

The canonical `PluginKernel.observe_lifecycle_for_finalization` now reads a
registered, validated generic plugin's actual runtime state and explicit
durable enable/disable markers **under its existing state lock**. It rejects
unavailable/quarantined/untrusted installations, active executions, unfinished
retirement, missing or symlinked lifecycle markers and specialized voice or
communication-channel plugins. The typed
`PluginLifecycleKernelObservation` binds the operation, installation, catalog
checksum and observed state. The durable checksum is SHA-256 over
the loader-selected canonical manifest bytes, **not** the catalog's legacy
MD5 directory fingerprint and not user-provided metadata. The state markers
are checked separately and do not alter that manifest digest. It is a
host-internal observation, **not** a permission, approval or transferrable
execution grant.

The forward-only migration
`20261117020000_61_plugin_global_lifecycle_terminal_status.sql` widens
`extension_lifecycle_operations.status` from 16 to 24 characters because
the predeclared `verified_committed` state needs 18. It does not convert
old prepared or unknown operations, relax the status check constraint, or
grant clients table access.

The existing `PluginLifecycleLedger.complete_verified` accepts only a
prepared operation in the exact authenticated tenant and actor scope.
It locks the claimed operation and transactionally (1) checks that the kernel
observation matches the reserved action's target state and checksum,
(2) advances the **application-global** revision by exactly one while
releasing its specific claim, and (3) records `verified_committed` on the
same operation. A mismatch, unknown/cancelled/stale/replayed claim, wrong
actor, SQL error or failed receipt update rolls back the entire terminal
transaction. No preflight, prepared claim or in-memory success can alone
produce a committed receipt. The existing `mark_unknown` remains permanent
and unresolved; uncertain mutations are not implicitly retried or restored.

**Scope and deliberate limitation:** This backend completion primitive is not
connected to a chat mutation endpoint or exposed to the consumer UI. Current
`PluginService.enable_plugin`/`disable_plugin` and other admin entrypoints
have not yet been migrated to one global execution gate, and the PluginKernel
lock is process-local. Therefore this slice **does not establish safe
cross-worker physical mutation, host-wide recovery, or live chat enable/disable
readiness**. A host-observed local state cannot authorize chat execution.
KPLUG-CONV-02C3B must govern *every* physical mutation path before the
completion primitive is used to claim a production-safe lifecycle change.

**Proof:** `tests/extensions/test_plugin_kernel_verified_lifecycle_observation.py`
exercises real local kernel state/marker transitions and fail-closed modality
and active-execution cases. The existing
`tests/integration/test_plugin_lifecycle_ledger_postgres.py` includes a
real kernel transition followed by restricted-role PostgreSQL finalization,
tampered operation/checksum/state rejection, wrong-tenant denial, transaction
rollback on receipt write failure, monotonic revision and replay/unknown
refusal. Plugin Backend runs both on exact-head CI. These tests do not by
themselves certify a multi-worker production transition.

## Locally atomic kernel lifecycle transition (KPLUG-CONV-02C3B1)

The trusted PluginKernel exposes a narrow backend-only
`transition_prepared_lifecycle(scope, operation_id=...)` primitive. It accepts
the existing immutable `PluginLifecycleApprovalScope`, compares its expected
pre-transition state and canonical manifest SHA-256 against actual kernel state,
runs the existing enable/disable implementation, then re-observes the exact
target state **without releasing the kernel state lock**. Refused/changed
manifests and stale local states produce no mutation; invalid post-transition
evidence is an exception, never a success receipt. Other local lifecycle calls
cannot interleave between the preflight and terminal observation.

**Security boundary:** this is *not* a substitute for durable
`PluginLifecycleLedger.reserve_approved`, a fresh RuntimePolicy authorization,
a cross-process physical admission lock, or a committed
`PluginLifecycleLedger.complete_verified` receipt. The kernel does not
treat a supplied scope or operation ID as an authorization grant.
No production caller or API/chat endpoint invokes this method yet.
Exceptions after a possible physical write must leave the global operation
unresolved/unknown; no blind retry or implied rollback.

The adjacent kernel regression suite proves exact expected-state/checksum
matching, local competing transitions, durable marker evidence, active
execution denial, and failure of post-transition observation. It does not
claim PostgreSQL multi-worker execution proof. Subsequent KPLUG-CONV-02C3B
slices must hold a durable per-installation execution lock across this
transition, finalize receipts atomically, and route all actual admin/marketplace
and extension-platform mutation entrypoints under the same global policy gate.
Until those gates and acceptance tests pass, conversation-driven plugin
enable/disable remains unavailable.

## PostgreSQL-held physical execution admission (KPLUG-CONV-02C3B2A)

The existing `PluginLifecycleLedger` now owns an internal, application-global
`hold_prepared_execution(scope, operation_id)` context. It accepts only the
exact tenant/actor-scoped prepared claim and a matching global installation,
manifest SHA-256, state and revision. It acquires a transaction-scoped
PostgreSQL advisory lock keyed to the canonical installation, then commits an
independent, one-way status update from `prepared` to `in_flight` **before**
yielding to a physical kernel transition. The advisory lock must remain held
across the kernel's locally atomic `transition_prepared_lifecycle` and the
ledger's `complete_verified` CAS. Separate workers attempting the same global
installation are refused; this is not merely a process-local asyncio lock.

The forward-only migration
`20261117030000_62_plugin_global_lifecycle_execution_admission.sql` adds
the `in_flight` state and a durable `execution_started_at` field.
Existing `verified_committed` history is not backfilled with fictitious
execution timestamps. Terminal CAS now accepts **only** `in_flight`, not
`prepared`, and an admitted claim cannot be entered again even if its
connection dies or its kernel transition returns an uncertain outcome.
`mark_unknown` accepts `prepared` and `in_flight` without releasing the
unresolved global revision. There is no automatic physical retry.

**Explicit scope:** this is a host-only persistence and concurrency primitive.
It is NOT a RuntimePolicy decision, RBAC permission, human approval, trusted
chat action, or production entrypoint. Existing direct administrator/store/
extension compatibility calls have not been migrated to this fence and can
still bypass its physical serialization. A PostgreSQL advisory lock excludes
only cooperating callers and a lost database connection releases that lock;
the surviving `in_flight` operation is what prevents repeat admission.
The global deployment must share the same authoritative database and physical
plugin installation before any multi-host execution certification. Do not
claim globally safe mutation until every active caller uses one service owner
and fresh policy/RBAC is proven. Chat enable/disable remains **disabled**.

**Proof:** the dedicated disposable PostgreSQL lifecycle integration test
applies the real forward-only migration, uses a restricted backend role,
refuses forged actor/operation/checksum, demonstrates two independent
connections contending for one installation lock while a real kernel
transition and terminal CAS run, verifies replay denial, and models a crash
after durable admission that leaves an irreversible unresolved claim.
The test is part of the exact-head Plugin Backend workflow, not a mock-only
contract. Startup recovery, policy-bound service orchestration and API caller
migration remain subsequent KPLUG-CONV-02C3B work.

## Execution slices (do not duplicate owners)

1. **KPLUG-CONV-01A:** Audit current runtime intent/tool orchestration and
   installed manifest descriptors. Add the minimal generic plugin-management
   intent/response contract plus read-only authenticated discovery with tests.
2. **KPLUG-CONV-01B:** Add governed multi-turn setup next-actions, safe
   approval/credential handoff and canonical host execution adapter.
   Ensure setup can be driven conversationally without route-owned logic.
3. **KPLUG-CONV-01C:** Add UI/presentation continuity and full chat-driven
   Telegram setup acceptance, including negative cases and policy/tenant
   proof. Verify real Telegram round trip separately.

**Release rule:** Plugin lifecycle success and channel operational delivery
are different statuses. Both require evidence; neither may be simulated.

## Approved conversational lifecycle execution (KPLUG-CONV-02C)

**Implementation status: not yet available.** The merged #960 read-only
preflight and #964 verified consumer panel are not approval or mutation paths.
Do not expose a chat Enable/Disable confirmation control until all the
following backend and replay evidence exists. This is a provider-neutral
system behavior, not a Telegram implementation.

### Authority and existing entry points

| Responsibility | Reuse; do not clone |
| --- | --- |
| Generic plugin target/intent | CORTEX and ChatRuntime's existing `plugin.inspect` discovery |
| Authenticated execution identity | `ChatExecutionContext.require_authenticated_user()` |
| Scope/permission/action eligibility | `RuntimePolicyEnforcer`, `ActionExecutionGate`, `ADMIN_PLUGINS_MANAGE` RBAC |
| Human confirmation and single-use approval | `ApprovalService` / `SqlApprovalRepository` |
| Canonical lifecycle state and physical mutation | `PluginService` -> `PluginKernel` |
| Receipt/audit | Existing runtime audit and tenant-scoped PostgreSQL persistence |
| Consumer presentation/history | Verified AG-UI event projection and canonical CopilotKit assistant slot |

The existing plugin management HTTP endpoints are permission-guarded, but
`PluginService.enable_plugin` and `disable_plugin` delegate directly to the
kernel. **Never call them from ChatRuntime based on a natural-language request,
preflight, UI value, or unchecked approval ID.** Introduce a narrow governed
management operation in the existing service owner; do not create a second
execution manager, public mutation endpoint, or browser-side authorization.

### Exact approved-action identity

The trusted backend must bind approval and subsequent execution to one
immutable, validated management plan containing at least:

- Canonical `installation_id` and explicit `enable` or `disable` action.
- Manifest digest/provenance, expected lifecycle state, and authoritative
  **durable monotonic lifecycle revision** at preflight.
- Authenticated actor, tenant, session, conversation, policy decision,
  required permission, request/correlation IDs, expiry, and single-use
  idempotency/approval identifiers.
- The effective installation scope is application-global. Tenant isolation
  protects approvals and audit, but a tenant-scoped lock alone does not
  serialize a global plugin state mutation.

The current `ApprovalService.request_fingerprint` covers normalized chat
messages and identity, **not installation state or lifecycle revision**.
Extend the existing approval model/repository to bind this typed action
rather than assuming a chat fingerprint implies stable plugin state. Ensure
an approval is not a bearer capability: its stored receipt must be re-read
in the authenticated caller scope. A pending or rejected receipt is not an
execution grant, and an approved receipt is not sufficient without fresh
RuntimePolicy authorization.

### Mutation and concurrency fence

One canonical kernel mutation primitive must re-read the installed manifest,
trust/quarantine flags, dependencies, active-execution state, lifecycle state
and revision **inside the same guarded transition**. Only an exact expected
revision and action permit the transition. The current
`PluginKernel._state_lock` is process-local; it does not establish a durable
cross-worker fence. Use an existing canonical, strongly consistent repository
and appropriate global lock/compare-and-swap before claiming cross-process
safety. If deployment topology cannot guarantee that ordering, fail closed.
ChannelHost and VoiceRuntime remain exclusively responsible for channel and
voice lifecycle, even for administrators.

Persist intent/claim before the mutation and a terminal authoritative outcome
afterward. Uncertain state, an expired claim, a commit failure, or an
interrupted write must **not** become 'enabled' or 'disabled' by inference,
nor trigger a blind retry. Reconciliation should inspect the actual kernel
state and durable revision. An approval is single-use even when the outcome
is failed or unknown; retries require a new scoped authorization or a
separately verified idempotent recovery contract.

### Result and UI contract

Use a separate bounded, server-verified lifecycle result envelope instead of
reinterpreting `karen.plugin_management_preflight.v1`. Approved-pending,
denied, stale/conflict, failed, unknown and verified-completed are distinct.
A completed success must carry a persisted receipt with the actual action,
installation, actor scope, approval/policy IDs, prior/next revision,
correlation ID, kernel outcome and proof of current state. No secrets,
credentials, raw plugin arguments or arbitrary plugin-supplied fields may be
projected. Saved history is an observation at execution time and cannot be
replayed as a fresh action or current plugin state.

### Release proof (must be exact-head and non-mock where specified)

1. Current administrator has a verified, explicitly confirmed target/action;
   approval and fresh policy are checked and consumed once.
2. Ordinary user, unverified principal, forged UI approval, wrong tenant or
   session, revoked admin role, expired/rejected approval and replay all fail
   without mutation.
3. Manifest/provenance/state/revision drift, independent concurrent
   enable/disable attempts, active executions and enabled dependents fail
   closed; enforce the global fence across multiple workers with real
   PostgreSQL-backed state.
4. Crash/timeout/persistence error produces an honest failed/unknown receipt;
   no false success and no automatic duplicate write.
5. Channel and voice management cannot go through generic plugin lifecycle;
   read-only inspection and existing direct plugin read actions still work.
6. CopilotKit live/history and legacy renderer reject forged mutation claims,
   handle denial/unknown states, and navigate only via allowed next actions.
7. Main Quality, Plugin Backend, Plugin Frontend, Plugin Security, production
   first-boot and the dedicated real-PostgreSQL concurrency/replay suites pass
   on the exact PR head before enabling chat mutation UI.

**Do not declare KPLUG-CONV-02C complete from this architecture contract.**
Release requires implementation and observed evidence for the entire chain.
