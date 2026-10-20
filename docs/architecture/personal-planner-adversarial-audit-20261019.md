# Personal Planner: adversarial audit and phased delivery

Date: 2026-10-19. Source inspected: main, tree 712f07318da036fe260a9583a01ec35a1e62681e. **Source-only inspection, not runtime or UX acceptance evidence.**

## Verdict and authority

Karen has durable **agent automation** tasks, cron/queue leases, personal cognitive goals and personalization. It does **not yet demonstrate** a first-class human life planner with Today/Week/Calendar/Goals, atomic chat edits, user-facing recurrence and verified reminder delivery. Do not portray these capabilities as shipped.

**Boundary:** Human tasks/plans are not agent executions. Keep separate state machines. Attach optional execution linkage and receipts. No second orchestrator, standalone imported task platform, duplicate user-preference storage or frontend-authored truth.

| Existing component | Evidence | Reuse or constraint |
|---|---|---|
| Saved automation definitions | `src/ai_karen_engine/api_routes/automation/tasks.py`, `services/automation/definitions.py` | Machine-task contract, not human planned activities |
| Durable SQL automation authority | `supabase/migrations/20260923010000_16_automation_scheduler_authority.sql` | Tenant RLS, queue/cron leasing foundations, not personal task schema |
| Cron worker | `src/ai_karen_engine/api_routes/automation/cron.py` | Reuse queue/leases for reminder delivery; keep auth + receipt boundary |
| Autonomous training scheduler | `src/ai_karen_engine/api_routes/automation/scheduler.py` | Separate domain. Contains `bypass_user_context_func`; review authorization before any broader use |
| Agent task UI | `src/ui_launchers/Karen-AI-Theme/src/components/automation/TasksPage.tsx` | Existing agent instructions/run/reviews UI, not personal planner |
| Calendar primitive | `src/ui_launchers/Karen-AI-Theme/src/components/ui/calendar.tsx` | UI component only, not calendar persistence |
| Goal semantic model | `src/ai_karen_engine/core/personalization/goals/contracts.py` | Reuse linked goal semantics; avoid duplicate goal authority |
| Personalization | `src/ai_karen_engine/core/personalization/runtime.py` | Derived memory state and preferences; read for suggestions only |
| Prior task-ownership design | `docs/architecture/paperclip-inspired-task-ownership.md` | Fencing pattern and warning about external side-effect idempotency |

Before implementation, perform repository-wide route, migration, notification, frontend navigation, import and open-PR inventory. Missing audited path is not proof of complete absence elsewhere. If an existing canonical user planner entity is found, update this ADR and reuse it.

## Threat model: adversarial acceptance cases

1. **Fake success:** model says “moved” but write fails; no success UI without durable receipt.
2. **Isolation:** same-tenant different-user and cross-tenant read/write/sync/approval must be blocked by SQL RLS and service auth.
3. **TOCTOU:** stale approved preview, another tab changed the week; apply with expected revision or return conflict and regenerate.
4. **Duplicate mutation:** client retries or model repeats; idempotency key, unique write receipt, exactly one logical change.
5. **DST and locale:** ambiguous “Friday”, nonexistent/overlapping local time, travel zone, floating/all-day times; explicit IANA zone and deterministic disambiguation.
6. **Recurrence:** occurrence-vs-series updates, exclusions, postponements, duplicate deliveries and missed jobs after restart.
7. **Provider drift:** disconnected Google/CalDAV calendar, 429, expired token, webhook replay; durable outbox, sync state, conflict surface, no false synchronized claim.
8. **Protected commitments:** “make Friday lighter” must not silently move meetings with others or immovable commitments; preview/approval and constraints.
9. **Completion semantics:** personal task completed by user never implies agent execution verified, or reverse.
10. **Privacy and usability:** secure reminders, deletion/export, quiet hours, no sensitive notes in telemetry; keyboard, mobile, screen reader and empty states.

## Architecture and records

