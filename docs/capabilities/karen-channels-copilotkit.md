# Karen Channels: CopilotKit Channels SDK integration contract

Status: **Approved direction; existing canonical Channels infrastructure confirmed, CopilotKit SDK adapter not implemented**
Parent: [CopilotKit-first ADR](../architecture/decisions/2026-10-25-copilotkit-first.md)
External reference: https://github.com/CopilotKit/OpenTag

## Source-verified placement and ownership correction

This plan extends, rather than reinvents, the already implemented Karen Channels
subsystem. Canonical owners verified in `main`:

- **PluginKernel / catalog:** `src/ai_karen_engine/extensions/plugin_kernel.py`,
  `extensions/platform/core/registry/plugin_registry.py`.
- **Manifest packages:** `src/ai_karen_engine/extensions/plugins/` with current
  `manifest.json` convention, exemplified by `telegram-bot/manifest.json`.
- **Channel interface:** `src/ai_karen_engine/extensions/channels/contracts.py`,
  including ChannelAdapter, verified identity and delivery records.
- **Host lifecycle:** `src/ai_karen_engine/services/channels/host.py`,
  activation, linking, ingress, execution, delivery, credentials and worker.
- **Canonical durability:** `src/ai_karen_engine/persistence/repositories/channel_repository.py`.
- **Operator config:** `src/ai_karen_engine/config/channels.py`,
  disabled-by-default validated ChannelHostSettings.
- **Human approvals:** `src/ai_karen_engine/services/approvals.py` and
  `persistence/repositories/approval_repository.py`.

There is **no authorization to add a second channel host, plugin catalog,
approval database, outbox, native worker or independent LangGraph agent**.
Use CopilotKit Channels SDK/OpenTag only for SDK-native transport and presentation
aspects not provided by Karen's existing channel adapter implementation.
Any necessary Node runner must be an isolated, audited edge adapter into the
existing ChannelIngressService and ChannelDeliveryService. Operator choice
between managed CopilotKit Intelligence and a self-operated runner is explicit.

Before adding a new channel capability manifest, evaluate the existing
`telegram-bot`, `whatsapp-cloud` and other channel packages to reuse adapter,
secret, lifecycle, install/uninstall and RBAC patterns. Keep native platform
identities untrusted until host-owned binding and policy validation completes.

## Product capability

Karen Channels is a first-class, installable capability plugin with individual channel adapters.
The first supported adapter is Slack; Microsoft Teams follows using the same contracts.
No standalone OpenTag agent, second provider registry, or duplicate memory service is allowed.

## Verified upstream implementation boundary

The upstream `@copilotkit/channels` SDK carries agent interactions through AG-UI and
supports native Slack and Teams UI. OpenTag demonstrates real cards, files, approval
interrupts, a Node Channels/CopilotRuntime host and a Python LangGraph agent.
In its standard deployment, CopilotKit Intelligence mediates platform credentials and
delivery; a self-operated channel runner is a separate deployment choice.

The SDK itself does not establish Karen tenant mapping, consent, identity,
replay protection, or unified conversation persistence. Karen must supply those.

Do not confuse the CopilotKit CLI managed Channels configuration with similarly
named open-source adapter packages. Pin SDK dependencies from a verified compatible
release and preserve the locked versions. Do not copy OpenTag's standalone agent.

## Canonical ownership

| Concern | Owner |
| --- | --- |
| Slack/Teams message ingress and native cards | Karen Channels plugin / CopilotKit Channels SDK |
| Platform credential and delivery infrastructure | Selected, explicit managed or self-hosted runner |
| Agent event projection | Existing canonical AG-UI contract |
| Identity binding and tenant resolution | Karen authentication / session authority |
| Action eligibility | CORTEX and RuntimePolicy |
| Provider/model choice and execution | ChatRuntime |
| Tools and plugin permission checks | Existing governed ToolBridge / plugin registry |
| Approvals | Runtime-authorized, durable approval/action receipt service |
| Conversation and memory persistence | Canonical conversation repository and NeuroVault |
| User experience | CopilotKit, with a single shared action/render vocabulary |

## Slack vertical slice: complete consumer journey

1. A registered, tenant-authorized installation binds a Slack workspace and actor to
   an authenticated Karen principal. Unbound messages fail closed without creating a
   new tenant or implicitly granting access.
