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
