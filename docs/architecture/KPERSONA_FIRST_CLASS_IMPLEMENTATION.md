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


---

# Persona 3.0 revision: User-Owned Purpose Personas and Scoped Learning

Status: **design contract only**. Supersedes the v2 claim that personas are exclusively presentation configurations. No implementation or test result is implied.

## Product contract and real user journeys

A user can create any number of personas for distinct *purposes* such as Business, Graphic Design, Family, Personal, Study, Writing, Contracting or Customer Support. These labels are user-defined organizational tags, not built-in RBAC roles or hardcoded intent routes.

John can create a "Design Studio" persona with approved design vocabulary, brand assets, preferred visual direction, feedback style and references to design projects. Karen can recognize a request's design context and **suggest** using Design Studio, or deterministically select it according to a previously authorized scoped rule. The same user can simultaneously own Business and Family personas with non-overlapping resources. Deleting or deactivating Design Studio must not delete John's global UserModel or his unrelated conversations.

Initial user journeys with acceptance criteria:

1. **Create**: John describes "Be my graphic-design collaborator for my business"; the wizard proposes a persona name, intent, communication DNA and optional knowledge scopes. Nothing persists or receives permissions until explicit confirmation.
2. **Attach**: John explicitly adds approved design projects, assets, references, and preferences. The persona stores *references and grants*, not copies of all private memories or files.
3. **Use**: John activates Design Studio in the shared composer; ChatRuntime obtains a frozen effective-context snapshot from the authorized resources; the response contains persona and context receipts.
4. **Teach**: John says "Use less gradient in my designs." It applies to the current response where feasible; Karen offers to save it as a design preference in this persona. Approved feedback is versioned and reversible.
5. **Adapt**: With consent, aggregated outcomes can produce ranked suggestions for Design Studio. Observed repetitions are not silently converted into durable preferences. All suggested changes have provenance and require review.
6. **Switch**: John selects Family. Business-specific resources are not recalled under Family unless independently authorized for this new scope, even if the model saw them in a previous context. Existing thread context must be privacy-classified; warn or start a fresh scoped conversation when necessary.
7. **Share**: John exports a safe template that carries presentation DNA and optionally non-sensitive, separately approved domain instructions; no private content, grants or memory. Team publication is distinct from private template export.

## Four separate concepts, not one overloaded persona field

**Persona Definition**: user-owned identity (name, purpose, tags, appearance, collaboration contract, source/version, defaults). It does not confer capabilities.

**Persona Knowledge Scope**: explicit references to existing authorized memory, projects, files, business/household contexts and knowledge collections. Enforce tenant, user, resource ACL, consent and purpose on every retrieval, not merely at persona creation. Persona membership is a *filter* on already-authorized resources, never an independent grant.

**Persona Learning Overlay**: evidence-backed, purpose-bound proposals and explicitly approved preferences with confidence, provenance, expiry, revocation and revision history. NeuroRecall retrieves and ranks; existing governed memory repositories persist; UserModel derives suggestions. No new vector DB, standalone persona memory engine or silent persona rewrites.

**Persona Execution Context**: runtime-owned, immutable per-turn assembly of definition revision, context scope, authorized memory receipts, user intent, communication contract and existing CORTEX/tool eligibility. A design persona can recommend a governed design workflow, but normal CORTEX/runtime permission checks alone determine execution.

Strict authority invariant: **persona never provides new permissions, tools, provider routing, tenant access, model budget, system-prompt authority or automatic external actions**. A "designer" persona is NOT a graphic-design agent. It can specialize the authorized collaborative experience while existing registered skills/tools do actual design operations.

## Required canonical data model (logical contract, adapt to actual migrations)

- persona_definitions: tenant_id, owner_user_id, persona_id, name, description, purpose, tags, visibility (private default), lifecycle_status, created_at, updated_at.
- persona_revisions (immutable): persona_id, revision, schema_version, communication_dna, collaboration_preferences, purpose_contract, compatibility_metadata, non-secret fingerprint, created_by, created_at.
- persona_scopes: persona_id, resource_type, resource_id, permitted_use, granted_by, consent_reference, expires_at, revoked_at, revision. Association is not ACL authorization.
- persona_preference_events: persona_id, field_path, candidate_value, source_type, provenance_reference, observed_at, confidence, consent_state, approved_by, approved_at, supersedes_event_id, expires_at. Keep raw personal/sensitive content in its existing governed store; references only where possible.
- persona_context_rules: persona_id, workspace_id or task_family, selection_mode (suggest | explicit-pinned | opt-in-auto), specificity, enabled, revision.
- persona_activation: authenticated tenant/user/session/conversation scope, active_persona_id, active_revision policy, selection_version, idempotency_key, updated_at.
- persona_execution_receipts: correlation_id, selected persona revision, scoped retrieval decision identifiers, effective presentation fingerprint, suppressed-field reason codes, tool eligibility invariant, fallback and fidelity metadata. Persist through the canonical runtime telemetry/audit contract with retention policy, not a second telemetry system.

Names are *logical entities*, not a mandate to add seven tables. Map to current PersonaService SQL, PostgreSQL/RLS schema, UserModel preferences, governed memory metadata, and runtime receipts first. Add only demonstrably missing relations by forward-only migrations; keep tenant/owner unique indexes and protect read paths with RLS and application checks. Avoid copying project content into persona definition rows.

## Learning lifecycle and control model

Explicitly distinguish:

- **User-declared**: an approved rule, such as "avoid gradients for this brand"; effective immediately within its selected purpose.
- **Observed**: a trace or explicit correction suggesting a preference. Retain only under opt-in collection and appropriate retention; it is not a rule.
- **Proposed**: evidence-based candidate with provenance, number of independently verified examples, confidence and applicable context; safe for user review.
- **Approved**: revisioned preference active only in its specified persona/context, with rollback and explainable application.
- **Rejected / expired / revoked**: excluded from effective resolution and further reuse where applicable; deletions propagate to indexes/caches.