2. Receive a signed platform event through the configured runner. Validate trust
   boundary, replay ID, event size, rate limits and delivery scope.
3. Resolve stable tenant, user, thread and conversation correlation. Thread linkage is
   durable and tenant-scoped, never only an in-process dictionary.
4. Translate the request to the canonical ChatRuntime's approved AG-UI ingress; do not
   allow arbitrary client tool/context/state/provider overrides.
5. Present results with native Slack UI using SDK facilities, plus accessible text
   fallback and evidence references; redact tool inputs, secrets and private reasoning.
6. For a permitted write, create a server-owned pending action with actor, tenant,
   channel, conversation, tool, canonical arguments digest, expiry and idempotency key.
7. Accept approval/rejection only from the authorized approver; atomically recheck
   permission, scope, consent and action state immediately before mutation.
8. Execute using the canonical tool owner. Commit outcome and durable receipt before
   claiming success in Slack. Concurrent or retried approvals must not execute twice.
9. Rehydrate the same authorized conversation in Karen web UI via canonical history,
   preserving source-channel information and native-UI-safe presentation metadata.
10. Handle rejection, cancellation, token revocation, transport disconnect, duplicate
    platform delivery, worker restart, provider degradation and cross-tenant attacks
    without false success.

## Plugin manifest requirements

Reuse the existing manifest schema, registration and permission gates. Declare
`channels.connect`, `channels.read`, `channels.send`, and `channels.manage` only
if matching existing governed permissions or register through the canonical RBAC
authority. Installation and management are administrative operations; channel users
cannot bootstrap their own elevated roles.

The plugin must be disableable and uninstallable without deleting shared canonical
conversation data. Define credential revocation, pending approval cancellation,
retention effects and audit continuity before uninstallation.

## Compatibility and deployment checks

- Check Node, package-manager and React compatibility against current pinned Karen
  versions before introducing `@copilotkit/channels` or runtime dependencies.
- Validate SDK license and the precise versioned event/action API.
- Use managed Intelligence only as an explicit, documented deployment option.
- Investigate the fully self-operated runner cost: signing, reconnects, concurrency,
  worker ownership, durable event queue, metrics and secrets.
- Keep the Python agent service and Karen's runtime authoritative. If a Node
  CopilotRuntime host is technically necessary for Channels, it is a restricted
  bridge, not a second ChatRuntime or general provider/router.
- Bind operational metadata to request, tenant, conversation, channel installation,
  platform event, approval, tool call and runtime correlation identifiers.

## Acceptance gates

- A real authenticated Slack mention receives one evidence-grounded response.
- Duplicate events and approval clicks yield one governed side effect.
- Unauthorized workspace/user/tenant bindings are rejected.
- Failed and expired approvals cannot execute; permission is rechecked on commit.
- File processing uses bounded, authorized, malware-aware ingestion paths and
  retention rules from existing artifact ownership.
- Rich cards are accessible and backed by actual persisted receipts.
- Replay in Karen's CopilotKit web chat references the correct canonical conversation.
- Outage, runner restart, malformed events, secret revocation and cancellation behave
  honestly, with structured telemetry.
- UI/AG-UI/API/plugin/integration tests plus a live Slack validation are required
  before declaring consumer readiness. Microsoft Teams requires its own tenant-consent
  and live integration proof.

## Non-goals

No OpenTag standalone LangGraph agent, duplicate planning services, duplicate tools,
new ad hoc permission systems, second memory/conversation store, fabricated channel
deliveries, direct writes from render components, or hidden mandatory hosted dependency.

## Suggested work packets

- **CK-CH-01:** dependency/SDK/API/licensing check and current plugin-manifest audit.
- **CK-CH-02:** register CopilotKit SDK-backed transport adapter in the existing PluginKernel and channel host, with fail-closed identity and event envelope.
- **CK-CH-03:** Slack read-only AG-UI round-trip with provenance and native presentation.
- **CK-CH-04:** authorized durable approvals, idempotent write path and concurrency burn.
- **CK-CH-05:** canonical cross-channel history/replay and browser acceptance.
- **CK-CH-06:** Teams adapter with live tenant setup, identity and approval verification.
