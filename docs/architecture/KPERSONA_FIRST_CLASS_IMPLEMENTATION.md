# KPERSONA: First-class Persona Studio and Persona Runtime

Status: audited design and execution contract, not implementation-complete
Base: main at 2e3a46b85beb25c648ee46a9687408948a8cabdf (2026-10-21)
Owner: canonical ChatRuntime / PromptRuntime for execution; PersonaService for scoped definition persistence; UserModelRuntime for evidence-based personalization; UI for presentation only.

## Objective and non-negotiable boundaries

Persona becomes a durable, switchable, explainable, user-owned **communication and collaboration profile**, available from any Karen workspace. It never acts as a provider router, alternate agent, executable prompt policy, permission grant, or memory owner. The product must demonstrate observable differences on real local models and survive navigation/reload without pretending that save, activation, or memory succeeded.

One responsibility, one owner. Before adding modules, reconcile the existing contracts and consumers. Keep legacy chat and native assistant-ui on one backend contract; use AG-UI only as an authenticated projection of observed runtime events.

## Evidence from current main

| Surface | Current evidence | Risk and disposition |
|---|---|---|
| PersonaSettings.tsx | Live GET /api/personas/ and /preferences/me; POST/PUT custom persona and /preferences/switch; three hardcoded templates; local unsaved draft; preferred address stored in auth profile | Useful but a single-persona editor, no gallery/version/diff/preview; system_prompt editor suggests stronger authority than runtime permits |
| api_routes/users/persona.py | CRUD, preferences, switch and style endpoints; depends on bypass_user_context_func alias | Trace dependency implementation and tenant enforcement on every route before live exposure; name alone is not proof of a bypass |
| services/persona/persona_service.py | Tenant/user-scoped SQL against custom_personas and preferences; cache and style analyzer | Depends on Persona fields and Pydantic-like operations not present in inspected core/persona/contracts.py: **contract drift** requires import/runtime tests and canonicalization |
| core/persona/contracts.py | Enum-backed dataclasses for assistant/expert/creative and style fields | Does not match service expectations (system_prompt, is_system_persona, default_*, .dict(), etc.); don't create another model, converge at source |
| core/runtime/prompt/persona_contract.py | Explicit presentation allowlist; strips system_prompt, provider, models, tools, policies, memory writes, permissions | Correct authority boundary. Preserve, version, expand cautiously only for presentation semantics |
| tests/core/runtime/test_persona_prompt_authority.py | Tests allowlisted presentation fields and rejection of role/policy/routing escalation | Valuable unit proof; missing authentic end-to-end activation, continuity, tenant, multi-transport equivalence |
| core/personalization/runtime.py | Resolves evidence-backed preferences through canonical repository | Integrate only via narrow typed preference projection; no duplicate personal memory or inferred unconsented switches |
| KarenAssistantChat.tsx + dashboard SessionProvider | Mounted persistent Karen chat, feature-gated assistant-ui/AG-UI and legacy alternative | Place persona selector and explainable active-state UI in a shared shell, not duplicate per transport |

### Verified versus not verified

Source presence does NOT prove CRUD/switch works in a running deployment, that selected persona reaches model prompts, or that one tenant cannot access another's persona. Browser and database proofs remain outstanding. Check migration ownership between Supabase baseline and service SQL before changing schema. Do not alter production migrations in place.

## Product model: Persona is not Agent, Profile, or Model

- **Persona**: voice, register, verbosity, terminology, formatting, collaboration style, language presentation and user-approved task-specific communication preferences.
- **Profile/UserModel**: who the user is, personal facts, durable preferences, goals, evidence, provenance; owned by governed memory/personalization.
- **Agent**: governed tools, specialist execution and workflow eligibility; CORTEX decides eligibility, runtime enforces.
- **Model/provider**: centrally registered health and capability routing. Persona may request *output form* but never directly select a provider or grant a capability.
- **Task intent**: governs required response contract. For safety, legal/medical precision, and requested formats, task/system policy overrides persona aesthetics.

### Canonical resolution order

System / platform policy > tenant policy and RBAC > task/intent prompt contract > explicitly activated user persona's allowed presentation fields > resolved user preference projection > conversation-level ephemeral style override > model formatting constraints. Merge only known allowlisted fields, with documented per-field conflict rules. A user's explicit turn request may temporarily supersede a persona style when otherwise authorized; never persist that switch without user consent. Frozen persona snapshot resolved before the turn, with immutable persona_id, revision, resolution_source and safe fingerprint in execution metadata.

