# CopilotKit migration: legacy retirement ledger

Status: required retirement gate, not a claim that legacy code was removed.
Date: 2026-10-25
Owner: Karen interaction architecture
Decision: docs/architecture/decisions/2026-10-25-copilotkit-first.md

## Rule

Prefer CopilotKit for overlapping user-facing interaction capabilities.
Retire replaced assistant-ui and historical CopilotKit implementations after
their consumers are migrated and behavioral parity has been proven. Preserve
unique Karen behavior within canonical runtime, storage, permission and
presentation contracts. No obsolete compatibility shim remains indefinitely.

The retirement gate is **per artifact**, not a blanket delete operation.
Before removal: enumerate imports, dynamic registrations, route mounts, tests,
docs, build files, dependency locks, plugin manifests and consumers; identify
replacement; demonstrate parity; delete obsolete artifact and stale references;
run full applicable tests on the same candidate head. Missing consumer discovery
or absent parity means the artifact is NOT approved for deletion.

## Initial candidate ledger

| Artifact | Concern | Proposed successor | Current decision | Required proof |
| --- | --- | --- | --- | --- |
| `src/ui_launchers/Karen-AI-Theme/src/components/chat/assistant-ui/KarenAssistantChat.tsx` | Legacy primary UI after cutover | CopilotKit v2 primary shell | retain until replacement live | Chat, model, persona, activity, voice, history, accessibility and replay parity |
| `@assistant-ui/react` and `@assistant-ui/react-ag-ui` | Duplicate UI dependencies | Tested CopilotKit UI packages | retain until no imports | Dependency graph, bundle/build, lockfile and tests |
| assistant-ui-only presentation renderers and hooks | Presentation behavior might be lost | CopilotKit render/approval contracts with existing governed schemas | selectively migrate | Typed receipts, XSS guards, persistence, replay, rendering parity |
| `src/ai_karen_engine/integrations/providers/copilotkit_provider.py` | CopilotKit misclassified as LLM provider; pseudo-client | Canonical model/provider registry plus proper CopilotKit interaction adapter | audit for deletion | Reference audit, canonical provider selection, no lost hook behavior |
| `src/ai_karen_engine/copilotkit/agent_ui_service.py` | In-process tasks/progress and message wrapper | Canonical ChatRuntime execution and durable activity projections | audit for consolidation | Existing API consumers, cancellation, task durability, response truth |
| `src/ai_karen_engine/copilotkit/thread_manager.py` | In-process thread mappings | Canonical scoped conversation/thread mapping | audit for consolidation | Durable thread continuity, tenant isolation and reconnect |
| `src/ai_karen_engine/copilotkit/session_state_manager.py` | Potential competing session persistence | Canonical session and persisted memory owners | audit for consolidation | State migration, reference graph and storage tests |
| `src/ai_karen_engine/copilotkit/safety_middleware.py` | Potential redundant or inconsistent safety gates | Canonical RuntimePolicy / RBAC and authorized tool boundaries | security review first | No removed safeguards, deny tests, cross-tenant regressions |
| Copilot-legacy HTTP routes and adapters | Duplicate ingress or old compatibility contracts | One authenticated canonical AG-UI transport | audit for retirement | Route table, external clients, telemetry, explicit deprecation |
| Legacy node/runtime agent wiring from OpenTag examples | Possible second orchestration authority | Restricted Channels bridge to Karen Runtime | never install as independent authority | AG-UI, identity, authorization, idempotency, durability |
| Stale examples, screenshots, docs, env vars, CI jobs and lockfile entries | False feature descriptions and maintenance overhead | Current CopilotKit contracts | remove after usage check | Path and symbol scans, configuration audit, docs/build green |

## Retirement checklist for every removed artifact

1. Record file path, real callers, previous responsibility and supported user capability IDs.
2. Identify the canonical replacement and whether it covers every supported behavior.
3. Search static imports, dynamic imports, reflection strings, manifest registrations,
   routes, tests, configuration, docs and shipping bundles.
4. Check RBAC, tenant/session scope, audit, consent, secrets, persistence,
   cancellation and replay guarantees from the original implementation.
5. Port missing useful behavior into the appropriate owner before removing anything.
6. Add negative contract checks proving retired paths are not reintroduced.
7. Remove source, stale imports, obsolete dependency and lockfile entries,
   scripts, feature flags, env references, styles and unreachable UI.
8. Verify frontend typecheck/lint/test/build and backend compileall/pytest/ruff/mypy,
   plus real authenticated browser and persistence acceptance as relevant.
9. Record before/after capability evidence, CI commit, deletion rationale,
   replacement location, residual risk and rollback method.
10. Close superseded PRs only after checking whether they contain unique useful code.

## Prohibition

Do not declare cleanup complete while the production bundle still mounts a
replaced framework, imports retired symbols, registers obsolete providers,
or advertises nonfunctional legacy features. Do not conceal an unresolved
migration behind an empty wrapper, canned output, silent fallback or alias.

## First execution slice

1. Verify CopilotKit version compatibility and implement the primary chat shell.
2. Verify parity of the live Karen AG-UI consumer journey against the previous UI.
3. Remove old assistant-ui packages and source after dependency and reference proof.
4. Collapse historical pseudo-provider and redundant session/task services into
   canonical owners; protect policy checks during removal.
5. Extend the same retirement ledger to channels, planner, search, model library
   and other overlapping technologies.