UserModel proposes; PersonaService records persona-scoped choices; NeuroRecall performs constrained retrieval; NeuroVault/governed memory owns storage/deletion. Never train or fine-tune underlying model weights as a side effect of persona preference learning. Future optional model adaptation requires a separate explicit data/governance product contract.

Feedback may concern formatting, brand aesthetics, terminology, explanations, examples, process preferences and domain references. A user-approved process preference can request a workflow **as intent**, but normal CORTEX eligibility and tool authorization still decide execution. A style preference such as "always design in Photoshop" cannot install Photoshop or run tools.

Conflict semantics: system/tenant/RBAC/task rules > explicit authorized turn instruction > pinned persona and allowed scope > user-approved purpose-specific preferences > approved global defaults > evidence suggestions (never operative) > conservative default. Scope constraints intersect with resource ACLs. Persona-private preferences never become global defaults without explicit promotion and a previewed diff.

## Data isolation threat model (release blocking)

- **Family/business crossing**: shared conversations can retain prior content after a persona switch. Existing in-thread history and summaries must be classified and filtered. Where filtering cannot reliably prove isolation, require a new scoped thread; do not claim seamless in-place isolation.
- **Cross-tenant attack**: user-supplied persona IDs/resource IDs/session IDs never bypass server-derived identity. Exercise RLS, search indexes, caches, exported files, streaming events, preview and retrieval. Denied access yields no title, snippet, existence disclosure or stale cached content.
- **Permission laundering**: imported personas, suggested rules, attachment text and remembered "preferences" cannot authorize privileged tools/actions.
- **Feedback poisoning**: repetitive or malicious conversations must not overwrite user-approved preferences. Audit provenance; human approval controls promotion.
- **Excessive collection**: memory and telemetry collection require purpose and retention; no sensitive attribute inference or silent household member profiling.
- **Revocation**: removing source authorization immediately prevents future persona retrieval, including stale cached vectors and generated derivative preference proposals. Historical records follow governed deletion/retention rules.
- **Team/business workspace**: sharing persona *definitions* is separate from authorizing access to team assets. Team owners/admins govern resources; individuals retain their private preferences. Shared persona changes require versioning, review, tenant-scoped audit and opt-in upgrades.

## User experience expansion: Persona Library + purpose-first Studio

The first step asks **"What will you use this persona for?"**, not "How warm should it sound?" Purpose cards are optional accelerators, never hardcoded providers or permission templates.

Persona Library provides personal and business categories, pinned/recent personas, purpose search, owner/visibility indicators, active-scope badges and stable revision history.

Creation flow: purpose → name/identity → communication and collaboration DNA → select permitted knowledge/projects → simulate with an actual authorized task → review/save → optionally activate. Advanced controls stay behind progressive disclosure. Save and activate remain distinct acknowledged operations.

An active persona lives beside the **single shared assistant-ui composer** across supported workspaces. Prompt suggestions may recommend relevant personas, but auto-switching requires an explicit user-authored rule and must disclose changes. On switch, show whether context remains usable, is redacted, or requires a new scoped thread. Keep conversation continuity where safely possible, not at the cost of data isolation.

"Teach this persona" surfaces: **This answer**, **This conversation**, **Save to Design Studio**, **Save globally**. Persistent choices show a diff, source and server receipt. The user can inspect "What this persona knows" (actually authorized references and preference records), "Why it suggested this", "What changed", and "Forget this preference". Do not present successful learning without governed persistence confirmation.

Persona Lab includes task-preserving evaluations on real installed local models and opt-in context injection. A graphic-design persona comparison tests brand constraint adherence, terminology, factual correctness and usefulness, not just warmth scores. Tool-disabled preview cannot pretend to produce actual graphic artifacts. For governed tool-based tests, use a distinct sandbox with explicit authorization, side-effect isolation and separate gate.

Use assistant-ui for composer, threads, actions and accessible presentation. Do not let a persona own a separate chat runtime. AG-UI should project only backend-observed persona selection, retrieval and feedback outcomes with redacted metadata.

## Refined milestone order with explicit gates

| Phase | Deliverable | Release-blocking proof |
|---|---|---|
| KP-01 | Current-source ownership and usage inventory including persona/service/UserModel/NeuroRecall | Active import/call map, classification, no duplicate ownership |
| KP-02 | Canonical validated purpose-persona schema with safe communication contract | Old payload compatibility, permission-escalation rejection, serialization/import proof |
| KP-03 | Immutable revisions, scopes, activations, feedback state and PostgreSQL persistence | Tenant isolation/RLS, cross-persona isolation, races, rollback, restart |
| KP-04 | Runtime scoped resolver, per-turn snapshots, memory ACL intersection, truthful receipts | Real retrieval/prompt/stream proof; tool/provider/RBAC invariants |
| KP-05 | Persona Library, purpose-first Studio, shared assistant-ui composer and active state | Create/activate/switch/teach/reload E2E; accessible mobile/desktop |
| KP-06 | Governed Persona Lab with domain-specific factual and style evaluation | Paired real-model runs, blocked side effects, contamination tests |
| KP-07 | Scoped selection rules, Lens and workspace-purpose recommendations | Determinism, consent, no unintended context crossover |
| KP-08 | UserModel evidence proposals, learning approval/rejection, drift/fidelity, safe Passport | No silent durable edits, data lineage, deletion/revocation, poison tests |
| KP-09 | Screenshots/docs, observability, user acceptance and feature-flag rollout | Complete security, persistence, browser and local-model gates |