Canonical PersonalPlannerService under runtime-governed services, with a scoped SQL repository and migrations. Use existing runtime, auth and audit dependencies. Proposed minimum personal task attributes: stable id, tenant_id, user_id, title, notes, status, priority, estimated_duration, due_at distinct from planned start/end, timezone, all_day/floating, hard_or_flexible, project/goal refs, dependency refs, recurrence spec and exceptions, optional automation_task_id, completion provenance, row revision, created/updated/deleted timestamps. Separate change-set proposal/approval record and planner revision, plus reminder occurrence and delivery receipts. Final exact files/schemas must follow owner inventory to avoid duplicate abstractions.

CORTEX classifies and gates. ChatRuntime normalizes and obtains authorized planner snapshot, requests a deterministic constraints-aware proposal, validates policy, applies operations atomically with revision/idempotency, issues immutable receipt, persists/projections and publishes refresh. Deep Agents only for complex multi-step conflict solving. NeuroRecall can inform preferences but does not own schedules. AG-UI and assistant-ui render pending/approved/applied/rejected/conflicted statuses from backend truth.

## Implementation gates

**P0 Ownership inventory & ADR:** map all candidate tables, routes, services, notification delivery, memory/goal stores, UI navigation, open PRs, permission models and licenses; agree canonical owner and event contracts. No blind rewrite.

**P1 Durable planner core:** personal task/plan CRUD, separate lifecycle, scoping, DB migrations with both tenant and user RLS, soft deletion and user data export, validated UTC+IANA time, optimistic concurrency, idempotent writes, audit and receipts, typed API. Test concurrent and restart paths.

**P2 User workspace:** Today, Week, Calendar, Goals, History with progressive-disclosure controls, direct manipulation and accessible list equivalents; accurate loading/offline/conflict/empty states; manual create/edit/complete/undo. Never use fictitious tasks in production UI.

**P3 Conversational edits:** versioned planning intents, read-snapshot and propose-before-apply contract, before/after diff, hard/flexible constraints, explicit approval for impactful changes, optimistic revision match, receipt, UI refresh. Simple operations must not invoke graph workflows.

**P4 Recurrence and reminders:** recurring series/occurrence exceptions, time zones, quiet hours, durable worker and outbox, retries/dead letters/dedup, cancellation semantics, delivered/failed receipts. Reuse scheduler/queue implementation without coupling personal task state to automation execution status.

**P5 Optional external calendars:** permissioned connectors/CalDAV sync adapters with consent, per-calendar scope, ETag/provider event refs, webhook validation, outbox/inbox reconciliation and offline-first fallback. Distinguish local-saved, sync-pending and remotely-confirmed.

**P6 Adaptive recommendations:** recommendation-only learning with transparent preference sources, privacy opt-outs, feedback, baseline comparison, time-estimation error and override metrics. Never silently override protected blocks.

## Mandatory proof

- `python -m compileall src`, `pytest tests/ -q`, `ruff check src tests`, `mypy src`; frontend lint/typecheck/test/build using scripts actually present; `docker compose config`.
- Disposable PostgreSQL migration upgrade/rollback; tenant and same-tenant-user negative tests, authorization denial and user-deletion tests.
- CAS stale-approval, idempotent retry, concurrent writes, external side-effect compensation and worker restart; no false success.
- Timezone/DST fold/gap/leap, recurrence exceptions, quiet hours, deduplicated notification retry.
- End-to-end test: “move unfinished from yesterday, keep gym, make Friday lighter” -> reviewable preview -> approval -> durable data -> reload -> receipts -> undo.
- Provider failure, offline, token revocation, out-of-order webhook replay and reconciliation.
- Accessibility keyboard/screenreader, small screens, high zoom, locale formatting.
- Structured telemetry: correlation/request, tenant/user IDs, policy decision, change-set ID, planner revision, idempotency key, operation and delivery receipt, latencies, error codes; redact task content and tokens.
- No claim of deployment, tests green or consumer readiness until verified. No package/release build needed before human verification.

## Integration and rollout

Super Productivity may guide UX; evaluate license compatibility before copying code. Vikunja is not automatically selected as a second backend. Feature-flag planner workspace; add migrations and versioned contracts before UI; retain existing automation task endpoints and behavior. A phased PR must not merge until its exact-head tests and relevant human UX checks are green. Report risks and blocked gates precisely.


## ADR-001: first-class core domain with governed extensions

**Status:** Accepted architecture direction for implementation planning; delivery remains gated on P0 repository-wide ownership reconciliation.

