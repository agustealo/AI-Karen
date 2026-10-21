# AI-Karen Persona Skills & Learning Data Guide

**Status:** design and implementation specification, not a deployed capability  
**Audience:** End users, workspace administrators, developers, security and product teams  
**Companion:** [First-Class Persona Implementation](KPERSONA_FIRST_CLASS_IMPLEMENTATION.md) (PR #501)  
**Product principle:** A user defines who a persona helps them be; Karen explains what evidence, resources and practice would improve that persona. It never claims to have learned, accessed or mastered something without verified provenance.

## 1. Executive summary

A persona is a **named, purpose-specific, user-owned collaborator**. Examples include **Troy (Graphic Designer)**, **Morgan (Business Strategist)**, **Echo (Music Producer)** and **Maya (Family Organizer)**. Name and role describe how the user wishes to collaborate. They do not create a distinct AI model, grant permissions, verify a professional qualification or guarantee practical skill.

The system must make learning requirements understandable, answer *"What information would help this persona do its job?"*, identify approved resources already available, surface gaps and let the user provide or authorize additional knowledge. This is a **Data Needs Advisor** integrated into Persona Studio and the canonical runtime. It is not a new autonomous agent or ungoverned crawler.

**Three distinct ways a persona improves:**

1. **Retrieval and grounding:** Karen reads authorized, current, purpose-relevant resources at task time. This is *using* information, not training weights.
2. **Preference adaptation:** explicit user feedback or evidence-backed proposals become persona-scoped, approved, versioned and reversible preferences. This is *learning user preferences*, not model fine-tuning.
3. **Evaluated capability improvements:** controlled tests reveal what the configured model and authorized tools can do. An administrator can separately authorize data curation, evaluation, or future training workflows if supported. Nothing here silently fine-tunes a model.

### Source-of-truth mapping

- **ChatRuntime** owns request context, persona snapshot and execution receipts.
- **CORTEX** owns intent, routing decisions and action eligibility; it does not execute.
- **PromptRuntime** compiles allowed persona instructions within system and task policy.
- **PersonaService** owns persona definitions, revisions, scope associations and approved preference changes.
- **UserModel** infers *candidate* preferences, never unilaterally approves or installs them.
- **NeuroRecall** plans constrained retrieval; **NeuroVault** and governed repositories control retention, deletion and lineage.
- **Skill/tool registry** owns executable manifests and real availability; a persona stores references, never tool permissions.
- **assistant-ui** presents shared chat, persona controls and feedback. Optional **AG-UI** projects authenticated runtime-observed events.

Before implementation, inventory existing owners and reuse their tables, registries and APIs. The logical contracts below do not mandate independent subsystems.

## 2. Guide for end users: creating Troy

### Fast start

1. In Persona Studio select **Create** or say: **"Create Troy, my graphic designer for luxury brands."**
2. Karen proposes a **name**, **title**, **purpose**, **specialties**, and short **collaboration description**. A role template is editable. It is not a professional credential.
3. Review the proposal and select **Create**. Save and Activate are separate operations, each acknowledged by the server.
4. Karen shows **What would help Troy?** with a short prioritized checklist; you may skip everything and start chatting.
5. Choose existing projects, upload references, connect permitted data sources, supply feedback, or select **Not now**. Each resource attachment requires authorization.
6. Ask Troy for real work. Karen uses only accessible resources, registered capabilities and valid permissions.
7. Correct Troy in normal conversation: **"Use higher contrast and fewer gradients for Brand A."** Apply now for the current request, or approve **Save to Troy** after reviewing the proposed change.
8. Under **What Troy knows**, inspect attached sources and preferences, their last update, permissions and removal controls. Revocation affects subsequent retrieval and requires cache invalidation.

### What Troy might need

| Requirement | Useful sources | Why it helps | Optional? |
|---|---|---|---|
| Brand identity | Brand guide, logo rules, typography/color tokens | Preserve brand consistency | Yes |
| Design references | Approved past work, moodboards, feedback | Recognize desired direction | Yes |
| Deliverable requirements | Destination dimensions, formats, accessibility/production constraints | Produce usable specifications | Task dependent |
| Workflow | Preferred review stages, naming conventions, approval process | Coordinate collaboration | Yes |
| Design literacy | Properly licensed references, public documentation, relevant terminology | Explain concepts accurately | No private dataset required |
| Outcome feedback | Accepted/rejected proposals and user corrections | Suggest preference improvements | Opt-in |

**Not needed by default:** full mailbox, private household records, all business drives, login credentials, entire browsing history, biometric data or other people's unpublished content. More data is not inherently better.

### Plain-language status labels

- **Ready to help:** sufficient permitted context for the requested task; not a promise of professional mastery.
- **Could work better with:** optional missing data category, benefit and safest collection route.
- **Needs access:** the specific source exists but is not authorized. Never reveal unauthorized source titles or existence across tenants.
- **Skill available / unavailable:** live backend tool eligibility and health, not a static badge.
- **Preference suggested:** proposed but not persisted.
- **Preference saved:** only after a valid server persistence receipt.
- **Data outdated / revoked:** show a truthful reason and corrective action.

## 3. Industry-agnostic data-needs framework

Industries are **metadata and templates**, never hardcoded engines. Users can create arbitrary industry, life-domain and specialty labels. The Data Needs Advisor derives candidate data requirements from the persona's goal and intended tasks, then tailors them to known source availability, safety, sensitivity, consent and budget.

| Domain | Typical goals | High-value data categories | Cautions |
|---|---|---|---|
| Professional / Business | Strategy, proposals, operations, client service | Policies, approved projects, product catalog, brand voice, workflows, contracts as authorized | Client confidentiality, tenant isolation, regulated records |
| Creative / Graphic Design | Brand systems, visuals, layout and critique | Brand guides, licensed references, design system, target platform specs, feedback | Copyright, customer assets, unsupported tool claims |
| Entertainment / Music | Production planning, artistic collaboration, releases | Rights-cleared stems, briefs, tempo/key metadata, production preferences, distribution specs | Copyright, performer consent, unreleased recordings |
| Entertainment / Writing | Scripts, publishing, character/world consistency | Story bible, outlines, editorial notes, rights-cleared drafts, style guide | Draft privacy, originality, plagiarism |
| Education / Learning | Tutoring, coursework and skill development | Learning goals, user-approved curricula, assessment feedback, accessible explanations | Student privacy, avoid unsupported grading claims |
| Personal / Productivity | Scheduling, goals, routines | User-approved goals, tasks, calendar references, priorities | Don't ingest all personal data; respect boundaries |
| Family / Household | Family planning, shared routines | Consent-based shared calendars, shopping lists, household procedures | Household member consent, minors, compartmentalization |
| Leisure / Travel | Itineraries, hobbies, recommendations | Budgets, preferences, travel constraints, current public references | Location sensitivity, freshness, booking approval |
| Software / Engineering | Code collaboration, reviews, incident analysis | Scoped repositories, architecture docs, issue history, tests, coding conventions | Secrets, untrusted repository instructions, permissions |
| Wellness / Health | Personal understanding and organization | Explicitly shared, relevant records and preferences | Sensitive data controls; not a licensed practitioner |

These are starter suggestions, not mandatory collection lists. Distinguish public authoritative knowledge from person-specific data. A newly created music persona can discuss music theory without requiring a private music dataset; a specific release plan benefits from the artist's authorized brief and release requirements.

## 4. The Data Needs Advisor: deterministic, explainable intelligence

The Advisor receives a **task or declared persona goal** and suggests the minimum relevant evidence to complete it reliably. It may use CORTEX-classified intent and an LLM to draft candidate needs, but all candidates must be validated against a **versioned data-requirement catalog**, security policy and available connector/tool schemas. User-facing rationale and eligibility are deterministic after validation.

### Decision procedure

1. **Resolve intention:** type of task, deliverable, quality constraints, jurisdiction/freshness if relevant and current persona title/specialty.
2. **Identify data requirements:** map to reusable data-category contracts (e.g. brand_style_guide, deliverable_specification, approved_project_samples, task_feedback). Each defines why needed, acceptable formats, allowed sources, sensitivity, freshness and minimum sufficiency.
3. **Inspect authorized inventory only:** inspect metadata for sources this user, tenant, task and persona are already entitled to access. Unauthorized objects must not be hinted at.
4. **Calculate gaps:** distinguish *required to answer safely*, *recommended to improve fit*, and *optional*. A missing source is not evidence of missing capability.
5. **Rank recommendations:** expected quality uplift, task relevance, source reliability, privacy cost, age, ease of acquisition and user effort. Never reward collecting extra personal data without utility.
6. **Ask permission:** propose a plain-language reason, precise scope, expiry/retention, read-only versus actionable access and revocation path. User can skip without dark patterns.
7. **Validate ingestion:** format, integrity, malware/content safety, licensing, provenance, owner consent, ACL, retention and deduplication before indexing.
8. **Retrieve under ACL intersection:** every use re-checks user, tenant, source permission, purpose, persona scope and revocation. Resource association itself is never a permission grant.
9. **Measure result:** task-specific user feedback and objective evidence where possible. Suggest corrections with provenance; no hidden learning.
10. **Reevaluate gaps:** when scope, task, skill, source freshness or user approval changes, recompute recommendations. Never claim dataset completeness based on number of files.

### Need score (ranking only, not truth)

`priority = task_relevance × expected_utility × source_trust × freshness − privacy_cost − user_effort − maintenance_cost`

Weights are calibrated using consented evaluation and centrally configured per use case, not arbitrary constants in UI. The Advisor must return **reason codes**, **data categories**, **minimum acceptable evidence**, **available count/freshness** where authorized, and **next user action**. Hide any confidence number that lacks calibration. The UI should normally show 2–4 high-value next actions, not a giant dataset questionnaire.

### Recommendation example

> **Troy could use your brand guide.**  
> Why: it establishes logo spacing, colors and typefaces so future proposals align with your brand.  
> Source: upload a file or select an existing authorized project.  
> Access: read-only for Troy; remove any time.  
> **Attach guide** · **Skip** · **Why this?**

Never recommend scraping paid datasets, copying competitors' protected designs or collecting a family member's private records without proper rights and consent.

## 5. Dataset lifecycle and quality gates

A **dataset** may be a single reference, a curated collection, structured records, an authorized connector search scope or a task-specific evaluation set. Avoid implying every persona needs massive bulk training data.

**Lifecycle:** proposed → user authorized → discovered/ingested → scanned/validated → indexed with ACL/provenance → available for scoped retrieval → evaluated → refreshed/expired/revoked → deletion propagated.

**Metadata contract:** `dataset_id`, `tenant_id`, `owner_id`, `source_kind`, `data_category`, `purpose`, `resource_locator`, `license/usage_rights`, `consent_reference`, `classification`, `source_version`, `content_fingerprint`, `collected_at`, `verified_at`, `expires_at`, `retention_policy`, `revoked_at`, `ingestion_status`, `provenance`. Reuse existing governed storage metadata; never store API secrets or the entire raw source in persona revisions.

**Validation:** source authenticity, permissible use, schema or file format, extraction quality, duplication, conflicting facts, timestamp/freshness, malicious embedded instructions, test contamination, and privacy/PII minimization. Quarantine untrusted or invalid imports. No source content can modify system instructions or permission policy.

**Sufficiency:** depends on the intended task; use criteria rather than simplistic document counts. For example, a brand-voice task may require a current style guide and recent approved writing samples; a printing task may require production specifications. Explain what cannot be validated. Do not invent "80% trained" progress percentages.

**Coverage matrix:** map goals → required evidence → authorized available sources → freshness → validation state → observed evaluation outcome. Separate objective checks (e.g. required dimensions present) from subjective preference satisfaction.

**Deletion:** deleting persona references must not silently delete a shared source; revoking the source must immediately block new retrieval for all linked personas, invalidate indexes/cache paths and trigger governed derivative cleanup. Preserve required audit evidence under retention policy without republishing sensitive content.

## 6. Skill system and educational semantics

A persona's **role/title** is a collaboration label. A **domain specialty** represents declared focus; a **method** represents preferred working process; an **executable skill** references a registered and eligible tool or workflow. Distinguish:

- **Declared**: the user says Troy focuses on typography. No proficiency claim.
- **Knowledge-grounded**: Troy has authorized reference material relevant to typography.
- **Tool-capable**: a registered design tool is available, healthy and permitted for a specific operation.
- **Evaluated**: bounded tests show performance on a task family with model/tool/version provenance.
- **Approved preference**: the user confirmed and saved a behavior for a specific persona/scope.

Skill improvement does not imply a model's underlying weights were updated. If model training becomes a separate product, it requires explicit opt-in, rights checks, curated train/validation/test separation, deduplication, memorization/privacy assessment, safety regression, rollback and model-registry promotion. No training authority belongs to persona documents.

## 7. Technical contracts and endpoints (logical, map before implementing)

**Persona data-needs assessment request**
- Authenticated `persona_id`, intended task or declared goal, optional workspace context and idempotency key.
- User, tenant and conversation scopes come from server auth, never trusted from the payload.
- Results: `assessment_id`, `persona_revision`, `task_family`, `requirements[]`, `authorized_source_summaries[]`, `gaps[]`, `recommendations[]`, `policy_version`, `correlation_id`.
- Each requirement: `category_id`, `importance` (required | recommended | optional), `why`, `minimum_evidence`, `accepted_source_types`, `freshness_policy`, `sensitivity_class`, `status`, `reason_codes[]`.
- Return 403/404 without existence leakage for unauthorized persona IDs; degraded inventory gets an explicit unknown status, never "no data found".

**Source authorization**
- User selects resource/scope/read mode and consent/retention; backend validates resource ACL and association, returns durable authorization receipt.
- Source revocation separately triggers retrieval cache/index invalidation. Distinguish permission denied from not indexed.
- Never embed raw secrets or cross-tenant resource IDs into client-visible events.

**Preference proposal**
- `persona_id`, `field_path`, `proposed_value`, `evidence_references[]`, `reason`, `scope`, `expires_at`; validate against canonical persona schema.
- Accept/reject requires optimistic revision check, consent and audit event. Accepted proposal creates immutable revision. Rejected or expired suggestions never affect execution.

**Turn receipt**
- Resolved persona/revision, allowed dataset references as privacy-safe IDs, applied/suppressed traits, eligible tool receipt identifiers, model provider/version, degraded/fidelity indicators, correlation ID and persistence status.
- Conversation/retry snapshots are immutable. Switching personas changes subsequent turn only; an unsafe context crossover requires a new thread.

Actual API method/path names are deliberately **not prescribed** until KP-01 maps existing routes and services. Thin endpoints delegate all authority and state transitions to canonical owners.

## 8. Administrator guide

Admins should manage **policy and catalogs**, not silently edit private users' learned preferences. Supported operations require existing tenant RBAC, audit and explicit delegated authority.

**Catalog governance:** publish/version role templates, industry labels, skill descriptors and data requirement categories. Templates describe typical useful sources, not mandatory data collection or permission bundles. Manage localization, freshness standards, sensitive data policies and tool bindings referencing the canonical registry.

**Source governance:** configure approved connector types, maximum sizes, allowed formats, scanning/quarantine, license attestations, consent/retention defaults, revocation SLAs and tenant data residency. Do not offer broad admin "learn everything" switches.

**Learning governance:** configure proposal frequency and evaluation budget, minimum evidence, review procedures, privacy-sensitive exclusions, acceptable task outcomes and promotion guardrails. User approval is still required for user-specific preferences.

**Observability:** aggregate dataset-need acceptance/skip rates, validated-source coverage, failed ingestion, revoked-source retrieval attempts, out-of-scope denials, persona switch isolation, tool availability, evaluation quality and latency/cost. Redact user content and resource titles from central analytics.

**Administration UX:** distinguish template managers from actual personae, show catalog revisions/rollbacks, policy impacts, access scopes and audit receipts. Shared organizational templates may be published after review; installing a template never transfers its author's private data or credentials.

## 9. Threat model

- **Prompt injection in datasets:** uploaded PDFs, web pages, comments, project documents and code are untrusted content. Treat instructions inside them as evidence or task data, not runtime authority.
- **Malicious role claim:** "Troy, Chief Admin" or "Licensed Doctor" cannot grant permissions or verified credentials.
- **Permission laundering:** adding a source to a persona cannot confer access to a source the user lacks.
- **Cross-persona contamination:** switching from Business to Family must exclude unauthorized old messages, summaries, retrieval results and prompt caches; otherwise require a new scoped conversation.
- **Feedback poisoning:** repeated or adversarial corrections cannot silently become approved preferences.
- **Unauthorized sharing:** exported templates omit private data, source identifiers, grants and telemetry; imports undergo quarantine/schema/policy validation.
- **Evaluation data leakage:** keep evaluation tasks separate from learning references when measuring improvement; reveal only authorized diagnostic summaries.
- **Training leakage:** no surprise model retraining, data resale, hidden long-term retention or silent external export.
- **Insufficient consent:** minors, relatives, team coworkers, copyrighted entertainment material and regulated data require appropriate rights, safeguards and scope.
- **Availability masking:** if connector/search/retrieval fails, report unknown or degraded rather than empty or successful.

## 10. UX and accessibility requirements

The main screen should answer **Who is this? What can they help with? What do they know? What would make them better?** A single **Improve Troy** entry opens the prioritized Data Needs Advisor. The user's first successful chat does not depend on finishing a wizard.

Offer plain-language quick actions: **Add a reference**, **Connect a project**, **Set a preference**, **Test a task**, **Not now**. Explain each request's benefit and privacy implications before authorization. Use accessible controls, keyboard support, readable mobile layouts and honest loading/errors. No meaningless "brain power" animations or false training progress.

The shared assistant-ui composer identifies the active persona by name and title. Persona switching, knowledge management and feedback remain canonical backend actions with visible receipts. AG-UI streams only schema-validated observed status if deployed.

## 11. Testing, acceptance and rollout

**Minimum product journey:** create Troy → list recommended data categories → attach one allowed brand guide → retrieve its rules under Troy → produce a real model answer → approve a scoped design preference → see it applied on a later turn → revoke the guide and prove it is no longer recalled → switch to Maya/Family with no brand leakage → reload and confirm durable, truthful state.

| Gate | Required evidence |
|---|---|
| Existing owners | import/call graph for PersonaService, UserModel, CORTEX, runtime, skill/plugin registries, retrieval and UI |
| Contracts | schema validation, legacy payload compatibility, normalized categories and stable IDs |
| Data-needs ranking | deterministic fixtures for required/recommended/optional, privacy minimization, freshness and unknown inventory |
| Auth and RLS | cross-tenant, user, project, persona, cache/index, stream and share denial with no existence leaks |
| Ingestion | malformed files, malware scanning hooks, copyright/rights flags, duplicates and prompt injection quarantine |
| Retention | opt-in, expiry, revocation, deletion propagation and shared-source safety |
| Runtime | immutable snapshots, real provider path, fallback truthfulness, zero tool privilege changes |
| Learning | accepted vs rejected vs pending feedback, immutable revisions, race tests, no implicit fine-tuning |
| Evaluation | held-out task preservation, baseline comparison, factual correctness, privacy/fidelity and cost |
| UX | create/skip/improve/attach/teach/revoke/switch, accessible browser and responsive screenshots |
| Telemetry | redaction, correlation IDs, denial reasons, evidence lineage and latency budgets |

**Quality commands**, when applicable to changed files: `python -m compileall src`, `pytest tests/ -q`, `ruff check src tests`, `mypy src`, `npm run lint && npm run typecheck && npm run test && npm run build`, `docker compose config`. Run scoped suites first; do not claim these gates have passed before execution.

### Delivery waves

1. **KP-01/02:** owner/reference audit, typed role/skill/data-need catalogs and safe adapters; no duplicate registry.
2. **KP-03/04:** real source associations, consent, versioned snapshots, ACL-intersected retrieval and receipts.
3. **KP-05:** approachable Studio, Data Needs Advisor UX and assistant-ui composer integration.
4. **KP-06:** real-model and held-out task evaluation of the learned preference and knowledge effects.
5. **KP-07/08:** context-aware, opt-in recommendations, safeguarded proposal learning, drift/fidelity and export.
6. **KP-09:** end-to-end security, human usability, performance, docs, rollout switches and screenshots.

**Release rule:** No "persona trained", "source learned", "project connected", "tool ready", or "preference saved" UI claim without a matching persisted and authorized backend fact. Design and proof remain separate milestones.

## 12. Decisions that must remain true

1. A persona is a scoped collaboration contract, not an agent, model or permission principal.
2. Users can start with zero uploaded datasets; source recommendations are proportional to real tasks.
3. Industry and skill templates are extensible data, not branching implementations.
4. Knowledge use, preference adaptation and model training are different operations with different consent.
5. Existing runtime, memory, skills and security owners remain authoritative.
6. Proficiency and quality are evaluated, never inferred from a title or dataset count.
7. Users can inspect, refuse, update and revoke what each persona knows.
8. Privacy and authorization outrank seamless switching or personalization.


---

# Adversarial Review: Facts Convergence, Minimal Data Needs and Delivery Contract
**Revision:** 2026-10-21. **Status:** architecture correction, not implementation or verified runtime performance.

## Engineering verdict

Retain the *user outcome* of the Advisor, not its proposed subsystem footprint. The first release needs a task-aware "What would help?" projection using existing persona, UserModel, facts, memory retrieval and skill registry authority. The guide's catalog, lifecycle and scoring descriptions are **logical contracts**, not approval to create tables, agents, stores, distinct AI evaluators or an independent registry.

### Repository evidence inspected

- \`src/ui_launchers/Karen-AI-Theme/src/components/settings/PersonalFactsSettings.tsx\`: currently presents facts with \`id,text,visibility,domain,category,importance,confidence,source,sourceType,usage_count,created_at,last_used\`; fetches \`/api/memory/facts\` and \`/api/memory/facts/suggestions\`. UI \`visibility\` and \`domain\` enums are coarse and should **not** be treated as proof of correct resource authorization.
- \`src/ai_karen_engine/core/memory/signals/general_fact_classifier.py\`: recognizes explicit first-person identity, work, business, project, skill and routine facts; explicitly does not persist by itself.
- \`src/ai_karen_engine/core/personalization/contracts.py\`: UserModel already has evidence/provenance and scoped preferences and goals, with an existing preference scope enum. Persona-scoped targeting may need a canonical typed extension, not an independent preference engine.
- \`supabase/migrations/20261015020000_25_profile_fact_tenant_rls.sql\`: enables and forces RLS on \`public.profile_fact\`, documenting it as a **rebuildable projection derived from governed \`memory_event\`**. Existing migration does not itself prove production RLS or every Facts API path is safe.
- \`src/ai_karen_engine/services/persona/persona_service.py\` and \`src/ai_karen_engine/core/persona/contracts.py\`: existing PersonaService, core dataclasses and caches require active-path contract reconciliation before expanding persona features.

These observations are file-level checks, **not** runtime tracing or completed security tests. Do not assume frontend Facts necessarily maps one-to-one to \`profile_fact\` or all UI CRUD operations are correctly wired: trace the actual API-to-storage path in KP-01.

## Canonical concepts and one owner each

| Concept | Authoritative owner | Persona relationship | Never do |
|---|---|---|---|
| User's factual assertions and their evidence | Existing governed memory event store / Facts projection | Scoped, authorized reference; view from persona | Replicate raw fact in every persona |
| User preferences, evidence and goals | UserModel with governed persistence | Approved scope filter or revised persona contract | Fork a persona-specific preference inference engine |
| Persona name, role, collaboration contract, revision | PersonaService | Canonical definition | Store credentials/tools as a persona permission |
| Files, design assets, documents | Existing resource/connector and ACL owner | References intersected with source ACL | Copy all asset contents into persona tables |
| Knowledge sufficiency recommendation | ChatRuntime orchestration using intent, existing policy and resource metadata | Ephemeral, explainable task-scoped assessment | Create another autonomous orchestrator or persist every gap |
| Executable tools and skills | Existing manifest/registry plus CORTEX/RBAC | Descriptive, non-authorizing binding reference | Treat badge, industry or title as an installed capability |
| Chat/stream rendering | Shared assistant-ui; optional authenticated AG-UI observed events | Show backend-confirmed effective persona state | Maintain client-side second source of truth |

### Facts and persona-scoped knowledge resolution

A fact can be globally relevant to the owner, scoped to a project/persona, or too sensitive to surface. These are **use constraints**, not a new copy of the fact. Store a canonical reference, purpose, consent/policy ID, effective scope, validity and revocation metadata in the existing governed infrastructure wherever possible. Permission for use is the **intersection** of tenant + authenticated actor + underlying resource ACL + purpose + persona scope + active consent + conversation boundaries. "Global" does not mean public, cross-tenant or every-persona visibility.

Example: "Brand A uses black and ivory" may be stored once as a source-backed brand fact; Troy is approved to use it on Brand A tasks. Morgan may access it only if separately permitted; Maya may not see it. An explicit user correction can be offered as a persona-scoped preference without turning the preference into a universal asserted fact. Separate assertions about external reality from opinions, preferences and operational instructions.

**Conflicts:** show source provenance, validity and competing claims. A recent high-confidence assertion does not automatically overwrite an approved fact; route correction through canonical lifecycle. **Revocation:** deny new retrieval immediately through authorization checks, then propagate cache/index and derived-view removal under governance. Do not falsely promise physical deletion of already-issued responses or legally retained audit records.

## Reduce Advisor to three outcomes

For an intended task, the Advisor returns only:
1. **Ready:** Karen has enough authorized, current evidence and eligible capabilities to attempt the task. Not a guarantee of correctness.
2. **Helpful next information:** at most three context-specific data or preference recommendations, with benefit, source class and user-controlled attach action.
3. **Blocked/unknown:** one genuinely required datum, capability or authorization is missing; distinguish absent from inaccessible, stale, unindexed or service failure, without leaking unauthorized existence.

No mandatory dataset at persona creation. No invented "skill learned" or percentage-complete meter. No LLM-generated automatic grants. The original algebraic recommendation formula is a **hypothesis**, not a shipping requirement: begin with deterministic task requirement rules and explicit reason codes; introduce rank models only after measured quality uplift, privacy cost and consent evaluation.

### Type-level logical minimum

\`DataNeedAssessment\`:
\`persona_id\`, \`persona_revision\`, \`task_family\`, \`outcome\` (ready | helpful | blocked | unknown), \`requirements[]\`, \`authorized_source_refs[]\`, \`recommended_actions[]\`, \`reason_codes[]\`, \`policy_version\`, \`correlation_id\`, \`inventory_health\`.

\`DataNeedRequirement\`: \`category\`, \`purpose\`, \`criticality\`, \`acceptable_source_types\`, \`minimum_evidence\`, \`freshness_rule\`, \`sensitivity\`, \`status\`. A requirement is associated with task intent, not mechanically inferred from industry alone.

\`RecommendedAction\`: \`action_type\`, \`benefit\`, \`target_scope\`, \`confirmation_required\`, \`reason_code\`. All mutations happen via existing authorized APIs; this assessment itself is read-only and does not persist user content.

Do not create these as tables or new URL routes until current services, schemas, storage and access control have been traced. Schema versions, unknown/degraded status and authorized redaction must be explicit.

### Five example assessments (non-binding product contract)

| Persona / intent | Minimum context needed | Optional quality improvement | Unsafe default to avoid |
|---|---|---|---|
| Troy / draft a Brand A logo concept | Brand name, intended audience, requested medium | Current brand guide, approved style references | Full client drive, unrestricted external image search |
| Morgan / prepare client proposal | Scope, customer requirements, requested output | Approved price sheet, current policy | All company contracts and mailboxes |
| Echo / explain chord progression | User's musical question | Genre/reference preferences | Bulk import of copyrighted tracks |
| Maya / plan household meals | Household dietary choices user opts to share, time/budget as relevant | Approved shopping list and existing recipes | Profiling absent household members |
| Coach / teach Python | Learning goal and current difficulty | Approved curriculum, learner corrections | Entire device files or private school records |

The advisor should be *useful from the first task*. If no external resource is necessary, say so. If a user asks for the same goal across roles, use persona-scoped preferences without duplicate fact persistence.

## User, administrator and developer responsibilities

**User-facing:** Persona Studio has one **Improve this persona** action, not a separate training console. Start with real work; surface no more than three targeted requests inline when useful. Show **What Karen knows**, **What Troy can use**, **Suggested improvement**, **Not now** and **Remove access**. The first is a view on canonical Facts/evidence; the second is an authorization-filtered projection, not a second facts list. Keep explicit confirmed actions for attach/approve/revoke. Show the current persona in the one shared assistant-ui composer; never require users to learn dataset jargon.

**Admin-facing:** govern approved data types and size, sensitive-content rules, retention, import quarantine, policy versions, connector eligibility and aggregate health. Don't expose other tenants' fact titles or private preference contents. Don't provide a universal training permission.

**Developer-facing:** resolve the current \`/api/memory/facts\` path, \`profile_fact\` lineage, memory admission, UserModel preference repository and PersonaService; identify any duplicate stores before new migrations. Build assessment as a pure/testable service function owned by existing runtime or its canonical subordinate service. Thin API ingress delegates. On degraded retrieval, return \`unknown\`, not zero sources. Log reason codes, latencies and scoped counts, never fact text or secrets. Scope cache keys by tenant, actor, persona revision, resource/consent policy version and relevant task fingerprint. Evaluate invalidation on revocation and new approvals.

## assistant-ui and AG-UI boundaries

**assistant-ui extensively where applicable:** reuse shared composer, thread view, persona selector, user-confirmation actions, inline evidence/source chips, attachment picker, feedback actions, inspect/compare and accessible empty/error states. These components are views of server-confirmed state, not app-level duplication. Verify \`@assistant-ui/react\` installation and import/build health before migrating components. Avoid a persona-specific chat runtime.

**AG-UI only when useful:** typed, versioned, authenticated projections of genuine long-running data ingestion/validation, scoped knowledge retrieval, evaluation progress or persona activation/learning receipts. Ordinary facts list CRUD, simple switching and static recommendations should use normal API state updates, not extra streaming infrastructure. AG-UI must never carry raw facts, unredacted filenames or other-persona context unnecessarily. Replay, reconnect, retry, cancellation and cross-tenant redaction require proofs.

## Adversarial acceptance matrix (must fail closed)

1. Personal Facts UI visibility=\`global\` still cannot cross tenant or implicitly authorize Maya to retrieve Troy-only project facts.
2. A single approved brand fact is reused across multiple authorized personas without duplicating canonical content; later source correction updates the governed projection.
3. The same text can be a preference ("I like gradients") or fact ("Brand A's logo has a gradient"); they do not share unintended lifecycle or scope.
4. Existing UI \`/api/memory/facts\` behavior is traced to the actual persistent owner; malformed, rejected and unavailable states are truthful.
5. No document produces "trained" status or skill verification merely on attachment; only consented evaluation can support measured proficiency.
6. Revoked data is rejected at the retrieval authorization boundary even if a stale vector/cache match returns it.
7. The Advisor suggests at most three useful actions or explicitly confirms none needed; it never demands bulk datasets for general knowledge.
8. Missing metadata on connector outage returns \`unknown\`, not \`ready\` or \`no data\`.
9. Unapproved feedback remains proposal only; acceptance is revision-checked, audited, tenant-scoped and rollbackable.
10. assistant-ui navigation/reload preserves backend-selected persona; AG-UI replay never reveals unauthorized facts and does not create alternate state.
11. A malicious uploaded source cannot install skills, override prompts, change model/provider or grant external tool access.
12. Paired real-model tasks show the advisor improves usefulness when relevant data is provided, with unchanged fact correctness and bounded cost/latency.

## Updated gates and ruthless scope budget

- **KP-01 (must precede migration):** inspect and document runtime call graph of Facts UI → API → memory event / profile fact; UserModel proposals and PersonaService contracts. Confirm what exists versus what only appears in UI. Provide an owner matrix and duplicate data flow audit.
- **KP-02:** align typed persona/facts scope contracts, classification of fact vs preference vs resource reference, and reason codes. No standalone data-need registry without demonstrated requirement.
- **KP-03/04:** single real Postgres-backed vertical path: create Troy, authorize one source, resolve once per turn, retrieve under ACL, apply one approved scoped preference, persist receipt and survive restart. Prove RLS/rollback, concurrency and revocation.
- **KP-05:** deliver simple task-triggered Advisor in shared assistant-ui; existing Facts gets an authorized cross-link and truthful empty/degraded states.
- **KP-06:** evaluate against no-Advisor baseline on held-out tasks, measuring factual accuracy, task completion, user effort, latency, token/retrieval cost, accidental over-collection and denied-access leaks.
- **KP-07/08:** defer drift scoring, passport, broad catalogs and skill evidence ranking until KP-06 verifies material value.
- **KP-09:** browser, accessibility, tenant/RBAC, streaming, deletion and admin policy acceptance. Human review before consumer exposure.

**Deletion rule:** if a new persona capability duplicates Facts/UserModel/memory, replace it with an authorization-scoped projection and delete the duplicate only after reference and migration audits. Never delete memory events, RLS, auth or audit implementations merely because a simpler design exists.

**Final decision:** Ship one trustworthy, task-aware "What would help?" interaction. No new training platform, no new memory system and no independent Advisor agent. One runtime, governed Facts, scoped persona revisions, truthful receipts and measured usefulness.
