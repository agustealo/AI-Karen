# 13. Canonical generative experiences and capability migration

[Wiki index](README.md) · [Manifest reference](03-manifests-and-prompts.md) · [Frontend integration](07-frontend-integration.md) · [Governed UI architecture](../architecture/governed-generative-ui.md)

**KGUI-01 status, 2026-11-20: typed declaration is a source candidate; deployed consumer acceptance NOT_VERIFIED.** This page documents current owners, the first safe contract slice, and future migration gates. It does not imply plugin renderers are dynamically installable.

## Product principle

KAREN has one intelligent chat runtime and one governed plugin lifecycle.
A plugin can contribute a capability, a source adapter, a presentation
declaration, and optionally a UI workspace. These are distinct responsibilities.
User preference influences presentation density, not authorization or truth.

`CORTEX -> RuntimePolicy -> ChatRuntime -> PluginKernel/ExtensionExecutionService -> validated result -> presentation_contract -> AG-UI/persistence -> KarenPresentationRegistry`

Never let plugins choose global model routing, bypass owned history, provide a
second chat runtime, save data in frontend-only state, or execute model-supplied
HTML/JavaScript. A declaration is not a grant.

## Canonical owners, not competing registries

| Responsibility | Source of truth | Migration rule |
| --- | --- | --- |
| Plugin manifest | `src/ai_karen_engine/extensions/platform/core/manifest.py` | Extend one typed `ExtensionManifest`; compatibility is explicit |
| Lifecycle/discovery | `src/ai_karen_engine/extensions/plugin_kernel.py` | Do not create another registry |
| Extension execution | `src/ai_karen_engine/extensions/executor.py` | Governed plan, permissions, audit and limits |
| Conversation execution | `src/ai_karen_engine/core/runtime/chat_runtime.py` | Model/provider and persistence remain runtime-owned |
| Presentation evidence | `src/ai_karen_engine/core/runtime/presentation_contract.py` and owned-history projector | Validate and attest each envelope |
| Browser component | `src/ui_launchers/Karen-AI-Theme/src/components/chat/KarenPresentationRegistry.tsx` | Strictly render host-approved types |
| Plugin UI mounting | `src/ui_launchers/Karen-AI-Theme/src/plugin_host/` | Existing trusted materialization, slots and error boundaries |
| Pin readback | `src/ai_karen_engine/core/runtime/presentation_pin_readback.py` | Fresh authorization and provenance; mutation separately gated |

A similarly named Python/React registry is not proof of duplicated authority.
Audit all imports, runtime call sites, tests and migrations before removal.

## KGUI-01 contract: declaration, not execution

Optional manifest field: `capabilities.generative_presentations`.

| Field | Validated value | Meaning |
| --- | --- | --- |
| `version` | Semver, default `1.0.0` | Version of the declaration |
| `component_types` | 1–8 unique host-allowlisted presentation types | Types the plugin declares it may supply |
| `surfaces` | Unique subset of `chat` and `workspace`; default `chat` | Potential host placements |
| `interaction_mode` | `read_only` | No action permissions or implied mutation |

The current exact allowed component vocabulary is
`time.observation`, `date.observation`, `weather.observation`,
`weather.comparison`, `search.results`, `data.table`,
`planner.task_list`, `surface.composition`.

The extension manager exposes a bounded `declaration_only` catalog projection,
not a healthy renderer catalog. The wire envelope, schema version,
`presentation_id`, `component_type`, `data`, `evidence_ref`,
optional `correlation_id` and `display` remain defined by the runtime's
presentation contract and cross-validated by the browser. No new chat response
shape, arbitrary renderer import, or service readiness is introduced.

## Capability census and migration order

| Candidate | Current footing | Decision | Proof before enabling |
| --- | --- | --- | --- |
| Time Query | Existing plugin with system + GUI manifests | Keep plugin; audit all direct clock paths and converge only after source-truth proof | Timezone, DST, scope, feature off, live clock and replay |
| Intelligent Search / weather / news | Existing plugin; separate backend data providers and source validators | Reuse strongest live provider; preserve source provenance; avoid parallel search orchestration | Live current data, citation binding, safe URLs, freshness, provider outage, tenant scope |
| Tables and composition | Already in core and frontend host | Retain shared primitives | Source-backed cells, bounded composition, reload |
| Charts and relationship graphs | Not in current host allowlist | Add as new validated *host primitives*, not independent chat runtimes | Numeric units, gaps, labels, accessible table alternative, dataset evidence |
| Movies and other media | Currently search-result presentation, not movie-specific host type | Ground through approved source integrations and a reviewed media renderer | Licenses, release-time semantics, canonical IDs and source evidence |
| Code and artifacts | No canonical chat code renderer | Extend host vocabulary; sandbox execution remains separately governed | Full-file fidelity, safe syntax rendering, no implicit execution |
| Voice | Pocket TTS is an extension; VoiceRuntime retains control | Reuse modality declaration and host runtime | Licensed model installation, real playback, cancel, health |
| Custom forms/workspaces | Existing UI materialization infrastructure | Governed plugin UI contributions, separate action permissions | Install/upgrade/revoke/uninstall, permission checks, receipt truth |
| Durable pins | Canonical admission and reference readback | Complete full-card transport without leaking raw unverified rows | Fresh reauthorization, digest drift, revocation and signed-in browser |

## User-facing adaptive UX