**Decision:** Karen Personal Planner is a built-in, modular, local-first product domain, comparable to Chat, Memory and Personalization. Its lifecycle and canonical storage remain usable without installed plugins, external calendars, hosted model providers, or agent-graph execution. The user-facing planner is never implemented as a standalone plugin or as a second imported application backend.

| Responsibility | Canonical owner | Non-owners / boundary |
|---|---|---|
| Tasks, planned time blocks, appointments, completion, priorities and plan history | Core PersonalPlannerService with scoped repository | Agent automation tasks, chat transcript and frontend state |
| Goals | Existing canonical personalization/goals authority, linked by stable reference | Planner must not duplicate or fork goal storage |
| Time recurrence, reminder intentions and delivery receipts | Planner domain + existing durable scheduler/queue/outbox authority | Cron administration UI and automation execution status |
| Intent/policy/eligibility | CORTEX policy contracts | CORTEX never directly writes planner entities |
| Identity, authorization, snapshot, approval, mutation and receipts | Karen runtime + canonical planner service | Tools, plugin adapters, UI and external providers never bypass |
| Complex conflict-solving proposals | Deep Agents only when multi-step planning is actually needed | No graph required for simple CRUD, reminders or completion |
| Preferences and adaptation | Existing Memory/NeuroRecall/Learning authorities | Planner may consume but must not create competing memory store |
| Today / Week / Calendar / Goals / History | Core Karen UI using versioned backend contracts | No speculative success toast or browser-only planner fallback |
| Calendar/email/third-party systems | Permissioned optional plugin adapters | Adapters do not own personal planner data or user authorizations |
| Chat, WhatsApp, voice and other channels | Authorized channel ingress -> common runtime planner tools | No channel-specific planner databases or permission bypass |

### Core and extension contract

- Core planner must support manual creation, editing, scheduling, completion, postponement, cancellation, proposals, approvals, undo, reminders and recurrence with extensions disabled.
- Publish versioned, typed planner read and mutation operations. Extensions may propose normalized task/event changes or report external states, but must invoke the same scoped service and approval policy.
- Each plugin manifest must declare capabilities, permissions, provenance, input/output schema, supported provider actions, and scoped consent. Validate manifest, tenant, user, token scope and RBAC at each call.
- Inbound suggestions (e.g. email follow-up or imported appointment) are **candidates**, never silently canonical tasks. Deduplicate by scoped source/provider reference and content fingerprint, and require policy-appropriate user authorization to commit.
- Outbound calendar sync is a separate side effect: preserve local source of truth, durable outbox, idempotency and provider receipts. Expose `local_saved`, `sync_pending`, `synced`, `sync_conflict` and `sync_failed` truthfully. Do not conflate local commit with remote success.
- Define bidirectional sync policy per connected calendar, including owner, provider ETag/revision, deletion propagation, stale-webhook rejection, and resolution for external changes before enabling writable sync.
- An automation execution may link to a personal task, but its `success`/`failed` state must not mark the human task `completed`. Completion requires its own authorized evidence.
- Accessible direct UI editing and natural-language chat both use one mutation path; the user can inspect, reverse when permitted, and audit committed edits from any authorized channel.
- Reuse existing scheduler, goal, auth, observability and UI infrastructure. Do not vendor Super Productivity or Vikunja as a competing backend. Study third-party UX independently of importing code or incompatible licenses.

### Additional adversarial gates

1. **Plugin absent/offline:** user can still open Today, edit tasks and see authoritative local planner history. Existing reminders are not gated on a calendar connector.
2. **Email prompt injection:** untrusted email text cannot cause unauthorized task creation, appointments, plugin installation or cross-account reads; user-visible suggestion is provenance-linked.
3. **Provider partial failure:** local save succeeds but remote update fails; UI shows pending/failed synchronization, never a globally successful claim. Retries do not create duplicates.
4. **Channel parity:** the same task requested in chat, workspace or WhatsApp observes identical user/tenant scoping, approval requirements, revisions and receipts.
5. **Shared goal authority:** planner links existing goal IDs; editing a goal cannot fork state or bypass the goals service.
6. **Revocation and export:** disconnecting integrations invalidates provider access and pending sync work without erasing the user's canonical local task data; export/deletion follows privacy authorization.

