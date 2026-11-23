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

## KGUI-CARD-STUDIO-01A: Canonical inert template schema (source candidate)

The first Card Studio foundation is deliberately **declarative and read-only**.
The existing `presentation_contract.py` now owns the strict v1 draft layout,
its built-in template seed projection and evidence-bound composition adapter.
This is one extension of the existing presentation owner, not a second
renderer registry, frontend code generator, execution pipeline or template store.

A draft contains only `schema_version=1`, a bounded slug `template_key`,
`title`, optional `description`, `layout` (stack/grid), `density`
(compact/comfortable), `interaction_mode=read_only`, and 1–6 uniquely named
`slots` whose `component_type` is already host-validated. The system
projection derives eight reusable primitives from the canonical vocabulary.
Nested compositions and revocable `code.artifact` are not template authoring
primitives. No dynamic imports, scripts, HTML, executable callback definitions,
unverified URLs, tenant claims, source content or permission grants are admitted.

The binding adapter composes **only the caller's runtime-authorized existing
presentation parts**, with exact slot/type matching and the current
`compose_authorized_surface` evidence-reference validator. It grants no
tool, memory, network, storage or replay authorization and is not yet wired to
ChatRuntime, AG-UI, a Studio editor or user persistence.

**Not yet implemented:** tenant-scoped PostgreSQL revisions, authoring API,
RBAC/approval receipts, user template CRUD, shared library, chat-to-draft
PromptRegistry, template publication, migration, plugin UI, authenticated
consumer acceptance or local-provider health. All remain separate gates.
Source CI is required before merge; a successful source test does not certify
end-user deployment.

## KGUI-CARD-STUDIO-01B: Scoped durable draft storage (source candidate)

This second slice reuses the canonical Postgres transaction manager
(`async_transaction_scope`) and adds the first internal Card Studio
repository under `persistence/repositories`. The migration
`20261122235900_67_card_studio_template_drafts.sql` introduces three
owner/tenant-scoped tables:

- `card_studio_templates`: stable user-owned identity, slug, head revision,
  lifecycle (draft or archived), timestamps; system-key namespace is reserved
  and user templates cannot overwrite immutable catalog definitions
- `card_studio_template_revisions`: append-only bounded JSON definitions,
  scoped composite foreign key, revision history; never evidence or executable code
- `card_studio_template_mutation_receipts`: idempotent create/revise/archive
  receipts committed in the SAME transaction as their effects

RLS is enabled and forced for all tables using the authenticated
`app.current_tenant_id` and `app.current_user_id` settings. Direct
anon/authenticated grants are revoked; immutable history rejects direct
update/delete while governed parent deletion can cascade. The repository
validates the already-merged inert draft contract and exact canonical
principal IDs, uses CAS on revisions, prevents slug reuse, enforces a bounded
live-draft library, exposes owner-scoped reads and version history, and soft
archives without destroying historical revisions.

**Boundary:** The migration/repository are not a deployment or consumer UI
feature. There is no route, plugin tool, chat proposal, template publication,
file execution, provider selection, active-card replay admission or public CRUD
access. A runtime-approved authenticated caller must still supply the
identities; declarative draft data is not a permission grant.

**Database acceptance:** The dedicated
`.github/workflows/card-studio-postgres-proof.yml` gate runs the actual
migration and canonical repository inside disposable PostgreSQL, including
injected mid-migration rollback, a restricted non-superuser role, tenant/user
RLS for all three tables, same-key concurrent retries, competing revision CAS,
immutable-history triggers, archive/history readback, atomic receipt failure
rollback and governed tenant deletion. Unit tests alone are not that proof.
This is intentionally isolated migration acceptance, NOT evidence of a full
production-schema upgrade or hosted release.

**Remaining gates:** Full-schema migration/upgrade compatibility, production
least-privilege role provisioning, authenticated API and RBAC, admin/support
lifecycle, Card Studio UX, signed-in browser acceptance, and deployed rollback.
Template publication, chat execution, and arbitrary UI code remain disabled.