The assistant chooses the **smallest useful** experience: short narrative for a
simple recipe; a verified time or weather observation for a live request;
source-backed media cards for current movies; host-rendered chart plus source
table for analytics; structured code/file views for developer work; approval
forms only for explicitly authorized mutations. The user may prefer compact,
visual, text-first, developer, or workspace presentation. Such preferences never
change evidence, provider routing, or permissions.

A plugin may optionally contribute its own page, sidebar panel, or capability
settings, but must use the existing UI host and authenticated backend.
Deactivation removes active tools and optional UI contributions; it must not
silently delete governed historical conversation or evidence.

## Consumer acceptance, not just CI

Use `src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts`
and `tests/architecture/test_local_chat_acceptance_contract.py` as the
canonical real-browser foundation. It already covers first prompt generative
provenance and dedicated time, weather, news, search and current movies tests.
Add missing adaptive journeys: curry recipe with follow-up scaling and diet
constraint, favorite-color unknown/write/relogin recall/correction, mixed
tool/model answers, charts, full-card replay, scope revocation and graceful
unavailable states. Prove the actual provider/model, real data source, persisted
assistant identity, tenant isolation, no phantom writes and one terminal
stream outcome. Check 390, 768, 1024 and 1440px and keyboard accessibility.

**Release gate:** PASS/FAIL/NOT_RUN per real signed-in environment and exact
commit. Synthetic or unit-only success cannot certify a consumer release.

## Migration and cleanup protocol

For each candidate: locate caller graph -> identify the stronger owner ->
classify active/misplaced/legacy/dead -> relocate only actual functionality ->
update manifests, authorized plan, frontend projection and tests -> prove
import/runtime/CI/browser behavior -> delete confirmed unused code only after
full reference audit. Never remove migrations, authorization, memory schemas,
audit, or recovery paths without separate explicit verification.

KGUI-01 is intentionally only the typed manifest/catalog bridge. Next work:
KGUI-02 backend+frontend presentation schema parity for chart and code,
KGUI-03 source-backed media, KGUI-04 governed UI interaction contracts,
KGUI-05 authenticated browser, lifecycle and accessibility release proof.

## KGUI-03A: Fault containment and shorthand calendar repair (2026-11-22)

- Keep bare/short date questions in the existing governed Time Query route. A date
  observation comes from the actual authorized clock receipt, not a second model
  synthesis that could invent the weekday. Concepts involving historical dates
  or code remain ordinary chat.
- Contain exceptions at each read-only presentation occurrence in the saved
  assistant message and response rail. Preserve text, other cards and provenance.
  A malformed replay event remains a backend-attested history-integrity failure:
  do not silently discard it or weaken the owner-scoped recovery contract.
- This slice does not claim to reproduce every reported crash, certify live
  search availability or add executable generated components.

## KGUI-03B+: Proposed Card Studio extension contract

**Owner:** Card Studio is an optional, governed authoring workspace exposed
through the existing PluginKernel, extension manifests and trusted UI host.
The canonical presentation contract remains the only card schema and admission
authority; Card Studio must not create a second registry, execution route or
free-form React/HTML generator.

**Library and CRUD:** Show system templates as immutable seed definitions.
Create user-owned copies; edit drafts with optimistic revision control; clone,
preview, publish, activate/deactivate and archive scoped templates. Do not
mutate built-in defaults. Store versioned declarations, theme/layout preferences,
data-source bindings, owner, tenant and audit metadata in a canonical governed
PostgreSQL repository, not browser localStorage. Existing
`CustomizableCardDeck` remains a local show/hide/order preference layer until
its explicit migration to scoped saved preferences.

**Three creation entrypoints:** (1) user enters a structured definition in Card
Studio; (2) user describes a desired card in chat, where CORTEX proposes a
`card.template.propose` intent and RuntimePolicy controls proposal execution;
(3) a dedicated Studio prompt generates an editable declarative draft. All use
one versioned prompt contract, a single schema validator, the same draft service,
and a read-only preview with supplied real authorized evidence or clearly marked
sandbox sample data. No generated code is executed.

**Runtime rendering:** Separate template selection from capability invocation.
CORTEX may request a presentation; ChatRuntime resolves authorized capabilities,
obtains typed evidence, evaluates the active template against its allowed
host primitives, validates limits and emits the existing `karen.presentation.v1`
event with evidence provenance. Replayed templates must remain bound to the
original committed version and must recheck authorization. If a template is
unavailable, safely show truthful source-backed text.

**Scope and security:** Authenticated user-scoped and tenant-scoped ownership;
RBAC for publish/share/administration; CSRF protections on mutations; immutable
revision history; audit of activation; template and binding validation;
parameterized queries and backend-only source adapters; no arbitrary URLs,
unsafe HTML/CSS, JS/TSX, SQL or secret-bearing fields from model outputs.
Any action card requires a separately authorized manifest action, confirmation,
idempotency and a persisted receipt.

**Adoption sequence:** First merge KGUI-03A and reproduce the real chat crash.
Then introduce the canonical template schema and migration/repository; create
read-only Studio CRUD and preview; add chat-to-draft suggestions; add versioned
bindings and controlled publication. Introduce new host primitives only after
schema parity in Python/TypeScript, hostile-input tests and browser acceptance.

**Proof:** DST, locale and short contextual date tests; real authenticated
time/news provider probes; one bad card leaves chat plus peers readable;
old/revoked/unknown templates fail closed; tenant isolation and RBAC; concurrent
edits with revision conflict; cross-process persistence; historical replay;
responsive browser tests; accessibility, structured telemetry and no secret logs.