## Experience architecture: Persona Studio

### Discovery and daily use

1. Persistent, understated active-persona indicator beside the shared Karen composer, in both legacy and assistant-ui. Show active name and current status, not fake confirmation.
2. Persona switcher available from chat and a dedicated Persona Studio in Settings. Search, saved personas, built-ins, recent, duplicate, edit, restore, set default. Keyboard and mobile parity.
3. Persona creation wizard with short guided choices: conversational energy, concise/detailed, precision, language style, output layout, domain terminology. Advanced user can edit structured fields; raw prose is parsed into *proposals* with explicit validation and a preview before acceptance.
4. Side-by-side preview uses the **same test prompt and same provider/model** on a real local model, two authorized runtime requests, visible latency/token differences, never canned answers. Cost and execution receipts shown honestly. Preview must be clearly separated from ordinary conversation and not persist unless explicitly saved.
5. Save & activate separate operations with receipts; retryable errors retain an unsaved local draft. Display revision, effective fields, and why overrides were ignored. Never label a draft active.
6. Explain "Why Karen responded this way": non-secret applied persona revision, task override and provider constraints. Show only allowlisted sanitized metadata, not raw prompt or hidden reasoning.
7. Full accessibility (focus trapping/restoration, announcements, minimum targets, reduced motion), mobile responsive, and offline-readable saved personas if explicitly supported; writes fail honestly while offline.

### Proposed original differentiators (product hypotheses, not existing capability)

**Persona DNA**: a versioned, human-readable set of bounded style traits rather than an unrestricted system prompt. Each trait has type, allowed range, owner, source and override policy. Build a shared canonical schema with validation and explainability.

**Persona Lens**: inspect an existing assistant reply and show how the same factual content could be *presented* under another persona, clearly marked as a new model transformation, not the original reply or an independent fact check. Opt-in, never silently rewrite stored history.

**Persona Drift Guard**: monitor whether output style differs measurably from selected DNA without silently changing the user persona. Present suggestions backed by bounded local evaluations; user approves changes and can revert.

**Contextual Wardrobe**: user-authored rules such as "use concise professional style in work workspace; casual style in personal chat." Rules are narrow, deterministic, audited, opt-in and user-visible. On ambiguity, keep explicit selection. No model-initiated persona switch and no extra agent orchestrator.

**Persona Passport**: local export/import of a signed or checksummed, schema-versioned *presentation-only* persona document; no personal memory, secrets, tool permissions, or system authority. Validate, preview diffs, then explicitly import. Cross-tenant sharing requires a separate governed publication and moderation policy.

**Persona Lab**: reproducible benchmark of instruction adherence, factual stability, safe refusal integrity, latency, token cost, language conformity, accessibility/readability and perceived fit. Test selected real installed models; compare against an unchanged baseline. Never treat stylistic preference as evidence of task correctness.

**Relationship Dial**: a consent-based preference for degree of warmth, directness, initiative in conversation *presentation*, not proactive tool execution or implied intimacy. Stored as user preference, not inferred identity or behavioral manipulation.

Do not use persona-supplied arbitrary instructions to control tool use, network access, RBAC or provider routing.

## Technical design and ownership

### 1. Converge contract first (P0)

Search all imports of core.persona.contracts and uses of PersonaService; prove incompatible fields. Select one canonical validated domain representation aligned with existing migrations, route serializers, and prompt presentation allowlist. Adapt existing service/models and tests; delete dead aliases only after reference audit. No parallel persona managers. Fail imports loudly; remove mock NLP fallback from production only after auditing its current consumers and establishing explicit unavailable behavior.

### 2. Persistence/revisions (P1)

Extend existing tenant-scoped canonical persona repository with immutable revisions and active selection, not a new database. Migration is forward-only and additive: persona_revisions (tenant_id, owner_user_id, persona_id, revision, schema_version, presentation_json, fingerprint, created_by, created_at); persona selection with concurrency version if not already expressible by preferences; unique indexes scoped by tenant/user; ownership/RLS verification. Preserve current records through a reversible data transformation with an audit report. Never mutate legacy baseline migrations.

### 3. Runtime (P1)