## KGUI-CARD-STUDIO-01C: Authenticated owner-scoped CRUD HTTP (source candidate)

The existing DEV_FAST workflow (`.github/workflows/dev-fast.yml`) is the
first focused PR validation gate. The existing
`.github/workflows/card-studio-postgres-proof.yml` remains the canonical
database gate. Do not introduce a second Card Studio store or fast CI owner.

**Transport:** `/chat/card-studio/templates` offers list, create, read,
revision-checked revise and archive, plus historical revision listing/readback.
The canonical chat router registers the small `api_routes/chat/card_studio.py`
adapter. No client-provided tenant/user, policy decision, receipt or source
attestation is accepted. Server authentication must supply the exact principal.
All replies are `private, no-store` and have correlation IDs. Mutations require
a bearer-authenticated request so cookie-only cross-site writes cannot be
mistaken for authorized requests.

**Runtime authority:** `CardStudioTemplateService` requires an active, verified
matching user/tenant `ChatExecutionContext`, calls the existing
`RuntimePolicyEnforcer` for `card_studio.read` or `card_studio.write`,
and delegates RBAC checks to the existing central permission registry. It
never accepts a caller-issued policy grant, executes a model, or selects a
provider. Only after this admission can the existing PostgreSQL repository
read or atomically commit an owner-scoped mutation. The repository preserves
immutable receipts, uncertain-response idempotency and revision CAS.

**Server feature gate:** `KARI_ENABLE_CARD_STUDIO_CRUD`, default **false**.
This gate is independent of the AG-UI and presentation-pin gates. It must not
be enabled for consumers until real signed-session HTTP, role provisioning,
full-schema deployment and browser acceptance are independently certified.

**Audit:** An access grant/deny and successful mutation receipt emit sanitized
audit/structured events with request/correlation, owner and tenant IDs,
operation, revision and latency, never template source content or credentials.

**Not included:** Template publication/activation, shared-library roles,
plugin execution, CORTEX chat proposals, custom components, visual editor,
model-generated HTML or direct frontend SQL.


## KGUI-CARD-STUDIO-01D: visual layout editor (DEV_FAST candidate)

The existing dashboard navigation now exposes **Card Studio** as an Advanced
Tools workspace. It delegates to `CardStudioWorkspace`, while the original
`KarenPresentationRegistry` remains the sole renderer for runtime-evidenced
cards. The editor intentionally previews **unbound layout geometry only**.
It cannot invent time, weather, search results, task data, metrics or receipts.

- **Host source of truth:** `GET /api/chat/card-studio/catalog` is an
  authenticated, feature-gated, RuntimePolicy-authorized read of the canonical
  `built_in_card_template_catalog()` in `presentation_contract.py`. The
  frontend does not register a component renderer or extend the allowlist.
  The catalog is inert and non-editable. Backend template validation remains
  authoritative.
- **Editing:** Edit bounded title, immutable new-template key, optional
  description, stack/grid layout, density and one to six safe slots. Keyboard
  move buttons supplement drag ordering. The preview is explicitly labeled
  as a layout with no runtime-bound evidence. No custom HTML, CSS, JS, model
  prompts or source references may be stored.
- **Storage:** API reads use the shared `apiClient`; creates, revisions and
  archives use the existing server-authorized CRUD endpoints. A revision save
  carries the backend head's `expected_revision`. Success is shown **only**
  after the exact committed receipt is checked against the original operation,
  key, template, revision and definition.
- **Uncertain responses:** No automatic POST/PUT retry. Before sending a
  mutation, the editor keeps an immutable key and request payload in
  principal-scoped **tab sessionStorage**, or refuses to send if that recovery
  write fails. Network/5xx/protocol errors lock editing and retain the
  request, offering manual replay of the exact same idempotency key and
  payload. A confirmed 409 requires an explicit reload; no optimistic
  "saved" toast or hidden fallback response is permitted.
- **Default off:** `KARI_ENABLE_CARD_STUDIO_CRUD=false` still governs every
  endpoint, including catalog discovery. When disabled, the UI must show
  unavailable and refuse editing rather than inventing local templates.
