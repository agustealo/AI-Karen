# 14. Writing Studio: communication identity intelligence and plugin integration

[Wiki index](README.md) · [Architecture](01-architecture.md) · [Manifests](03-manifests-and-prompts.md) · [Frontend](07-frontend-integration.md) · [Testing](09-testing-and-observability.md)

> **Status: Proposed full-scope product and developer contract, 2026-11-20.** This chapter is a target specification, **not** evidence that Writing Studio, KariSignature, its endpoints, its hooks, or its UI have shipped. Every API, entity, event and example below is **proposed unless explicitly identified as an existing platform owner**. Reconcile against live source, existing PRs and tests before creating files. Naming and trademark clearance for KariSignature remain unverified.

## 1. Mission, product boundaries, vocabulary

**Writing Studio** is the first-class user/admin experience for acquiring, governing, testing, applying and evolving *communication identities* for individuals, businesses, clients, teams and authorized agents.

**KariSignature** is the product-owner-selected name for the reusable underlying communication-style capability; trademark clearance and production availability remain unverified. It is not a voice-cloning system. Do not rename or replace the existing Persona, Memory, CORTEX, Agent or VoiceRuntime authorities in order to implement it. The temporary contract identifier `writing_style.v1` is intentionally brand-neutral pending naming approval.

A **communication identity** is a versioned, evidence-supported description of how an actor or organization expresses information: vocabulary, sentence structure, rhetorical patterns, register, tone, degree of formality, format, audience adaptation, accepted phrases, avoided phrases and explicit style rules. Its purpose is *expression*, not deciding what to say, what facts are true, what memory may be retrieved, what tools may run, or which provider executes.

Distinguish the following concepts:
- **Sample:** untrusted, permissioned input evidence, never system instructions.
- **Trait:** an observation inferred from bounded samples, with provenance and confidence.
- **Rule:** a declared, authorized user/organization preference, with precedence, constraints and revision history.
- **Identity/profile:** tenant-scoped owner, purpose, state, consent, linked evidence, revision and consumer bindings.
- **Variant:** task- or audience-specific expression profile (professional, conversational, marketing, etc.) within an identity or as an independently governed profile.
- **Binding:** authorization-constrained link to Persona, Agent, user workflow or channel, *not a permission grant*.
- **Style resolution:** host-approved, bounded, provenance-bearing style instructions assembled by the canonical runtime.
- **Acoustic voice:** audio characteristics, voice references and synthesis are separate capabilities governed under [Voice and modalities](08-voice-and-modalities.md). A written style sample does not authorize voice cloning.

**Core product acceptance:** an authenticated user can create an identity, submit/approve samples, inspect evidence-backed proposed traits, publish an immutable revision, generate with it in a permitted task, see exactly what revision was used, provide correction feedback, and safely revoke access. Admin can govern the plugin without seeing raw private samples by default.

## 2. Canonical ownership and non-duplication

| Responsibility | Canonical owner / integration boundary | Writing Studio responsibility |
| --- | --- | --- |
| Authentication, session, tenant, RBAC, consent and policy | Existing auth / RuntimePolicy / approval and audit owners | Request permissions; reject or fail closed; never create its own authorization |
| Chat and model execution, prompt assembly, provider selection and degradation | ChatRuntime and canonical PromptRegistry / model router | Supply validated style constraints and a versioned prompt contract, not assemble system prompts or run a competing inference router |
| Intent recognition, eligibility and capability recommendation | CORTEX | Advertise typed style intents/capabilities; CORTEX decides, host executes |
| Plugin discovery, trust, dependencies, lifecycle, enable/disable | PluginKernel, PluginService and ExtensionExecutionService | Governed plugin manifest, adapters and user/admin surfaces; no parallel plugin loader |
| Persona identity and behavioral purpose | Existing Persona authority (see relevant Persona Studio work) | Optional, scoped communication-style attachment; never supplant persona instructions or policy |
| Agent work planning and execution | Existing agent/workflow owner plus runtime | Governed tool invocation; no independent agent or LangGraph for simple transformations |
| STM, episodic, durable memory, retrieval, governed persistence | Existing STM / NeuroRecall / NeuroVault and canonical database services | Store style-specific records where genuinely needed; access memory only through scoped host services |
| Tenant settings, personal preferences, secrets | PluginSettingsRepository, user preference owner, Identity Vault | Tenant configuration only in plugin settings; personal selections in user preferences; secrets never in plugin JSON |
| Web interface and UI materialization | Existing theme/CopilotKit design and UI plugin materialization | Writing Studio and admin panels, project existing backend state |
| Events and extension points | Existing PluginKernel lifecycle hooks and host event/telemetry owners | Register typed lifecycle observers/capabilities; add no private hook authority |
| TTS, STT, playback, cloning | VoiceRuntime, modality adapters and consent/media owners | Optional approved textual delivery hints only, not synthesize audio |