**Early vertical slice**: One user creates Design Studio, authorizes one project reference, selects it, receives one real response grounded only in the allowed scope, approves one correction, sees that correction on the next turn, switches to Family and cannot retrieve the design context. Prove this before elaborate galleries, sliders, adaptive ranking, or novel agent infrastructure.

## Non-negotiable proof scenarios

1. Alice and Bob in different tenants use identical persona names and resource identifiers; no cross-tenant existence/read leak.
2. John changes Design Studio midway through a streaming response; its immutable revision persists to final receipt; the next turn uses the new revision.
3. "Remember I prefer monochrome layouts" updates **only** the explicitly approved Design Studio scope; Business and Family remain unchanged.
4. A revoked brand project disappears from future retrieval and cannot be reintroduced through a stale vector/cache hit.
5. Conversation handoff from Business to Family either filters every restricted prior context or requires a new thread, with truthful user notification.
6. An imported "CEO" persona demanding admin tools, external model use, or secret disclosure cannot change eligibility, provider policy or memory rules.
7. Preview and failure paths never mark save, activation, persona learning, tool execution or model output successful without corresponding backend receipt.
8. An unapproved evidence-derived proposal never becomes active despite repeated exposure or multiple concurrent sessions.
9. A registered local model can produce a valid Design Studio response with stable task requirements even when output style fidelity is degraded.
10. Shared team persona updates cannot overwrite a member's private preferences or broaden resource ACLs.

## Delivery instruction

Stay on PR #501 and its existing branch. First reconcile actual code ownership and migrations before changing implementation. Maintain one ChatRuntime/PromptRuntime, one PersonaService persistence owner, one governed memory stack and one CORTEX permission decision path. Commit this revised **design** without claiming implementation, passing tests or live learning. The immediate next work is KP-01/02 with the early vertical slice guiding acceptance.


---

# Persona 4.0 extension: Named Roles, Industry Skills and Human-Centered Studio

Status: design-only extension. This supersedes any assumption that a persona is merely a style preset. It does not imply implementation, a deployed UI, or verified runtime behavior.

## Product North Star

A user can say: "Create Troy, my graphic designer, skilled in luxury branding, typography and packaging. Learn how I like to work." Karen proposes an intelligible, editable specialist profile and explains what the role can and cannot do. The user confirms persistence and separately authorizes any knowledge attachments. The same model supports business, entertainment, education, personal life, engineering, household organization and arbitrary user-created categories, with no industry-specific runtime fork.

**Persona = named user-owned collaboration identity + purpose/role + declared specialties + communication contract + scoped knowledge references + approved learning overlay + optional eligible skill bindings.** It is never a separate AI, agent runtime, security principal, model, professional credential or source of tool authorization.

## Adversarial corrections before implementation

1. **Skill ambiguity**: separate *claimed familiarity* (taxonomy or user-declared area of focus), *demonstrated skill* (measured performance with evidence and model/version), and *executable capability* (existing registered tool/workflow with manifest, RBAC, dependency health, input schema and approval). Showing a skill badge must never imply the tool is installed or permission granted.
2. **Title spoofing**: display profession labels as user-selected roles, not verified licenses, real human identity, certification, work history or guaranteed expertise. Never invent resumes or experience years; sensitive sectors need appropriate caveats and policies.
3. **Unbounded learning**: the persona may accumulate approved preferences and references but must not automatically edit its own definition, learn secrets, infer household member profiles, or fine-tune models. UserModel proposes; governed memory owns evidence; PersonaService owns approved persona revision; revocation invalidates relevant caches.
4. **Skill/plugin privilege laundering**: persona-suggested skills cannot install plugins, execute tools, alter model selection, approve actions or widen scopes. CORTEX evaluates eligibility, runtime checks manifest/RBAC and performs actions with existing consent.
5. **Industry proliferation**: a data-driven catalog of industry/role/skill descriptors is discovery metadata, not separate business/entertainment/family engines. User-created titles and tags work without requiring catalog entries.
6. **Mixed-use privacy**: same-name personas can exist across tenants; team template adoption cannot attach original owner's data. Personal, family and business resources remain ACL-intersected even in cross-workspace chat. Switch creates a fresh scoped thread when history cannot be safely filtered.
7. **UX honesty**: don't turn sliders into invented behavioral guarantees, imply that a static model has mastered a skill, or show saved/learned states without committed server receipts. Avoid mandatory multi-page wizards.
8. **Assistant UI dependency**: reuse installed shared assistant-ui primitives only after dependency/import/bundle checks; no second chat state or runtime. AG-UI events are optional authenticated projections with schema-versioned receipts, not new control paths.
9. **Learning economics and quality**: cap proposal frequency, evaluation tokens, retrieval budget and derived memory retention. Measure whether approved preferences improve user outcomes without reducing factual fidelity; observe opt-out and deletion.
10. **Race and downgrade**: immutable persona, skill catalog and tool registry versions belong in each turn snapshot. Version changes affect next turn, not in-flight retries; unavailable skill means honest degradation rather than a fabricated action.

## Canonical, typed contracts (extend existing owners before adding tables)

- PersonaIdentity: persona_id, tenant_id, owner_user_id, display_name, avatar_reference, title, purpose, industry_tags[], role_tags[], visibility, ownership_scope, created_at, updated_at.
- PersonaSkillDescriptor: skill_id, taxonomy_version, display_name, kind (domain_specialty | collaboration_method | executable_binding), origin, declared_proficiency (optional, explicitly user-provided), measured_evidence_reference (optional), manifest_binding_id (optional), review_state, published_version. Never turn declared_proficiency into verified expertise.
- PersonaSkillAssociation: persona_id, revision, skill_id, preference_weight, context_scope, added_by, consent_reference, disabled_at. No permission columns and no credential storage.
- PersonaRevision: immutable definition plus purpose contract, communication DNA, preferred methods, skill associations, safe knowledge-scope references, source fingerprint and author audit data. Proposals are independent until accepted.
- PersonaLearningProposal: persona_id, scope, proposed field-level change, evidence references, observation provenance, confidence/calibration metadata, consent state, timestamps, expiry and revocation. Approved changes create a new revision via the canonical PersonaService.
- PersonaExecutionSnapshot: requested persona_id, resolved revision, registry versions, eligible skill receipts, permitted memory scopes, effective communication traits, applied/suppressed reason codes, correlation_id; hash excludes secrets. Persist receipt through existing runtime telemetry and audit.