ChatRuntime resolves persona once per execution through a typed PersonaResolutionService that delegates to the canonical PersonaService and UserModelRuntime. Sanitization happens in PromptRuntime; store per-turn revision evidence and policy-rejected fields in allowlisted observability, not a second prompt string. Snapshot at start prevents mid-stream switching. Request header or client-provided persona ID is a **preference request**, never authority. Use server-owned authenticated selection and verify user/tenant scope. Missing persona fails to default presentation honestly; no fabricated confirmation.

### 4. API (P1)

Thin authenticated routes for list/detail/create/update, revisions/diff/restore, preview (governed model execution), activate/deactivate, effective state and export/import. Idempotency keys, optimistic locking/ETags on mutations and consistent machine-readable errors. User/tenant derived only from authenticated context. No route-level prompt assembly. Audit every mutation and activation, including denied operations.

### 5. assistant-ui / AG-UI (P2)

Use assistant-ui Composer, Thread, Message, ActionBar, Tooltip and accessible primitives extensively for persona-aware chat controls and the Persona Lab preview threads. Do not fork conversation storage or instantiate one agent per persona. Shared React session store owns currently active backend-confirmed persona state; the shell selector serves both chat transports. AG-UI is optional and only needed to stream **observed** preview/token/status events through existing canonical projection when assistant-ui native stream benefits. Use allowlisted CUSTOM(karen.persona_applied) with persona_id, revision, label, status, correlation_id; never ship raw prompts, private traits or rejected authority fields. Legacy SSE receives semantically equivalent safe metadata. No STATE_SNAPSHOT or fake TOOL_CALL for a persona change.

### 6. Rollout (P3)

Config-driven OFF by default until model/browser proofs; phased internal -> opted-in tenant -> general. No new external AI requirement; local-first preview. Legacy clients work with old payloads through documented migration compatibility. No consumer packaging until human acceptance.

## Executable work breakdown and dependency order

| ID | Deliverable | Exit gate |
|---|---|---|
| KP-01 | Inventory all persona imports, actual APIs, SQL schema, active runtime prompt path; classify dead/misplaced code | Source-of-truth matrix, API auth/tenant test, import reproduction |
| KP-02 | Canonical typed persona schema and adapter migration, enforce presentation-only | All service/route imports, create/update/switch integration tests green; no mock production fallback |
| KP-03 | Durable persona revision/selection migrations and repository | Tenant isolation, rollback, concurrency and restart persistence tests |
| KP-04 | Single runtime resolution + prompt assembly receipt | Real local-model A/B; explicit persona different presentation, same permissions/provider policy |
| KP-05 | Shared shell selector, Studio gallery/editor, honest save states | Both chat transports, desktop/mobile keyboard, reload, error-state E2E |
| KP-06 | Preview Lab with governed real model calls | No canned reply; traceable model receipts; no preview saved as conversation |
| KP-07 | Contextual Wardrobe and Persona Lens opt-in | Deterministic precedence, opt-out, no automatic mutation |
| KP-08 | Drift Guard, evaluation dashboard and safe Passport | Version schema, import validation, no memory/secret exfiltration |
| KP-09 | Docs/screenshots, observability, live rollout readiness | Main quality, tenant RBAC, browser and production-like model acceptance, review and green merge |

## Observability

Emit structured persona.created, updated, activated, resolution_started/completed, rejected_field, preview_started/completed, fallback_unavailable, revision_restored. Every event carries tenant_id, user_id (redacted where needed), conversation_id, request_id, correlation_id, persona_id, revision, schema_version, resolution_source, result, and latency_ms. Never log persona secrets, full raw instructions, private facts, or hidden prompts. Metrics: activation failures, resolution fallback rate, version mismatch, preview latency, prompt-policy rejection count, across-transport mismatch.

## Test matrix (no fake successes)