Audit existing implementation and pending PRs first. In particular, reconcile Persona Studio and existing plugin GUI manifests before choosing new paths. Do not create competing profile, memory, credential, hook, route, agent or provider registries. Thin HTTP routes only validate, establish context, delegate and translate typed failures.

## 3. Supported identity scopes and ownership

Supported logical scope types:
1. `personal`: individual's default or purpose-specific writing identity.
2. `professional`: individual's distinct occupational register.
3. `business`: organization brand voice governed by tenant policy and brand owners.
4. `client`: explicitly authorized client-specific identity; client ownership/delegation and retention must be documented.
5. `team`: authorized group identity with member-specific permitted variants.
6. `persona_binding` and `agent_binding`: **consumers**, not new ownership scopes or hidden synthetic users.

An identity has a stable opaque ID, owner type/ID, tenant ID, optional client/project scope, title, purpose, classification, state, creation and update metadata, current published revision, version sequence and policy-controlled retention. Use scoped references; never trust a client-supplied tenant/owner field. A personal profile cannot be silently promoted to a company or client profile. Transfer of ownership requires independently authorized workflow, audit and provenance.

Lifecycle: `draft -> analyzing -> review_required -> published -> suspended -> archived`; invalid/failed ingestion or analysis may return to a retriable draft with explicit failure metadata. Publishing is an auditable compare-and-swap operation. Immutable published versions remain addressable for permitted audit and response provenance; archived/revoked identities must be fenced from new use. Deletion, retention and historical provenance obey existing privacy, legal-hold and governed deletion policies. A user cannot acquire a client identity merely by guessing its ID.

## 4. End-to-end sample acquisition

Allow: pasted text, approved document uploads, user-authorized email or channel imports, selected messages, transcribed dictation, human-authored brand guides and approved imported style definitions. Use the existing file/media and connector ingestion owners; do **not** build a standalone arbitrary URL fetcher or mailbox scraper. A sample can be associated with a declared author, source owner, origin channel, source timestamp, source URI/ref, target identity, language/locale, consent grant, authorization receipt, permitted use, retention time and source digest.

Pipeline (all stages auditable and retry-safe):
1. Receive scoped request with correlation/request ID, auth, tenant, consent and target profile ownership.
2. Validate MIME/type/size and source authority; quarantine hostile or unknown files, enforce malware and prompt-injection defenses.
3. Normalize with provenance preservation; redact or isolate unnecessary third-party PII; retain the original only under approved retention rules.
4. Deduplicate by scoped content digest; identify quoted text, third-party writing, signatures, templates and boilerplate. Never assume authorship because a document was uploaded.
5. Segment by writer, audience, medium, purpose and language; reject weak samples or label uncertainty.
6. Run analysis through canonical prompt contract and model routing, with provider/egress policy and resource limits.
7. Produce typed *proposed* traits with confidence, evidence reference, sample statistics and explicit conflicts; do not execute embedded instructions.
8. Present proposed traits/rules to user or assigned approver; require authorized confirmation for durable promoted preferences.
9. Publish an immutable revision with optimistic concurrency; invalidate downstream bindings/caches and write usage/audit receipts.

A model-produced style claim is not a factual claim about the author's psychology, protected characteristics or personal identity. Avoid inferring sensitive attributes, demographics, mental or health state. Do not train or fine-tune external models on client material without a separate explicit approved capability and consent. A transcript used for writing-style analysis is not authorization to clone the speaker's acoustic voice.

## 5. Structured style and revision contract (proposed)