Use existing tables/config/registries where suitable. If a skill registry already exists, reference it by canonical identifier; do not create a PersonaSkill runtime registry alongside plugin manifests. Do not hardcode industries, specialist titles or tool names into API routes.

## Single runtime path

Authenticated request -> canonical ChatRuntime -> persona selection/activation and ACL resolution -> immutable persona+skill+knowledge snapshot -> CORTEX intent/policy decision -> scoped NeuroRecall/UserModel preference context -> PromptRuntime compiles *presentation and collaboration* constraints -> existing provider router/model executor and governed skills/tools -> streamed response with safe receipts -> persistence/telemetry.

Priority: platform safety/policy/tenant constraints > authenticated user turn intent > active approved persona revision and authorized references > approved scoped preferences > approved global defaults > non-operative suggestions. Persona methods or titles cannot override execution authority. If a user specifies a persona per message, it is an authorized selection input, not a permission request.

## Studio usability contract

The main Library shows human-readable cards: name, role, short purpose, a few skills, source/visibility and actual activation status. The primary CTA is **Create a persona**. New users can type one sentence; assistant-guided setup proposes a name/title/industry/specialties, shows an editable summary, and requires explicit **Create** confirmation. Do not ask for technical setup, memory internals, provider settings or skill IDs.

Progressive disclosure:
- **Quick create**: purpose -> suggested name/title/specialties -> preview summary -> create -> optionally activate.
- **Working persona**: current projects/approved knowledge, editable preferences, teach/correct action, skill availability and recent activity with receipts.
- **Advanced**: revision compare, communication traits, scoped attachment ACLs, tool bindings (view only unless separate authorized management), provenance, lab testing, import/export.

Every persona card supports: Open chat, Edit, See skills, What it knows, Teach, Revision history, and deactivate/archive when authorized. Avoid overcrowding the card: expose secondary actions via an accessible overflow menu.

In the shared assistant-ui composer, display the active persona name/title and a single switcher. Do not duplicate composers across workspaces. Persona changes survive navigation only after backend acknowledgement. Workspace recommendations are suggestions unless an opt-in deterministic rule was approved. AG-UI conveys server-observed changes and preview events but does not persist choices.

Make empty, loading, error, offline/degraded, unauthorized, no-tools-installed, and knowledge-revoked states understandable. Mobile and screen-reader users can complete create/activate/switch/teach/revert flows with keyboard and accessible labels. Do not rely on avatar images/colors to distinguish identities.

## Skill evidence and growth ladder

- Declared: "Troy focuses on typography." User-authored descriptor, no validation of professional expertise.
- Available: an existing registered design-related tool is enabled, healthy and authorized in this execution context. Display clearly if unavailable.
- Practiced: with opt-in, preserve bounded task/outcome evidence in governed stores; avoid storing raw private designs needlessly.
- Improved: UserModel proposes a versioned preference based on feedback; user can review diff, accept/reject/revoke. No silent persistent adaptation.
- Evaluated: Persona Lab compares actual task outcomes on an authorized model, with tool-disabled preview by default. Label self-report versus objective evidence and separate style fidelity from factual accuracy.

Skills can be grouped by industry and search without assuming a fixed hierarchy. One persona may span multiple industries. Templates are portable role/skill/communication definitions, not privileged instruction bundles.

## Launch acceptance journey

A user creates "Troy (Graphic Designer)" with typography, branding and packaging specialties; saves a confirmed definition; attaches a permitted brand project; activates Troy; gets a genuine local-model response citing only permitted context; suggests "prefer high-contrast minimalist designs"; reviews and approves a scoped revision; sees the preference applied on the next turn and receipt; switches to an independently scoped Family persona; observes no brand content leak; reopens app and confirms durable persona state and revisions.

Test denial of cross-tenant/persona access and of unapproved skill execution; revoked assets cannot be recalled through stale caches; concurrently edited/activated versions remain atomic; assistant-ui build imports succeed; streamed and non-streamed receipts agree; mobile and accessibility checks pass.

## KP plan deltas

- KP-01: inventory persona, skill registry/plugin manifests, user model, tool authorization and active assistant-ui dependency paths; record surviving owners.
- KP-02: reconcile PersonaService/dataclass plus typed name/title/industry/skill contracts and migration compatibility without duplicating registries.
- KP-03: persist immutable skill associations alongside persona revisions and scope/consent changes, with RLS and concurrency proof.
- KP-04: resolve eligibility and knowledge access at turn boundary; report actual capability rather than promised expertise.
- KP-05: prioritize one-sentence creation, understandable cards, shared switcher, teach/change review and screen-reader/mobile flows over DNA sliders.
- KP-06: measure local-model domain task preservation and skill availability; tool-disabled previews cannot fake design artifacts.
- KP-07/08: deterministic recommendations and user-approved learning; versioned skill evidence and bounded evaluation; no new agent.
- KP-09: plain-language onboarding, retention/privacy docs, receipts, screenshots and tested rollout flags.

**Exit criteria**: first-use user can create, understand, activate and improve Troy without learning implementation vocabulary; runtime cannot cross persona knowledge boundary or grant tool privileges; every claimed save/learn/execute event has backend proof. Remain on PR #501 until verified. 


