# CK-01: Canonical ownership preflight, reconciled

Date: 2026-10-25
Status: Source-level owner discovery **confirmed**, runtime and SDK integration **not verified**.
Supersedes this document's previous unlocated plugin/approval owner assumptions.
Detailed plan: [CopilotKit migration implementation v2](./copilotkit-execution-plan.md).

## Verified canonical owners

- `src/ai_karen_engine/extensions/plugin_kernel.py` bridges platform catalog and governed execution; discovery comes from `extensions/platform/core/registry/plugin_registry.py` with typed `extensions/registry.py` execution projection.
- Extension packages already live in `src/ai_karen_engine/extensions/plugins/` and have manifests, such as `telegram-bot/manifest.json`.
- `src/ai_karen_engine/extensions/channels/contracts.py` defines channel adapter, connections, native events and delivery receipts.
- `src/ai_karen_engine/services/channels/{host,activation,linking,ingress,execution,delivery,worker,credentials}.py` already implement the governed channel lifecycle.
- `src/ai_karen_engine/persistence/repositories/channel_repository.py` owns durable channel inbox/outbox and identity persistence.
- `src/ai_karen_engine/config/channels.py` validates disabled-by-default ChannelHostSettings.
- `src/ai_karen_engine/services/approvals.py` is the runtime-owned approval service; `persistence/repositories/approval_repository.py` is its durable owner; `api_routes/automation/approvals.py` provides its HTTP surface.
- `src/ai_karen_engine/api_routes/chat/runtime.py` is canonical chat HTTP/AG-UI ingress and imports `AGUIEventProjection`.
- `src/ai_karen_engine/config/runtime.py` owns RuntimeSettings and `enable_ag_ui_bridge=False` default.
- `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts` proxies AG-UI with auth forwarding and stream integrity.
- `src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx` mounts the current assistant-ui chat and `SessionProvider.tsx` owns frontend conversation identity/bootstrap.
- `src/ui_launchers/Karen-AI-Theme/src/app/globals.css` + `tailwind.config.ts` own the HSL/Tailwind 3 visual system.
- `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/` contains persona, model catalogue, dictation, history, presentation and activity components.

## Resolved wrong assumptions

1. **There is no need to create a plugin host, manifest system or second registry.** The canonical extension system is already present.
2. **There is no need to create a general new human approval service or schema.** Extend the existing service/repository only if an independently proven granular write-action contract gap requires it.
3. **The channel service is not merely a planned module.** It already includes durable ingress/execution/delivery infrastructure. CopilotKit Channels supplies transport/native UX on top of that.
4. **/app/plugins is not the manifest authority.** It is a configurable deployment path; `PluginKernel` and the extension platform own catalog/execution.
5. **The existing web app is not a blank frontend.** Its three-panel design, composer controls, voice, persona, model, receipts and persisted history are behavioral preservation obligations.

## Still unproven (must not be claimed complete)

- Runtime flag enabled in actual deployment and authenticated AG-UI client/server compatibility.
- SDK v2 dependency installation, SSR/CSS/Tailwind 3 compatibility and typechecked component slots.
- Full route and import graph for legacy Copilot modules, including dynamic plugin registrations.
- Runtime-gate/approval replay and actual database receipts with CopilotKit UI.
- Real Slack/Teams delivery and managed-versus-local channel runner viability.
- Exact-lockfile build, Playwright visual baselines and E2E consumer parity.
- Safe legacy deletion and absence of stale consumers.

## Existing tests and gates to reuse

- `tests/api_routes/test_chat_ag_ui_transport.py`
- `tests/architecture/test_runtime_approval_authority.py`
- `tests/services/test_approval_service.py`
- `tests/architecture/test_plugin_runtime_authority.py`
- `tests/extensions/test_channel_*.py`, `tests/extensions/test_plugin_*.py`
- `tests/integration/test_channel_claim_concurrency_postgres.py`
- `src/ui_launchers/Karen-AI-Theme/e2e/karen-durable-history-restoration.spec.ts`
- `src/ui_launchers/Karen-AI-Theme/e2e/kchat-workspace-continuity.spec.ts`
- `main-quality-gate.yml`, `chat-system-burn.yml`, `presentation-contract.yml`, `plugin-ci.yml`, `karen-history-browser-acceptance.yml`.

## Entry conditions to code migration

1. Confirm pinned SDK types and UI styling; do not infer a v2 provider API from older v1 pages.
2. Validate browser-to-runtime AG-UI contract and feature gate, without an independent ChatRuntime.
3. Capture and preserve every current chat behavior as a user-facing regression scenario.
4. Mount one chat experience at a time, with rollback and no two live agent executions.
5. Require complete migration receipts and remove legacy artifacts only after dependency and policy audits.

No code paths have been changed by this CK-01 document.