Profile revision schema should include:
- `profile_id`, `revision_id`, `parent_revision_id`, `revision_number`, `schema_version`, `published_at`, `published_by`, `content_digest`.
- `languages` and declared locales with per-language sample/evidence coverage.
- `register`, `tone`, `verbosity`, `sentence_structure`, `paragraph_structure`, `punctuation`, `rhetorical_devices`, `cadence`, `greeting`, `signoff`, `formatting`, `preferred_terminology`, `avoid_terms`, `audience_adaptation`.
- Structured fields must use bounded schemas, validation ranges and controlled vocabularies where feasible; free-form text is advisory data, never system authority.
- `traits[]`: trait ID, typed value, observation source, confidence, supporting/rebutting evidence reference and extraction model/prompt version.
- `rules[]`: author-approved rule ID, scoped applicability, priority, declared-vs-inferred provenance, expiry and conflict resolution metadata.
- `sample_refs[]` as policy-checked references, not unrestricted file paths or full content in execution plans.
- `eval_summary`: passed criteria, benchmark version, model revision and known limitations.
- `consent_snapshot` and use limitations. Do not replicate full credential or auth objects into the profile.

Prefer a small stable core schema plus versioned extensions over unvalidated arbitrary JSON. Changes to a published revision create a new candidate; revisions never mutate in place.

## 6. Consumer, business/client and admin UX

**Navigation:** Writing Studio as a discoverable user-facing app/surface, and a Plugins & Tools management entry. Display a separate admin area only to eligible roles. Availability comes from verified backend capability health, not a hardcoded menu.

**Consumer UI:** initial explanation and consent; profile type + scope wizard; identity library (owner, revision, status, permitted consumers); paste/upload/import sample journey; sample provenance and rights/consent controls; analysis job progress; reviewable trait fingerprint with linked evidence; rules editor; variation editor; publish/diff/rollback; preview/test lab with source-to-output comparison; audience selector; apply-in-chat/writing workflow; version usage and corrections; export, archive, revoke and delete/request-delete. Persist real data and read back after every change.

**Client/business UI:** tenant/project folders, explicit client authorization, shared brand rule library, authorized member roles, approval chains, profile publication policy, scoped binding and usage by agent/persona/channel, brand compliance evaluation, delegated access expiry and audit history. A tenant operator must not automatically gain access to raw personal sample content.

**Admin UI:** plugin installed/trusted/enabled/healthy/blocked/degraded status; manifest and version; dependency/permissions readiness; ingestion limits and allowed source integrations; local-first/external-provider egress controls; selected analysis prompt contract/model capability status from canonical registry; token/cost quotas; background worker health; job errors/retry; retention/consent policy; hook subscriptions and failures; tenant-level approvals; audit access; metrics with privacy controls; upgrade, migration, uninstall, backup and recovery.

**UX states:** empty, setup-needed, permission-denied, loading, analyzing, awaiting review, published, suspended, revoked, outdated binding, provider unavailable, policy blocked, partial/failed save, stale revision conflict and deletion pending. No fake saves, training, readiness, completion, previews or usage receipts. Readiness is distinct from catalog declaration. Support responsive 390/768/1024/1440 px layouts, accessibility, keyboard and focus restoration, screen reader announcements and draft continuity.

## 7. CORTEX, Persona, Agents, Writing workflows and Story Repository

**CORTEX:** Classify intent (`style.analyze`, `style.create`, `style.compare`, `style.apply`, `style.feedback`, `style.manage`) and propose eligible capability/profile selectors. CORTEX never reads unscoped sample bodies, writes profile revisions or selects execution providers. The runtime rechecks every proposed profile ID/binding under the *current* actor, tenant, purpose, destination and consent.

**Persona:** Persona determines behavioral role, purpose, accessible knowledge and instructions. The profile governs expression only. Persona may reference a published style version or an approved policy-defined selector. A Persona binding cannot grant new tool, memory or client permissions. On persona switch, resolve fresh tenant/scopes; no silent cross-persona state carry-over.

**Agent:** Agents discover typed, authorized style capabilities. Read operations are `writing_style.list`, `writing_style.describe`, `writing_style.resolve`, `writing_style.preview`; governed mutation operations are `writing_style.ingest_sample`, `writing_style.propose_revision`, `writing_style.submit_feedback`, `writing_style.publish`, `writing_style.revoke_binding`. These are **contract names only**, not currently implemented tools. Mutation, external sharing and application to public communications require separate explicit permissions and approval when policy requires it. Agent output records profile ID/version but never exports raw sample bodies to generic tool contexts.

