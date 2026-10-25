# CK-01: Canonical ownership and wiring preflight

Date: 2026-10-25
Status: Partial verified source inspection. Not a live execution proof.
Branch: architecture/copilotkit-first-migration-20261025

## Confirmed source anchors

| Concern | Verified path | Observation |
| --- | --- | --- |
| Canonical configuration | `src/ai_karen_engine/config/runtime.py` | `RuntimeSettings` and `FeatureFlags` own central backend options |
| AG-UI enablement | `src/ai_karen_engine/config/runtime.py` | `enable_ag_ui_bridge=False` by default; never silently enable at frontend |
| Plugin directory config | `src/ai_karen_engine/config/runtime.py` | `ServiceEndpoints.plugin_dir="/app/plugins"` is a deployment path, **not** a verified manifest loader |
| Legacy Copilot transport | `src/ai_karen_engine/api_routes/chat/copilot.py` | Still delegates chat to canonical runtime; predictor dispatch explicitly remains a compatibility surface |
| Canonical web SSE gateway | `src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts` | Auth/header forwarding and terminal event integrity exist and must survive |
| Current web UI | `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/KarenAssistantChat.tsx` | Imports persona, model catalog, dictation, history, presentation, activity and companion-rail components |
| Shared presentation contract | `docs/architecture/governed-generative-ui.md` | Evidence-bound versioned presentations with accessibility and durable replay obligations |

## Unresolved owners: do not fabricate

- Plugin manifest loader, registry, installation, uninstall and RBAC attachment: **not located** in this inspection. A guessed `src/ai_karen_engine/plugins/plugin_manager.py` is not supported by repository fetch.
- Durable approval/action receipt owner: **not located** in this inspection. No new approval database/table or service may be introduced until the canonical owner is traced.
- Backend AG-UI route module location and dynamic mount registration: **not yet traced**. Web proxy existence alone does not prove enabled server ingress.
- CopilotKit SDK v2 React compatibility, SDK hook names, lockfile, SSR, adapters: **not tested**.
- Reference/dependency tree for historical CopilotKit components: **not yet exhaustively traced**.

## Risks requiring fixes

1. **Feature gate drift (P0).** A CopilotKit frontend must not silently talk to a backend that has AG-UI disabled. Use centrally validated backend configuration and expose authorized availability to the UI. Verify disabled, enabled, wrong-scope and degraded responses, including startup and deployment transitions.
2. **UI behavior loss (P0).** The existing chat component has a substantial consumer contract. Before cutover, compare streamed text, model requests, persona selection, local/browser dictation, restored history, typed cards, observed agent steps, contextual rail, cancellation and accessible keyboard navigation.
3. **Two data owners (P0).** CopilotKit agent state and thread APIs are interaction-state mechanisms, not a license for independent durable conversations, profile state or memory. Project canonical server-owned revision and state snapshot through AG-UI.
4. **Legacy security deletion (P0).** No deletion of Copilot safety middleware or historic routes before graph-based reference audit and end-to-end authorization tests prove their guards were migrated.
5. **Channels packaging (P1).** Do not invent an installable plugin path/manifest based only on the configured `/app/plugins`. Find actual registry/loader/lifecycle; any Node runner remains a subordinate channel ingress adapter.
6. **Phantom proof (P1).** Documentation PR #554 and capability baseline PR #553 are not proof of live CopilotKit installation. State must remain explicitly incomplete until production-like CI and browser proof.

## Next implementation commands (run in repository workspace)

```bash
git grep -n -i -E 'plugin_dir|manifest\.json|plugin_manager|plugin_registry|extension_registry|register_plugin' -- src config plugins tests
git grep -n -i -E 'approval|pending_action|action_receipt|idempotency_key|toolbridge' -- src tests
git grep -n -E 'enable_ag_ui_bridge|/api/chat/ag-ui|AGUIRunRequest' -- src tests
git grep -n -E '@copilotkit/|@assistant-ui/|@ag-ui/' -- src/ui_launchers/Karen-AI-Theme
git grep -n -i -E 'copilotkit_provider|AgentUIService|ThreadManager|CopilotSafetyMiddleware' -- src tests config
```

Missing paths in these suggested searches are not proof of absence. Use actual repository tree and generated import/route graph. Capture output against exact commit; derive canonical plugin and approval owners before introducing code.

## Acceptance to advance CK-02

- Canonical plugin loader/manifest and approval authority located by actual imports and registrations.
- AG-UI backend enablement and route mounting proven with authenticated request and feature-gate negative cases.
- Current chat capability-by-capability parity fixture captured and joined to #553's single registry.
- Actual CopilotKit package compatibility established against lockfile and code APIs.
- No new runtime authority, provider registry, chat store, memory store, or policy bypass.
