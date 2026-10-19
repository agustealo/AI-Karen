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