**Writing/chat workflows:** User requests style by explicit profile or authorized default; runtime resolves the immutable version, merges bounded style hints in prompt assembly, applies token budget and safety precedence, executes with canonical provider selection, then records actual applied profile/version, degradation/reason, model, latency and audit outcome. User can inspect style attribution, offer correction and selectively approve learning. If a named profile is revoked, inaccessible or unavailable, show that truth and ask for a different style; do not silently substitute another client identity.

**Intelligence Blueprint:** controls purpose, cognitive specialization and applicable task strategies, not stylistic sample ownership. **Story Repository:** contributes authorized narratives and anecdotes as content/evidence, not untrusted policy. **KariSignature/Writing Studio:** determines how permitted content is expressed. Cross-system references carry actor/tenant/project/consent scope; retrieval or story availability never grants style-profile rights and vice versa.

**Channels:** explicit user authorization and destination policy. The same approved style may serve email, WhatsApp, proposals and social copy, with medium-specific constraints and separate publication approvals. Do not apply identity to private or client messages automatically on inferred similarity alone.

## 8. Resolution and precedence

Suggested resolution order, subject to the canonical runtime's existing higher-level instruction hierarchy:
1. Platform/system safety, compliance, authentication, privacy and tool policies.
2. Tenant/client governance and authorized destination constraints.
3. Persona/agent task role and knowledge permissions.
4. User's explicit task and authorized profile selection.
5. Approved organization/client communication rules within scope.
6. Approved personal style rules and task-specific variants.
7. Inferred, evidence-backed soft traits with confidence thresholds.

Rules in conflict must be surfaced deterministically with winning source, reason and affected trait. Do not claim to blend incompatible clients automatically. Explicitly authorized composite usage may combine separate non-conflicting style dimensions; no cross-client content transfer, sample migration or persistence of merged identities without consent. User override cannot bypass platform/client compliance restrictions. Snapshot the exact effective style resolution on execution for replay/debug without storing protected raw samples in logs.

## 9. API and event contract proposals

**All paths and events below are *proposed*, not existing API routes.** Match the repo's existing API conventions before implementing. HTTP routes remain thin. Prefer one owned style service + extension adapter, not parallel REST and plugin implementations.

Candidate authenticated API families:
- `GET/POST /api/writing-studio/profiles`
- `GET/PATCH /api/writing-studio/profiles/{profile_id}`
- `POST /api/writing-studio/profiles/{profile_id}/samples`
- `GET /api/writing-studio/profiles/{profile_id}/samples`
- `POST /api/writing-studio/profiles/{profile_id}/analyze`
- `GET /api/writing-studio/analysis-jobs/{job_id}`
- `GET /api/writing-studio/profiles/{profile_id}/revisions`
- `POST /api/writing-studio/profiles/{profile_id}/publish` (revision CAS + audit)
- `POST /api/writing-studio/profiles/{profile_id}/preview` (actual authorized runtime)
- `POST /api/writing-studio/profiles/{profile_id}/feedback`
- `GET/POST /api/writing-studio/profiles/{profile_id}/bindings`
- `DELETE /api/writing-studio/profiles/{profile_id}/bindings/{binding_id}`
- `POST /api/writing-studio/profiles/{profile_id}/revoke`
- `GET /api/writing-studio/capabilities` (verified user/tenant-scoped availability)
- `GET /api/writing-studio/admin/health` (authorized admin only; no private content)

Response envelope proposal: stable `profile_id`, `revision_id`, `tenant_scope`, `status`, `correlation_id`, `request_id`, `capability_version`, `permission_decision` and explicit typed errors. Mutating operations use revision preconditions and idempotency keys where applicable. Large uploads use the existing secure media pathway; no raw document in ordinary JSON plugin settings. Define paginated list limits, payload sizes, locale encoding, ETags/CAS semantics and retention metadata before implementation.