- Unit: schema, normalization, revision conflict, allowlist, backward compatibility, preference precedence.
- Integration: API CRUD, ownership, cross-tenant forbidden, concurrent switches, real Postgres persistence, restart/reload, no unauthorized tools/providers/memory writes.
- Runtime: baseline versus persona on same real local model, persona snapshot stable during stream, CORTEX intent and system contracts retained, degraded metadata, AG-UI/legacy parity, cancellation/error terminal integrity.
- UI: save/activate receipts, no local draft mistaken for save, keyboard/mobile, switch across Agent Runtime/Planner/Settings, reload, create/edit/restore, errors.
- Adversarial: persona tries to escalate policy, inject tools or external provider, spoof tenant/persona IDs, inject malicious imported instructions or cross-user memories.
- Commands: python -m compileall src; pytest tests/ -q; ruff check src tests; mypy src; npm ci; npm run typecheck; npm run lint; npm run build; targeted Playwright browser suite; docker compose config.
- A successful skipped Playwright test is NOT acceptance. Prefer dedicated sanitized credentials and KAREN_KCHAT_ACCEPTANCE_REQUIRED=true where applicable.

## Merge policy

Use one existing branch/PR per coherent slice, avoid stacked PRs; keep main current. Merge only source changes with passing internal gates and no merge conflicts. Live behavioral claims require live proof; document unexecuted tests explicitly. Exact-head CI can be waived as a policy gate by a human, never represented as a completed check. Human consumer verification precedes packaging.

## Immediate engineering action

KP-01/KP-02 first. Confirm whether core/persona/contracts.py is active or legacy and identify correct canonical model in the repo before changing it. Resolve service signature/schema drift and the misleading freeform "core persona" UI copy. Then add immutable revision persistence and a real runtime applied-persona receipt. The new studio and proprietary extensions follow verified authority and persistence.


---

# Adversarial revision v2: Adaptive Communication Contract

Status: implementation requirements superseding conflicting earlier design language. This revision extends the existing architecture; it is not evidence that runtime behavior works.

## Architecture correction: three independent planes

1. **Execution authority**: system/tenant policy, CORTEX decisions, RBAC, ChatRuntime, PromptRuntime, tool/model registries and governed memory. Persona has no write or escalation privilege here.
2. **Communication contract**: explicitly chosen presentation and interaction traits, bounded schemas, per-field applicability, revisioned and user-owned.
3. **Personalization intelligence**: UserModel can produce evidence-backed suggestions and explicit-consent proposals. Inference does not silently update a persona or activate another persona.

Never encode provider preferences, permissions, routing, tool invocation, background tasks, memory recall scope, workflow selection, safety-policy toggles or tenant settings in Persona DNA. An interest in higher-quality explanations is a presentation preference, not permission for more reasoning tokens, a more expensive model, or deeper agent execution.

## Critical adversarial corrections (implement before the Studio)

### A. Canonical ownership and deletion protocol

KP-01 must trace import graph and actual runtime calls for persona models, APIs, dataclasses, SQL, settings, prompt filtering, active persona resolution, streaming and UserModel. Produce an owner matrix with active/misplaced/legacy/dead classification. Confirm whether core.persona.contracts is canonical or historical *before* editing or deleting it. Preserve the existing PromptRuntime presentation allowlist as authority; a second sanitizer is not a substitute. Every removed alias requires a reference audit.

Acceptance: production imports and one end-to-end resolved prompt path work; no duplicate store/resolver/renderer; old serialized payloads still deserialize or fail explicitly with migration guidance.

### B. Deterministic field-level resolution contract

The previous single ranked merge list is insufficient because fields can be absent, prohibited, conflicting, or context-specific. Introduce a typed, pure resolver returning per-field provenance:

- Input: authenticated tenant/user/session; server-selected active persona revision; validated task/intent presentation contract; explicitly requested turn-level style adjustments; bounded UserModel presentation preference projection; provider output constraints; scoped workspace rules.
- Fixed authority: platform > tenant/RBAC > intent/task response contract > explicit turn request for allowed presentation fields > user-activated persona > opted-in contextual rule where explicitly authorized > evidence-backed preference defaults > conservative presentation default. Provider formatting feasibility is a *final constraint*, not a higher-trust instruction.
- A conversation-scoped persona override is separate from a one-turn style request. A pinned selection wins over auto-switch. Ephemeral overrides expire on their declared scope and never persist implicitly.
- For each field, output: value, source, source_version, applicability, precedence_reason, suppressed_sources, and constraint_reason; expose only safe explainability labels to users. Missing, null, reset and inherited are distinct operations.
- Reject unknown schema keys and prohibit freeform prompt or arbitrary instruction injection into model-level system authority.
- Version resolver rules and generate a canonical resolution fingerprint from *non-secret semantic policy inputs*, not raw sensitive prompts.