## Persona Skills & Learning Data companion

See [Persona Skills & Learning Data Guide](PERSONA_SKILLS_LEARNING_DATA_GUIDE.md) for user/admin/developer flows, the Data Needs Advisor, industry-neutral evidence categories, ingestion governance, consent, dataset sufficiency, and skill evaluation. The companion guide is design-only and does not imply a deployed training capability.


---

# Persona 5.0: Full Adversarial Implementation Plan

Status: design and implementation contract, not production code or test verification. This section governs conflicting earlier plans. Remain on PR #501.

## Mission, exit test and non-goals

A person creates Troy (Graphic Designer) from one sentence, explicitly connects an authorized brand project, activates him in Karen's persistent chat, receives a real local-model result using only permitted context, approves a design preference, sees it applied on the next turn, and safely switches to Family without leakage. Personal Facts, Turn Intelligence, and Persona Studio must project the same authoritative events.

No separate persona agent, memory engine, per-industry runtime, second Facts writer, skill registry, telemetry database, model training or required dataset. CORTEX decides, ChatRuntime executes, PromptRuntime compiles presentation, NeuroVault governs persistence, UserModel proposes, PersonaService persists personas, and assistant-ui displays backend truth.

## Adversarial owner matrix

| Responsibility | Canonical owner | Prohibited competing owner |
|---|---|---|
| Auth/session/tenant/request identifiers | Thin ingress and established auth | Persona prompts / React |
| Per-turn orchestration and frozen execution context | ChatRuntime | Advisor / AG-UI / route |
| Intent and RBAC policy | CORTEX + runtime authorization | Role or skill labels |
| Persona CRUD, revisions, activation, approval | Existing PersonaService | Another persona database |
| Formation/admission | MemoryRuntimeManager / Formation evaluator | Facts UI or persona |
| Durable write and deletion | NeuroVault governed write path | Persona knowledge copy |
| Derived Facts | Existing profile_fact projection | New fact writer |
| Preference suggestions | UserModel | Silent persona mutation |
| ACL-filtered context, ranking and dedupe | NeuroRecall + runtime access checks | UI or persona prompt |
| Skill/tool execution | Existing plugin/skill manifest and runtime | Persona descriptor |
| Presentation instruction compilation | PromptRuntime | Route / UI |
| Conversation, composer and actions | Shared assistant-ui | Persona-specific chat runtime |
| Optional observed streaming | Existing AG-UI bridge | Authoritative state owner |

KP-01 must confirm exact live code owners, imports, database migrations, call paths and compatibility shims before edits. Classify every duplicate as active, misplaced, legacy, replaced, or security-critical. Do not delete migrations, access controls, audit, or recovery logic without proof.

## Data contracts and precedence

PersonaDefinition: owner/tenant, name, title, purpose, industries, tags, privacy/visibility. A professional title is a user-provided role, never certification.

PersonaRevision: immutable schema version, communication DNA, collaboration preferences, declared specialties, safe references, audit provenance and fingerprint.

PersonaScope: authorized source identifiers and purpose limitations, never permissions by themselves. Every read intersects actor, tenant, source ACL, consent, purpose, persona and thread scope.

SkillAssociation: declared specialty or canonical registered executable capability. The UI must distinguish declared skill, available tool and evidenced task proficiency. No persona-issued privileges, credentials, provider routing or self-installation.

LearningProposal: scoped evidence, proposal status, user approval/rejection, expiration, supersession and revocation. Only approved changes produce a persisted revision or governed preference record.

ExecutionSnapshot: frozen per-turn persona revision, allowed context references, eligibility decisions, applied/suppressed presentation constraints, runtime model metadata and correlation ID. Never expose hidden prompts or private raw evidence in UI receipts.

Precedence: platform/safety/RBAC/tenant policy > explicit authorized turn intent > selected approved persona contract > approved persona-scoped preferences > approved global defaults > non-operative suggestions. Imported content can never change this ordering.

## Canonical memory truth and state transitions

For a sampled turn, correlate selected intent, retrieval adapter health, raw candidate count, unique fact identity, eligible candidates, actually injected context, formation candidates, evaluator decisions, durable commit receipts and projection watermark. Distinguish observed, recalled, injected, saved and projected.

The repeated-name weather example is evidence for investigating *effective retrieval deduplication and task relevance*, not proof of duplicate database rows. Preserve contradictory evidence, provenance and temporal validity. A recalled identity statement is not automatically useful for a weather task. Memory outages are degraded results, not zero memories. When durable save precedes Facts projection, report saved/syncing only if a real durable receipt exists. Revoked sources fail closed even with stale cached/vector hits.

## Threats that block shipment

1. Cross-tenant fact/persona lookup via guessed identifiers.
2. Business-to-Family history, summary, attachment, cache or AG-UI event leakage.
3. Permission escalation using imported CEO/Admin persona, user-provided skills or malicious documents.
4. Incorrect success toast without persisted persona, preference or fact receipt.
5. Tool execution during default Persona Lab preview.
6. Stale revoked information in any future effective context.
7. Provider fallback escaping original context restrictions or local-first policy.
8. Multi-tab activation race silently replacing another choice.
9. Learning candidates becoming durable without explicit policy/consent.
10. Personal Facts showing a projected record as a new independent source of truth.

A turn freezes normal persona edits; subsequent turns use new revisions. Security revocation triggers reauthorization or abort where feasible. If switching scopes cannot safely filter previous chat context, create a new scoped thread with clear explanation.

## UX and assistant-ui/AG-UI boundaries

First-use interaction: Describe a specialist -> edit proposed name/title/skills -> Create -> optionally Activate. No mandatory sliders, datasets, taxonomy selection or technical configuration.