**Proposed event names:** `writing_studio.sample.accepted.v1`, `writing_studio.analysis.completed.v1`, `writing_studio.revision.proposed.v1`, `writing_studio.profile.published.v1`, `writing_studio.binding.revoked.v1`, `writing_studio.style.resolved.v1`, `writing_studio.feedback.recorded.v1`. Events publish *bounded references* only, not raw sample data. Sensitive events are delivered after committed persistence using existing event/outbox mechanisms where available; delivery is retry-safe and idempotent.

## 10. WordPress-inspired actions, filters and host authority

Use the **existing** plugin manifest's `hook_points` capability only to the extent it supports the required event and authorization semantics. Do not assume a WordPress-like extensibility API currently exists merely because a manifest has hook fields.

- **Actions:** post-commit, scoped lifecycle signals. Listeners cannot mutate the authoritative transaction or veto a security decision.
- **Filters:** deterministic, bounded transformation of explicitly filterable style proposals/draft presentation data. Input/output schema validation, priority, recursion limit, timeout, versioning, isolation and audit mandatory.
- **Capabilities:** callable permission-checked operations through PluginKernel -> ExtensionExecutionService. Registration is not authorization.

No hook may override authentication, tenant isolation, approval, model policy, prompt instruction hierarchy, retention law or audit obligations. Do not permit arbitrary plugin code from untrusted ZIPs to execute in-process. Hook registry owns versions, plugin signatures/trust, health, enabled state, dependencies, idempotency, failure policy and consumer provenance; extensions declare subscriptions, never create another registry. Suspended/disabled plugins lose new execution admission immediately.

Define proposed lifecycle callback metadata: `event_id`, `event_type`, `schema_version`, `timestamp`, `correlation_id`, `actor_ref`, `tenant_ref`, `profile_ref`, `revision_ref`, `authorization_scope`, `causation_id`, `redaction_level`, `delivery_attempt`. Treat these as design fields, not shipping event payloads.

## 11. Storage, isolation, memory and configuration

Prefer the canonical PostgreSQL persistence owner, scoped row-level protections and existing user/tenant registries. **Logical entities, not an instruction to make separate tables**: identities, immutable revisions, samples/evidence references, observed traits, approved rules, bindings, analysis jobs, evaluations, feedback, usage attribution, consent receipts and deletion requests. Reuse the existing audit, identity, file/media, retention, background task and settings services when they already supply the needed contract.

- Enforce tenant RLS, owner/delegate checks, source provenance, scoped key/asset permissions and all-purpose RBAC on *every* read/write and job callback.
- Sample embeddings or searchable evidence use only approved NeuroRecall/indexing routes; governed durable source deletion is managed with NeuroVault and canonical stores, not a hidden vector DB.
- Do not store uploaded raw writing in unrestricted logs, browser localStorage, metric labels or plugin configuration.
- Prevent stale published-style caches following scope changes, consent revocation, deletion or tenant switch.
- Persist user-selected default profile through the existing user preferences owner. Tenant-wide operational limits live in PluginSettingsRepository. Credentials stay in Identity Vault.
- Model/provider selection, local-first operation, network egress opt-in, fallback and token budgets come from central config/policy. No implicit remote analysis of private samples.
- Use schema versioning, migrations, rollback-safe upgrade and integrity checks; do not delete historical migrations to simplify an upgrade.

## 12. Analysis, evaluation and continuous improvement

Prompts for extraction, comparison, fidelity checking and preview use **versioned PromptRegistry contracts**. Inputs declare language, audience, purpose, evidence refs, output schema and token budgets. The model must preserve factual meaning, avoid manufactured experiences and avoid imitating a forbidden third-party identity. A model response is a suggestion, not profile state until host-approved persistence.

Evaluation tracks: style adherence, semantic fidelity, factual preservation, unwanted phrase occurrence, brand rule compliance, audience suitability, cross-language transfer, robustness to prompt injection, diversity/overfitting and user preference satisfaction. Evaluation cases require consented held-out samples and recorded generation model/prompt version. Training/evaluation contamination is disallowed. Use a mix of deterministic rules and independently judged, auditable comparisons; never call a sample merely "authentic" by a single score.

Learning policy: explicit corrections may propose changes; approved durable rules outrank inferred traits; repeated user acceptance can inform a proposed revision but not silently commit it. Drift alerts are explainable and opt-in where needed. Provide baseline vs. style vs. revised comparison with accessible differences and fact-preservation checks. Retraction/rollback must immediately affect new executions without rewriting historical execution receipts.