Acceptance: table-driven tests cover all pairwise conflicts, missing/deleted persona, workspace change, requested language, accessibility constraints, stale selection, and simultaneous edits. Determinism is verified across repeated resolutions.

### C. Execution snapshot and switching semantics

At request acceptance, ChatRuntime freezes persona_id, revision, schema_version, resolved fields and fingerprint under the authenticated context. Streaming chunks, retries, tool returns, resumptions and AG-UI projection refer to that snapshot. A switch during a response applies only to the next turn unless the current run is explicitly cancelled and restarted. Retried calls cannot accidentally re-resolve a newer persona. Conversation branch replay uses its original metadata, never silently reinterpreting history. Persona deletion never removes historic non-secret provenance required for audit.

Activation must have a server receipt, optimistic version, idempotency key and audit event. Reject unauthorized IDs and stale writes without altering the current selection. Cross-tab state uses server reconciliation rather than last-writer-wins local UI guesses.

### D. Capability-aware rendering without model steering

A bounded style compiler in PromptRuntime maps resolved fields into the model's permitted presentation instructions, under token budget and output mode. It may degrade unsupported formatting explicitly. It cannot select models, change budgets, trigger tools, or modify CORTEX classifications. Track requested_style, applied_style, suppressed_fields, renderer_version and outcome with safe metadata. A safety-critical or strict JSON task can override style where needed.

Acceptance: same persona on multiple registered healthy local engines yields truthful fidelity status; strict JSON, citations, multilingual presentation and safety responses preserve task contracts. Persona must not change actual_provider or any RBAC eligibility.

### E. Data lifecycle and privacy

Tenant/user ownership, server-derived identifiers, scoped uniqueness and RLS are tested against the real PostgreSQL schema. Revision records are immutable, activation pointers mutable with optimistic locking; transactional creation/revision/selection prevents orphaned states. Define retention, deletion, tombstone and rollback behavior before schema changes. Never import secrets, memories, executable templates or arbitrary scripts. Export is data-only: strict schema/version, origin metadata and checksum for integrity; cryptographic authenticity requires separately governed signing keys and verification. Import shows a quarantined validation/diff screen and never activates automatically.

The earlier phrase "reversible data transformation" must not imply down-migrating and destroying later user revisions. Document rollback by feature flag plus forward-only compensating migration as appropriate.

### F. Persona Lab isolation and scientific validity

Preview uses the canonical runtime execution path but a separate preview purpose and storage policy. It is authenticated, rate-limited, RBAC/tenant-scoped, cancellable and tool-disabled by default; it performs no external side effects or durable chat-history writes. Preview prompts never receive unrelated private memories. Same factual task, provider/model, parameters, context policy and randomization controls, with token/latency receipts. Seed determinism only if the engine actually supports it. Separate objective task correctness and safety preservation from subjective stylistic fit.

Compare paired real-model outputs in randomized display order; include evaluator calibration, blinded user votes and repeat trials to estimate variability. Do not claim persona improvement from one anecdotal output. If an evaluation model is used, register its provider and disclose cost, bias and confidence; a local deterministic metric should be used where sufficient. Cancellation and failures are visible, not replaced with fabricated outputs.

### G. UserModel feedback governance

User actions such as "shorter", "more examples" or "less formal" create a one-turn adjustment by default. Offer explicit "Apply to this conversation" or "Update my persona" choices, with a diff and activation receipt. Separate behavioral observation from authorized personalization. Do not infer sensitive traits, social intimacy, personality or protected attributes from conversations. Model-generated proposals carry source and confidence, expire, and require a user's explicit confirmation before durable changes.

### H. Adversarial trust boundary tests

Test attempts to inject provider selection, new tools, tool permissions, cross-tenant references, prompt role boundaries, raw hidden prompts, memory writes, background execution, RLS bypass, SSRF-like imported links, hostile unicode/invisible characters, oversized profiles and schema-bomb inputs. Verify denial is audited and the unchanged baseline remains safe. Denial metadata must not reveal secret values. For previews, explicitly prove no tool invocation or side-effect persists even if the adversarial persona asks for one.

## Next-generation product design: progressive disclosure, not a control cockpit

The top-level surface is a small active persona selector in the shared composer. Users can start with a curated baseline, preview with a simple before/after, and explicitly activate. Advanced Studio shows editable Persona DNA, revisions, contextual rules and evidence. The UI must not present a slider percentage as a guaranteed numeric model behavior. Use qualitative anchors and show estimated adherence, including confidence/limitations.

