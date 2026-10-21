# Governed Generative UI for Karen

## Ownership contract

Generative UI is a presentation capability of the canonical Karen Runtime. It is **not** an additional orchestrator or an independent source of truth.

- **API ingress:** authenticate, resolve session and tenant, validate input, delegate, and translate errors. No UI selection or tool execution.
- **CORTEX:** decide whether response presentation should be narrative, structured, compositional, or action-oriented. Enforce capability and policy eligibility.
- **Canonical Runtime:** obtain real capability results, normalize typed evidence, select presentation, persist authorized results and event metadata, emit one unified AG-UI stream.
- **Presentation registry:** a versioned, allowlisted component vocabulary with input schemas, budgets, compatibility contracts and safe fallbacks.
- **assistant-ui:** render authorized content, stream progress and present controls. It cannot invent data, resolve provider choices, write memory or execute privileged tools.
- **AG-UI:** deliver observed execution events and response parts. It is not an authorization decision-maker.
- **Deep Agents:** execute delegated multistep work. LangGraph only where true graph execution is needed.

## Normalization and presentation boundaries

Each capability result carries an immutable evidence reference and an explicit quality state. An independent retrieval failure (e.g. memory) must not mark a successful weather observation as unusable.

Use a versioned backend contract with these conceptual fields:

- `schema_version`, `presentation_id`, `component_type`
- `conversation_id`, `message_id`, `correlation_id`
- `data_refs`, `observed_at`, `freshness`, `units`
- `capability_status`, `degradation_reasons`, `source_provenance`
- `tenant_id` and `permissions` checked exclusively server-side
- `state_revision`, `interaction_receipt`, `action_idempotency_key`

The wire shape must be finalized by inspecting existing chat response/event and persistence schemas. Do **not** add a competing unvalidated response envelope.

Presentation modes:

1. **Deterministic:** trusted tool data is rendered via a known typed renderer (weather, search, time, etc.).
2. **Compositional:** a model proposes an allowlisted presentation tree. Runtime validates schema, depth, output size, units and evidence bindings before emission. A model may not generate executable JS/TSX or untrusted HTML.
3. **Interactive:** user actions call already registered, authorized backend capabilities. Status reflects persisted receipts, not optimistic assumptions.

A provider capable of plain text but not structured presentation must fall back to a complete, accessible narrative. The UI must not force model changes simply because a generative renderer exists.

## Capability coverage and experience gaps

| Domain | Required output | Interaction constraints |
| --- | --- | --- |
| Weather | condition, temperature, high/low, humidity, wind, precipitation, observation time and source | refresh only via runtime, do not invent hourly series |
| Time, calendar | timezone-aware clocks, availability, calendar events | edits only after scoped permission |
| Search and research | ranked references, quotations, evidence, media if trustworthy | links verified, cite original sources |
| Geography | geocoded pins, supported routes and travel context | maps need real coordinates and routing evidence |
| Analytics | tables, plots, distributions, filters | never infer missing datapoints |
| Files and documents | previews, structured extracts, editable drafts | save/export receipts and access scope |
| Planner | tasks, time blocks, priorities, conflicts | optimistic edit never equals persisted state |
| Workflows and agents | plans, status, subagents, artifacts, durable checkpoints | AG-UI events cannot fabricate completion |
| Memory and persona | remembered facts, provenance, conflicts, correction requests | tenant isolation, explicit confirmation for governed mutations |
| Providers/settings | real model inventory, health and permissions | UI mirrors backend truth only |
| Communication channels | conversations, transports, send drafts | explicit user approvals and action receipts |
| Plugins | declared capability schema and result renderer | verified manifests and RBAC |

## Explicit non-goals

No raw model-authored React code, no direct DOM execution of model payloads, no client-side plugin execution, no independent frontend fallback router, no duplicate memory store, no unsanctioned network fetch in UI, no unauthorized cross-workspace data exposure.

## Verification gates

1. Check import resolution, dependency pins and lockfile reproducibility. Make the feature opt-in until proven.
2. Unit-test normalization, units, missing fields, zero values, unknown conditions, date parsing and URL safety.
3. Verify tool events carry structured results instead of a raw extracted-data transcript only.
4. Add an AG-UI integration test for partial event streaming, cancellation and reconnect/replay.
5. Verify message persistence and restoration of presentation state, interaction receipts and accessibility metadata.
6. Test tenant/RBAC failures and expired approvals server-side, including repeat-click idempotency.
7. Run renderer security tests for hostile links, unknown component types, oversized trees and malformed tool results.
8. Check responsive layout, keyboard navigation, screen-reader labels, contrast, reduced motion and degraded text fallback.
9. Test frontend lint, typecheck, test and build; backend compileall, pytest, ruff and mypy as applicable.
10. Perform governed authenticated end-to-end screenshots using observed live capability results.

## Current incremental implementation

The first slice registers a read-only weather presentation in existing assistant-ui AG-UI data rendering and the tool-result fallback. This does not yet satisfy the compositional, interaction, persistence, or backend normalization gates. Keep rollout feature-flagged and avoid merging as a complete generative implementation until those gates pass.