Everyday interaction: one shared assistant-ui composer with active named persona; project scope indicator; quick switch; What Troy knows; Teach Troy; inspect and undo approved preferences. Backend receipt is required before marking the choice saved. Accessible keyboard/mobile/screen reader support and honest offline/degraded/error states are release requirements.

Advanced controls: revision compare, approved knowledge references and provenance, deterministic workspace rules, Lab, exported templates and skill evidence, revealed progressively. assistant-ui is presentation, never routing or data authority. AG-UI projects authenticated observed long-running progress, not CRUD, state writes or animated invented status. Prove package installation and bundle imports before integrating assistant-ui widely.

## Data Needs Advisor: smaller, task-specific

Given task goal, authorized existing knowledge, live tool eligibility and active persona revision, return either enough-to-proceed, up to three high-value missing information requests with clear necessity/rationale, or a genuine capability/authorization blocker. Do not require giant role-specific datasets. The Advisor never writes memory or silently trains a model. Existing resource selection and governed fact/preference correction handle user actions.

## Dependency-ordered delivery

| Gate | Work | Acceptance proof |
|---|---|---|
| KP-01 | Active code/migration owner and duplicate audit | Call graph, import audit, classification |
| KP-02 | Typed persona contract/compatibility | Validation, old payload, authority-denial tests |
| KP-03 | Facts-memory convergence and relevance | Weather-turn replay, dedupe, formation receipts, contradiction checks |
| KP-04 | Durable persona revisions, scopes and approval | PostgreSQL RLS, restart, concurrency, revocation |
| KP-05 | Runtime persona resolution and scoped context | Real local model, ACL, fallback, streaming/snapshot tests |
| KP-06 | Minimal Studio + shared assistant-ui flow | Create/use/teach/switch Playwright, keyboard/mobile |
| KP-07 | Task-aware Advisor | Fewer questions, demonstrable task success against baseline |
| KP-08 | Safe real-model Persona Lab | Controlled paired trials; no default tools or side effects |
| KP-09 | Optional wardrobe, Lens, drift and sharing | Feature-flagged privacy, factual fidelity, import fuzzing |
| KP-10 | Docs, accessibility, telemetry, rollout | Human acceptance, rollback readiness and evidence matrix |

First release includes Troy's name/title/specialties, authorized context, real responses, consent-based scoped learning, safe persona switch, coherent Facts/Turn Intelligence and shared composer. Defer fancy DNA dashboards, automatic wardrobe, proficiency grading, drift watchers, team marketplace, Passport distribution and model fine-tuning.

## Verification and merge policy

Run relevant Python compilation, unit/integration tests, Ruff, mypy, frontend lint/typecheck/test/build, Docker config, real PostgreSQL tenant RLS/restart/race checks, local-model smoke tests and Playwright accessibility/navigation acceptance. Record exact commands, tested commits, failures, skips, and verified receipts. Do not confuse waived exact-head CI with a passed test. Inspect screenshots before putting them in docs. Keep PR #501 draft until implementation gates pass. Avoid stacked PRs, unnecessary schema churn and false completion claims.

Roll back or stop on cross-tenant leakage, revoked-memory reuse, unapproved tool execution, unauthorized provider fallback, incorrect saved-state acknowledgment or unsafe persona context switching.


---

# Persona 6.0: Full Adversarial Persona–Agent Collaboration Contract

**Status:** Architecture and executable acceptance specification only. Supersedes conflicting Persona 5.0 assumptions about collaboration. PR #501 remains draft; no code/tests are claimed. **KP-01–KP-05 remain ahead of KP-11.**

## Product decision and boundaries

Support named personas as specialized collaborators and reusable Persona Teams as *configurations of approved persona references and responsibilities*. Retain ChatRuntime as sole request/execution authority, CORTEX as intent/policy decision-maker, Deep Agents as existing actual multi-step execution orchestrator, PromptRuntime as compiler, and registered provider/tools as execution mechanisms. Do not implement a persona-specific agent runtime, planner, model router, queue, memory store, provider fallback, independent skills registry, workflow engine or team controller.

**Persona** answers *which approved knowledge, communication preferences and domain collaboration stance are useful*.
**Agent** answers *which governed tasks are executed and how*.
**Team** answers *which roles participate on this user-authorized assignment, with which minimal task-scoped context and exchange rules*.
**Runtime** answers *who is authorized, what was executed, with which provider, model, receipt and outcome*.

A named role, professional title or skill is metadata, not a credential, privilege, ability guarantee or prompt-authority escalation. Workflow selection remains with CORTEX/runtime. Deep Agents is not mandatory for simple multi-perspective responses; LangGraph is used only if the existing graph execution requires branching/conditional durable coordination.

## New adversarial findings

| Threat / failure | Severity | Mandatory correction |
|---|---|---|
| Team becomes a second orchestration implementation | Critical | Team definition stores only references/policy; Deep Agents executes |
| Agent-to-agent sharing launders private Facts across scopes | Critical | Explicit output exchange grants with ACL, purpose, tenant, origin and revocation checks |
| Multi-persona combination merges raw persona prompts | Critical | Structured role contracts, scoped resources and compilation; no concatenated authority-bearing raw instructions |
| Role labels grant tools/models/provider policy | Critical | Recompute manifest eligibility/RBAC per delegated action and fallback |
| One persona's approved preference mutates others | Critical | Evidence isolated by persona; cross-persona promotion requires explicit review |
| Mid-run participant revision or revocation is ambiguous | Critical | Frozen normal snapshot; security revocation recheck/abort, durable workflow resume invariants |
| Subagent observations attributed to the wrong identity | High | Distinct actor / persona / execution-agent / tool / model IDs and provenance |
| Cross-persona contributions degrade factual validity | High | Task invariant contract, attributed artifacts and verifier/review gate |
| All teams spawn several expensive model calls | High | Deterministic one-call vs serial vs parallel topology policy, budgets |
| Side effects occur in rehearsal or preview | Critical | Tool-disabled preview; separate authorized sandbox tests |
| Shared or imported team copies ACL grants | Critical | Portable definitions never contain credentials, memory grants or private references |
| A stalled delegated task hides partial failure | High | Per-task terminal status and explicit partial deliverables; no successful team receipt until criteria met |
| Agent requests unlimited specialist additions | High | Bound fan-out, task depth, token/time cost and replan count from central config |
| UI fabricates concurrent specialists or approvals | High | Render only runtime-confirmed participants, actual events and receipts |
| Partial/degraded retrieval silently pollutes final response | High | Fail closed on unauthorized data, mark missing/partial evidence explicitly |
| Team member gains access through previous chat summaries | Critical | Restrict prior thread and summaries, otherwise create a new scoped conversation |