### Delivery order and proof

Treat P0 as a hard gate: enumerate all existing planner-like records, service owners, scheduler implementations, extension manifests, integration branches and open PRs. Amend this ADR if an existing canonical planner owner is found. Then implement P1 core persistence/API without requiring plugins; P2 core workspace with real data; P3 runtime-mediated conversational proposals and commits; P4 reminder/recurrence behavior; P5 optional provider adapters; P6 independently benchmarked adaptive planning.

Do not merge based solely on documentation review: each production slice requires exact-head CI, tenant/user isolation tests, conflict/idempotency tests, truthful receipt and synchronization tests, and human UX acceptance appropriate to the slice.


## P0 ownership reconciliation: verified source findings (2026-10-19)

**Verification method:** Direct GitHub default-branch file reads for the paths below. GitHub repository-wide code search returned no file matches for planner, reminder, calendar, notification, goal or scheduler terms. Therefore this is a **partial owner reconciliation**, not a claim that no competing module exists. Do not advance the P0 gate until tree/reference and open-PR inventory succeeds.

| Source verified | Observed behavior | Owner decision / follow-up |
|---|---|---|
| `src/ai_karen_engine/api_routes/automation/tasks.py` | `/api/tasks` accepts agent assignments, instructions, acceptance criteria, verification contracts and execution review state. Delegates to automation definition/execution services. | **Keep in automation**. Do not repurpose route, records or `Pending/Running/Success/Failed` status as human plans. |
| `src/ui_launchers/Karen-AI-Theme/src/components/automation/TasksPage.tsx` | Reads `/api/tasks/` and agent catalog; agent task/result/review UI. | Keep automation UI distinct from the new personal Today/Week experience. |
| `src/ai_karen_engine/api_routes/automation/cron.py` | Uses automation repository claim leases and durable queue, job type and execution-target dispatch. | **Reuse infrastructure patterns/queue authority** for reminders, with a distinct queue job contract and delivery receipts; don't execute a personal task as an agent job. |
| `supabase/migrations/20260923010000_16_automation_scheduler_authority.sql` | Defines agent automation tasks, jobs, cron and queue; task status only `Pending/Running/Success/Failed`; automation task RLS checks tenant context, not personal task owner. | **New personal planner table/policy required unless another canonical schema is found**. Enforce tenant AND user identity and independently test same-tenant isolation. |
| `src/ai_karen_engine/api_routes/automation/scheduler.py` | Autonomous training scheduler routes use `bypass_user_context_func` as a dependency including role checks. | **P0 security review**: establish whether the bypass can be reached in production and prove RBAC before reusing any path. No personal-planner calls may depend on bypass auth. |
| `src/ai_karen_engine/core/personalization/runtime.py` | Reads repository-owned preferences/behaviors/goals and derives user snapshots, without claiming second durable goal authority. | Planner consumes scoped projections and links canonical goals; no new independent goals storage. |
| `src/ai_karen_engine/core/personalization/goals/contracts.py` | Defines semantic goal lifecycle/contracts. | Reuse validated stable goal IDs via existing repository; verify actual goal write owner and migrations in full P0. |

### Open-PR overlap check (partial)

A scoped open-PR search for `planner`, `calendar`, `reminder`, `notification`, `scheduler`, and `goals` returned PR #499 for the first three matching terms and `scheduler`, with no matches for the others. This is **not** a full review of all active branches or PR file lists. Before P1, enumerate every open PR and compare file overlap with backend services, schemas, app navigation, AG-UI, notifications and goals.

### P0 blocker checklist before P1

- Enumerate default-branch tree and all migrations for potential canonical personal planning tables.
- Trace scheduler queue consumers, notification delivery providers, job retries and their dependency injection and secrets boundaries.
- Trace canonical goal writes/IDs from API through repository to database; confirm ownership and tenant-user scoping.
- Inventory router registration, memory/CORTEX runtime tool contract, frontend navigation, UX components and overlapping PR branches.
- Confirm safe authenticated service/worker context, row-security posture, and audit-event ownership.
- Record exact reuse sites and test locations. Only then select new schema identifiers and implement P1.

**Status:** source-grounded partial audit recorded; P0 remains open. No runtime security claim, no tests executed, no production code changed.