- **Separate acceptance:** Real responsive browser acceptance at 390, 768,
  1024 and 1440 px; actual local operator feature enablement; accessible drag
  and keyboard ordering; screenshot evidence; multi-tab CAS and uncertain
  browser reload acceptance must be observed before consumer promotion.

Focused client tests live in the **existing Vitest configuration** under
`card-studio-api.test.ts` and `CardStudioWorkspace.test.tsx`. Python
runtime and HTTP catalog tests run in the existing Card Studio PostgreSQL gate.
The existing `DEV_FAST` job remains the focused PR entrypoint.


## KGUI-CARD-STUDIO-01E: protected real-browser acceptance (operator-gated)

Card Studio's visual editor is source-integrated, but **that is not a
hosted-browser certification**. Reuse the existing `KAREN Browser Acceptance`
workflow with `scenario=card-studio` on approved exact-head `main`,
`deployment_target=preview`, and an independently verified deployed
`target_sha`. This is the canonical protected browser workflow, **not** a
new UI runner, template renderer, or auth/provenance authority.

The approved `karen-sanitized-browser-acceptance` environment must provide:
`KAREN_CARD_STUDIO_ACCEPTANCE_URL` (approved immutable HTTPS preview),
`KAREN_CARD_STUDIO_MUTATION_APPROVED=true` (dedicated disposable mutations),
and the existing real sanitized `KAREN_UX_EMAIL` /
`KAREN_UX_PASSWORD` secrets. The backend must have an explicitly enabled
`KARI_ENABLE_CARD_STUDIO_CRUD=true` **on that disposable preview only**;
the checked-in application setting remains **OFF**. Protected checks compare
the reviewed SHA to the running deployment both before and after acceptance.

`e2e/card-studio-live-acceptance.spec.ts` authenticates using the existing
approved sign-in fixture and checks genuine catalog/library HTTP 200 responses,
four browser viewports (390/768/1024/1440), document geometry, keyboard Tab
and slot movement. A second test on the disposable owner account exercises
create, reload/readback, concurrent two-tab CAS (real HTTP 409), revision
readback and archival. It then executes a **real committed HTTP request via
Playwright route.fetch**, drops only the browser response, verifies the UI
will not falsely claim success or automatically retry, reloads the tab and
manually replays the same idempotency payload. This proves deterministic
retry, not complete network-outage resilience.

No fake card evidence, UI-created policy grants, mocked 200 responses,
production publication, or cross-tenant fixture bypass is allowed. Traces,
video, automatic screenshots and HTML/JSON reporters are disabled for
authenticated trials. Independently approved local sanitized screenshot
capture remains optional; protected GitHub jobs upload no private browser
artifacts. The existing Card Studio PostgreSQL workflow checks the source
wiring contract; passing that source check is **not evidence that an
actual approved deployment/browser trial ran successfully**.


## KGUI-CARD-STUDIO-01F: principal-scoped editor state

The account-authenticated `CardStudioWorkspace` is a thin identity wrapper
around the existing editor. Its private `PrincipalCardStudioWorkspace`
subtree is **keyed by the canonical authenticated tenant ID and user ID**,
using the same principal scope as the existing unverified-idempotency
`sessionStorage` record. A logout or principal transition immediately
unmounts all previous owner-scoped template inventory, selected revision,
unsaved draft, authorization error, pending mutation and preview state;
a late fetch/commit completion from the previous component cannot populate
the newly authenticated owner's view. The backend remains the sole RLS,
RBAC, session and RuntimePolicy authority.

The existing focused Vitest suite explicitly covers A-to-B principal
switching with selected private data, a late A list response after B loads,
a retained uncertain A mutation that cannot appear in B's retry panel,
and immediate logout isolation. Source proof does **not** establish
an authenticated two-account browser run or certify cross-tenant enforcement
beyond the server's already existing real PostgreSQL tests.

`KARI_ENABLE_CARD_STUDIO_CRUD` stays disabled by default. The separate
approved disposable-preview browser release gate described above remains
mandatory for consumer promotion.