## Data model: minimal logical schema, reuse existing owners

- **PersonaTeamDefinition**: team_id, tenant_id, owner_user_id, name, description, lifecycle, visibility, created_at. This is configuration, not execution authority.
- **PersonaTeamRevision** (immutable): version, participating persona_id/revision policy, declared responsibility, user-defined objective template, conflict/handoff policy, artifact exchange policy, source fingerprint, approvals and updated_by. No provider IDs, credentials or implied resource grants.
- **CollaborationRequest**: user instruction, selected or recommended team revision, immutable current actor/tenant/session/conversation, task requirements, explicit approvals, correlation_id/idempotency_key.
- **ParticipantExecutionSnapshot**: persona_id, resolved immutable revision, participant_task_id, effective ACL/purpose scope, facts/references actually injected, model/tool eligibility decision provenance, budget and authorization watermark. Do not make agent identity an alternate security principal.
- **SharedArtifactReceipt**: producer_task_id, resource_id, redacted metadata/type, user/tenant owner, source provenance, permitted recipient task IDs and purposes, eligibility/version, revocation marker, approved transfer decision. Transfer only task-relevant output, never entire hidden context or raw memory.
- **TeamExecutionReceipt**: parent execution_id, child task IDs, selected topology, decisions, participant-attributed outputs, approvals, provider/model/fallback metadata, elapsed/cost/failure summaries, status and delivery receipts. Extend canonical runtime telemetry; no new telemetry silo.

Before adding SQL, map these to existing Deep Agents task/checkpoint storage, persona revisions, conversations, artifact repository and audit rows. Add only relations that cannot be represented reliably with existing schema. Immutable revisions and idempotency are required. Team templates are organizational assets but cannot inherit members' private data.

## Collaboration policy and delegation algorithm

1. **Intent**: Authenticated user requests a task or selects a saved Team. CORTEX classifies intent and whether specialized perspectives add value. Team suggestion does not activate automatically when unauthorized or unconfirmed.
2. **Normalize**: ChatRuntime resolves actor/tenant/permissions, requested personas, currently authorized team revision, tool and model policies, deadlines and bounded budget. Only the authenticated runtime may establish the root execution context.
3. **Sufficiency**: For a simple informational comparison, compile a single response using the authorized limited perspectives; do not create multiple agents or run one model call per persona.
4. **Decompose when justified**: Existing Deep Agents turns the goal into distinct deliverables only where dependencies, parallel work, tool operations or independent review justify it. CORTEX keeps governing task/policy decisions. Each participant receives a distinct scoped task context.
5. **Select context**: For every participant, intersect current user/tenant authorization, source ACL, purpose and persona-specific grants with task need. Each retrieval uses NeuroRecall's canonical selection/deduplication. Persona knowledge references do not grant access.
6. **Execute**: Runtime applies PromptRuntime's safe role/presentation contract, selects model using canonical provider router/learned policy and evaluates registered tool manifests and approval needs. A persona cannot route providers or self-grant tools.
7. **Exchange**: Child output is not implicitly visible to other participants. Register task artifact and purpose-bound transfer permit. Revalidate authorization at consumer context-selection time; sanitize untrusted output as data and redact unrelated sources. On revocation, deny future read and abort/re-authorize affected active work.
8. **Verify**: For every deliverable preserve user requirements, source traceability, factual stability and specialized task checks. Contradictions between personas are surfaced as disagreements with evidence, not averaged into fabricated consensus.
9. **Assemble**: Canonical runtime composes reviewed results, attributed contributions, outstanding approvals and clear partial-failure states. Keep parent and child receipts, cancellation and retry semantics consistent.
10. **Learn**: Completed work can supply bounded evidence to UserModel. The user approves a revision for one explicitly scoped persona; no team-wide silent learning, hidden memory replication or model retraining.

Topology choice requires observable policy inputs and configuration: task decomposition benefit, tool requirements, independent cross-check value, model capability, resource cost, latency and confidence in completeness. Rule: single execution by default; serial/parallel workflows only after actual need. Cap participants, recursion depth, timeouts, retries, total tokens/cost, ongoing artifact retention and proposal volume centrally.

## Authority and isolation rules

The context that Troy sees is **not** the context that Morgan sees. Shared task briefs require explicit source ACL, consent and purpose intersection. An artifact that Troy produces may be sharable only if approved for the recipient and task; this does not imply that Morgan may read Troy's source brand documents, prior chats or private preferences. Untrusted artifacts cannot insert executable system instructions, alter policy or grant resources. Derived outputs may themselves be sensitive and inherit applicable provenance/restrictions; do not assume generated text is public.

An active workflow freezes normal persona/team revisions on creation, and resumptions must restore the same authorized snapshot *subject to current security rechecks*. Cancellation and revocation supersede frozen snapshot eligibility. Retry must reuse idempotency keys and must never repeat already acknowledged external side effects. Reassigning a participant must be user-approved if it broadens knowledge purpose or materially changes external actions.