## 13. Threat model and failure cases

Adversarial matrix:
- Uploaded samples contain system-message imitations, tool instructions, URLs or exfiltration commands: treat as inert evidence.
- User uploads another person's confidential writing without rights: require appropriate ownership/consent attestations and enforce restricted use.
- Cross-tenant profile enumeration and ID guessing: deny before metadata disclosure.
- Agent requests a client profile without binding: deny; no guessed "closest" identity fallback.
- A publish operation races another revision: CAS conflict; never last-write-wins.
- User or admin revokes consent mid-job: fence new work; prohibit publication and downstream use after revocation; follow defined cancellation rules.
- Plugin disable while agent works: new admission denied; in-flight work bounded by approved lifecycle policy and no unauthorized post-disable side effects.
- Provider missing, token budget exceeded, unhealthy worker, insufficient samples: explicit typed degraded/unavailable/needs-more-evidence states.
- Cross-client blending and inference of protected/sensitive traits: reject.
- Malicious hook filters: sandbox/permission gate, typed validation, timeouts and fail-closed for security-relevant paths.
- Telemetry or logs include source text: redact; store only authorized metadata.

No covert behavioral profiling, consent-free voice cloning, unauthorized third-party impersonation, undisclosed learning, unbounded model calls or fabricated analysis results.

## 14. Observability and operational lifecycle

Record structured events for authenticated create/ingest/analyze/propose/approve/publish/bind/resolve/preview/feedback/revoke/delete, including permitted `correlation_id`, `request_id`, `tenant_id`, `user_id`, `profile_id`, `revision_id`, `persona_id`, `agent_id`, `plugin_id`, `capability`, `intent`, `model/provider`, `response_source`, `degraded_mode`, `fallback_level`, `latency_ms`, `status`, `error_type/code` and evidence counts. Protect high-cardinality values from Prometheus labels; do not include raw content or secrets. Persist audit trail according to canonical retention policy.

Admin sees job health, queue/backpressure, model availability, failures, rejection reasons, permission denials, revision conflicts, sample ingestion outcomes and retention/deletion status without unapproved sample disclosure. Enable/disable and upgrade preserve data, migrations and observability. Destructive actions require confirmation and enforce user/tenant policy.

## 15. Implementation slices and proof

| Slice | Deliverable | Required evidence |
| --- | --- | --- |
| WS-00 | Inventory existing docs, components, hooks, Persona PRs, storage and UI ownership | Real file paths, active/dead classification, reuse plan, no duplicate PRs |
| WS-01 | Typed profile/samples/revisions/consent schema and service contracts | Migrations and rollback; PostgreSQL RLS, CAS, provenance and tenant-denial tests |
| WS-02 | Existing hook/extension contracts audited and minimally extended if needed | Manifest validation, priority, timeout, disable fence, schema and permission tests |
| WS-03 | Actual sample import, extraction and human approval | Real bounded sample-to-trait pipeline, injection tests, provider eligibility, immutable publish proof |
| WS-04 | CORTEX, Persona, Agent and canonical runtime style resolution | Full authorized ingress -> execution trace, selected version attribution, cross-tenant denial |
| WS-05 | Consumer Writing Studio and admin management UI | Browser create, ingest, approve, publish, bind, preview, revoke; reload/readback, errors and responsive views |
| WS-06 | Feedback, fidelity/drift benchmarks, client/team workflows and release acceptance | Adversarial cross-client tests, live PostgreSQL, observed browser task, actual model output and rollback |

**Proof commands** (adapt exact suites to implemented paths and workspace):
```bash
python -m compileall src
pytest tests/ -q
ruff check src tests
mypy src
cd src/ui_launchers/Karen-AI-Theme
npm run lint && npm run typecheck && npm run test && npm run build
cd ../../..
docker compose config
```
Add targeted contract tests and real integration/browser acceptance for every implementation slice. Report commands actually executed and their outcomes; a documentation-only PR does not certify any new runtime features. CI evidence must match the *exact head SHA*. Preserve production first-boot, security and migration gates.