The Persona Studio is a new *view of the canonical state*, not a client-side store of truth. assistant-ui owns the reusable composer/thread/message interaction components; Karen owns visual language and accessibility. A single backend-confirmed persona session state serves assistant-ui and legacy chat. AG-UI is optional event projection, not persona CRUD or orchestration.

## Additional original capabilities as hypothesis-driven work

1. **Persona Contract Inspector**: explain, per message, selected persona versus applied/suppressed traits, with privacy-safe provenance and constraints.
2. **Adaptive Fidelity**: detect when the available model cannot reliably satisfy particular traits; show truthful reduced-fidelity status instead of claiming behavioral precision.
3. **Intent-Preserving Style Transform**: an opt-in Lens operation with semantic constraints; compare structured facts/citations and flag possible distortions rather than declaring equivalence.
4. **Correction-to-Preference Loop**: promote repeated explicit feedback into opt-in proposed revision diffs, not automatic memory/persona writes.
5. **Accessibility Presets**: presentation defaults for readability and format without inferring any user medical or disability status.
6. **Persona Contract Test Kit**: a versioned corpus that tests every published Persona DNA revision against safety, factual invariants and typical task families.

Do not schedule Drift Guard model evaluations on every response. Begin with on-demand or sampled, budget-governed checks. No new agent, routing framework, vector collection or evaluation database unless the existing telemetry and canonical repositories are insufficient and the insufficiency is proven.

## Reprioritized implementation waves and acceptance gates

| Gate | Scope | Required proof |
|---|---|---|
| P0 / KP-01 | Inventory real ownership, imports, SQL, runtime wiring, security boundaries | Owner matrix, import reproduction, full reference map |
| P0 / KP-02 | Canonical typed schema, adapters, presentation authority, compatibility | Serialization/CRUD tests, policy denial, import checks |
| P0 / KP-03 | Revision/activation transactional persistence, isolation and concurrency | PostgreSQL integration, tenant RLS, restart/rollback, racing activations |
| P0 / KP-04 | Per-field resolver, immutable turn snapshot, safe receipts, capability renderer | Prompt/stream/retry tests; actual model no permission change |
| P1 / KP-05 | Shared composer selector, creation/editing, revision compare, inspection | Browser reload/navigation, keyboard/mobile, truthful failure states |
| P1 / KP-06 | Governed preview Lab, real-model paired evaluations | Same-runtime paired runs, no tools or side effects, comparison validity |
| P2 / KP-07 | Opt-in scoped wardrobe and Lens | Deterministic rules, factual stability checks, explicit consent |
| P2 / KP-08 | Sampled drift evaluation, correction loop, safe import/export | No silent mutations; rate limits, import fuzzing, reproducible tests |
| P1 / KP-09 | Accessibility, instrumentation, documentation, screenshots and feature flag rollout | All meaningful quality gates and human browser acceptance |

Milestones may merge independently only when their security and contract gates are proven. Never treat exact-head CI waiver as a successful test. Do not stack unnecessary PRs; update this existing branch until its coherent foundation is green. Preserve a clear distinction between design committed, code implemented, tests run and production enabled.

## Required proof artifacts

- Ownership/reference audit containing explicit surviving owners and deletion reasons.
- Schema contract plus forward-only migration and documented rollback/retention rules.
- Golden precedence table and deterministic conflict resolution tests.
- Real PostgreSQL RLS and concurrency results.
- Prompt/stream/AG-UI/SSE equivalence tests, including cancellation and retry.
- Real local-model baseline comparisons with provenance, sample sizes and failures.
- Playwright screenshots in appropriate docs or README after visual inspection.
- Security test report: injection, tenant, RBAC, import, preview side effects and logging.
- Telemetry report: selection, fidelity, drift, failed activations and resolution latency.
- Final merge-ready checklist distinguishing verified tests from waived external gates.

## Final architectural decision

Persona is a governed **adaptive communication contract**, not an agent, operating mode, personality simulator, provider preference or alternative prompt authority. User intent and explicit choice control its durable evolution; UserModel recommends; PromptRuntime compiles; ChatRuntime resolves and snapshots; CORTEX retains decision eligibility; the registered execution engine runs; UI displays observed truth.