Team role conflicts: explicit user task intent and system policy outrank team suggestions; conflicting user-approved persona presentation conventions are isolated within child tasks and reconciled through deliverable requirements. Professional labels never establish licensure. No team member can operate as an administrator merely due to title.

## UX: sophisticated capability, simple presentation

Persona Studio's main surface remains one-sentence creation and an intuitive personal persona library. **Persona Teams** appears as a secondary collaboration affordance, not a required setup step. A user can say, "Have Troy design and Morgan review the campaign." Karen previews proposed roles and key context boundaries, then starts approved execution. Saved teams are optional reusable shortcuts.

Use the single persistent assistant-ui thread/composer with a clearly attributable participant switch and concise task cards. Provide actual status states: proposed, awaiting permission, queued, running, partial, failed, completed, canceled. A task card links to artifacts, source evidence, cost/latency where available, approvals, retry and cancel. Do not show fake typing indicators that imply model execution.

AG-UI is valuable for streaming *runtime-observed* start/progress/waiting-on-user/tool-completed/artifact-ready/failed/completed events from long-running Deep Agents workflows. Use existing AG-UI event bridge with tenant-scoped auth, safe structured schema, correlation_id, stable sequence numbers and reconnect/replay semantics. It is never a second workflow state owner. Routine team CRUD/selection and feedback approval use existing APIs.

Use assistant-ui for shared thread, composer, tool-result cards, approvals and accessible controls, but only after dependency/import and integration checks. Preserve Karen visual identity; do not reproduce the same chat state in every participant panel. Mobile and keyboard/screen-reader navigation must be tested.

## KP-11: Persona Teams (post-foundation; feature-flagged)

**Prerequisite:** KP-01–KP-05 release-blocking proofs and the single-persona Troy vertical slice have passed. KP-06 shared composer and approvals required before broad usability. Never block the initial usable persona release on teams.

**KP-11A — Reuse and topology audit**: Identify actual Deep Agents task/delegation/checkpoint APIs, CORTEX routing, skill manifest ownership and artifact ACL. Document what survives, remove proposed duplicate engines from scope. Prove simple multi-perspective tasks can run without spawning agents.

**KP-11B — Scoped team revisions**: Implement only necessary persistent team references, roles, revisions and opt-in activation. Tests: tenant ACL, no inherited grants, import/clone safety, version concurrency, revocation.

**KP-11C — Delegated collaboration**: Wire runtime-owned participant snapshots into existing Deep Agents execution. Enforce bounded topology, per-action RBAC, model router ownership, safe share/consume of artifacts, retry and cancellation. Tests: denied tool, tenant, revoked cached context, wrong purpose, fallback, side-effect idempotency and partial failures.

**KP-11D — Shared UX and AG-UI projection**: Only verified team progress appears in assistant-ui cards. AG-UI events carry real redacted task state and can resume in-progress work. Tests: navigation, reconnect, multi-tab, mobile, keyboard, misleading-success prevention.

**KP-11E — Real campaign acceptance**: Troy prepares a sourced design direction; Morgan reviews marketing consistency; a parent workflow returns attributed deliverables. Use actual authorized local-model calls, real PostgreSQL persistence, optional governed design tools, RLS, task-scoped artifacts and browser E2E. Include negative tests: Family cannot read campaign, user rejects sharing, tool denied, model fallback, cancellation/resume and stale revoked context.

## Verification and rollout

For KP-11 capture audit evidence per task: source commit, command, environment, actual model/provider, execution topology, number of model calls, latency, tokens/cost, tool receipts, memory access counts, rejected ACL events and screenshot evidence. Baseline against a one-persona or one-call task; promotion requires meaningful user benefit without factual, privacy or reliability regressions. Never claim "three models worked together" when a single prompted answer was used. Failing authorization, unapproved actions, cross-tenant leakage or fabricated completion is an immediate rollback condition.

**Build order:** KP-01/02/03 canonical foundations -> KP-04/05 single-persona real runtime -> KP-06 basic UX -> KP-07 task-aware advisor -> KP-10 security/rollout. KP-08/09 advanced additions remain deferred; KP-11 teams follows proven collaboration dependencies and may ship separately, on the *same evolving PR only if small and nonblocking*, otherwise after merging the verified foundation to main. Avoid PR stacking and stale conflicting branches.

**Single source of truth:** persona identity/revision in existing PersonaService; memory/Facts in governed NeuroVault projection; preference proposals in UserModel; authority in ChatRuntime/CORTEX; execution in Deep Agents and registered tools; presentation in assistant-ui; streamed observed events in AG-UI. No new persona brain.


## KP-01 implementation checkpoint: verified defect and first remediation

The active `core/persona/contracts.py` defines a dataclass Persona with `tone`, `verbosity` and `instructions`; PersonaService, the API and SQL expect `system_prompt`, `default_tone`, `default_verbosity`, `default_language`, `domain_knowledge`, `is_active` and `.dict()`. UserPersonaPreferences and ChatStyleContext likewise differ from service usage. This is a confirmed contract mismatch requiring reconciliation, not merely an architectural concern.

A first security remediation has been committed: the service's process-global `_persona_cache` is restricted to built-in system personas, and custom ID lookup now goes through user/tenant-scoped preferences. Prior global caching by persona ID alone risked cross-user and cross-tenant disclosure. A targeted regression test for identical IDs across tenants was committed. **The test has not been run, and no full authorization or runtime guarantee is claimed.**

Next: reconcile existing typed contracts and Pydantic/SQL consumers in place; execute import and unit tests, PostgreSQL RLS and rollback/restart tests, and audit other global caches before adding migrations, Advisor UI, or team execution. Keep KP-01/02 open until proven.