**Release go/no-go:** do not advertise Writing Studio ready until a real authorized user can produce a published profile from approved samples, apply it through canonical runtime to observed model output, inspect a persistent provenance receipt, switch tenant safely, revoke the profile, and observe the denial of further use. Admin UI must show actual backend readiness, not declaration-only readiness.

## 16. Feature recovery and documentation discipline

Before implementing, examine the repository for prior labels such as "Voice DNA", "VDNA", "Writing Studio", "KariSignature", communication-style profiles and Persona Studio. An empty exact-name search is not proof of absence. Reuse the strongest existing implementation and preserve its tests, migrations, guards and canonical paths. Rename only with migration/compatibility review and confirmed product approval.

Every implementing PR must amend this chapter's **status** and cite concrete implemented source paths, manifest version, migration IDs, corresponding backend/UI tests, exact-head checks, unavailable prerequisites and observed UX evidence. Keep proposed APIs visibly proposed until verified. If the current code differs, source plus executable tests take precedence over this blueprint.

## WS-01 implementation ledger (source-only, not consumer enabled)

**Implemented on the WS-01 feature branch:** `KariSignatureRequest`,
`KariSignatureRevision`, `KariSignatureAuthority`,
`KariSignatureResolver` and `KariSignatureResolution` in
`src/ai_karen_engine/core/runtime/prompt/karisignature_contract.py`.
This is a bounded, asynchronous, read-only style-resolution kernel. It reads
the current published revision through a host-supplied authority, compares
canonical tenant/profile identity, validates the approved expression schema,
verifies the SHA-256 digest, and requires the host to return **literal True**
for current use authorization. Failure or revocation denies the resolution.
No raw sample text is admitted. Approved fields reuse
`PersonaAssemblyPolicy.sanitize_persona` and cannot set provider, model,
tools, memory, permissions or system policy.

**Current limitations:** This slice does **not** provide a production
`KariSignatureAuthority` adapter, PostgreSQL profile/revision persistence,
consent or source-sample ingestion, publication workflows, prompt-runtime
selection, provider execution, user/admin UI, agent bindings or consumer
acceptance. The interface cannot grant permission merely because a caller
instantiated a revision. Production adapters must fetch the authoritative
published version and check active RBAC/consent/tenant and purpose. Do not
enable style selection or claim user availability until those paths are wired
and tested. The bounded enum vocabulary is intentionally conservative and
is subject to versioned review before broader internationalization.

**Proof target:** `pytest tests/core/runtime/test_karisignature_contract.py -q`,
`ruff check src/ai_karen_engine/core/runtime/prompt/karisignature_contract.py
tests/core/runtime/test_karisignature_contract.py`, canonical prompt/persona
regressions, and exact-head CI. WS-02 must reuse the already-existing database
and user-preference owners for scoped immutable revision storage and authority;
it must not introduce a duplicate prompt assembler, model router or ACL store.

## WS-02 read-only persistence candidate (not consumer enabled)

The follow-on repository slice defines private, owner-scoped
`karisignature_profiles` and `karisignature_revisions` PostgreSQL tables
with tenant and authenticated-user RLS, granted-consent and published-revision
admission, immutable revision payloads and a current revision foreign key.
The `PostgresKariSignatureAuthority` adapter in the existing platform
personalization boundary implements the WS-01 host protocol using
`async_transaction_scope(tenant_id=..., user_id=...)`. Every live read must
match the actor, tenant, purpose, profile, revision number and content digest;
the resolver performs its own bounded expression and digest checks. Source
samples remain absent from this read model.

**Publication remains disabled.** The migration deliberately declares no RLS
INSERT/UPDATE/DELETE policy. WS-02 does not create or populate profiles,
accept consent, authorize organizational/client delegation, register a
singleton runtime provider or expose HTTP/UI controls. Later publication must
be a separate, audited compare-and-swap owner with independent permission and
deletion/retention proof. Since reads and permission checks currently use
distinct short transactions, they do not by themselves prove atomic revocation
with concurrent live streaming. Consumer activation must resolve that race
at the existing execution/persistence authority.

Proof: `tests/core/runtime/test_karisignature_postgres_authority.py`,
PostgreSQL migration/first-boot CI, RLS denial under mismatched actor/tenant,
and fresh exact-head security review. Source merge is not deploy acceptance.
