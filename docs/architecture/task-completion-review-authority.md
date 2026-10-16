# MI-09: evidence-aware human completion review

## Scope and authority

This is Step 3B's first accountability slice. A model response is an *execution
observation*, not a verified business outcome. No additional orchestrator, agent,
approval registry, task store, or provider selector is introduced.

- **Task definition, latest execution, and human review transition:** canonical
  `SqlAutomationRepository` over `public.automation_tasks`.
- **Execution lifecycle and reviewer authorization:** existing
  `services/automation/execution.py`.
- **Model, tools, plugins, policies:** existing CORTEX, ChatRuntime, Medusa.
- **Pre-execution approvals:** existing `ApprovalService`; not reused for
  post-execution verification because the two decisions are different.
- **Evidence provenance:** runtime-confirmed identifiers, status, summary of
  sources/artifacts, and a preview of the returned answer. Counts and previews
  are observations, *never independent evidence that the objective was met*.
- **User accountability:** the authenticated task creator decides whether
  their previously defined acceptance criteria have been satisfied.

## Durable states

`Pending` -> `Running` -> `ReviewRequired` -> `Success` or `Rejected`.
Execution errors use `Failed`, preserving real error information.
The 2026-10-16 migration reclassifies old, unreviewed `Success` records as
`LegacyUnverified` rather than laundering them into verified completions.

`Success` now requires persisted `execution_id`, `reviewed_by`, and
`reviewed_at`, enforced by the database CHECK. Historical records retain their
original last-run metadata but cannot be retrospectively approved without a
new execution and real review.

A pending `ReviewRequired` attempt blocks new worker claims, including cron
re-execution. The owner must accept or reject it first, so a scheduled run
cannot overwrite the evidence awaiting review.

Only the authenticated creator, in the correct tenant, may approve or reject.
Every review must match the **current** execution UUID and `ReviewRequired`
state; a compare-and-swap SQL UPDATE prevents double approvals, stale browser
tabs, and approval of a newer run using an old receipt. The current working
lease token is never exposed through task reads.

## API and UI

- `POST /api/tasks/{id}/execute`: returns `ReviewRequired` when the model
  produced an answer. Never returns goal `Success` from ChatRuntime output.
- `POST /api/tasks/{id}/review`: `{execution_id,decision,note}`,
  with decision `approve` or `reject`. 403 for nonowners, 404 for missing
  tenant-scoped tasks, 409 for stale/already-reviewed attempt IDs.
- `GET /api/tasks/` and `GET /api/tasks/{id}`: includes
  `executionId`, `resultReceipt`, `reviewedAt`, `reviewedBy`,
  `reviewNote`, `acceptanceCriteria`, alongside existing task fields.
- Tasks UI displays the unverified result preview, source/artifact counts,
  the requested acceptance criteria, and actual backend review actions.

The task record includes the reviewer-accessible full answer up to the
centrally configured `KARI_TASK_REVIEW_MAX_ANSWER_CHARS` limit (default
65,536 characters, validated 2,400..262,144). The first 2,400 characters
are also retained as a preview. Source metadata includes bounded, safe
HTTP(S) URLs and titles but does **not** independently certify them.

A pending result **cannot be approved** if the full answer was truncated,
if attachment/artifact contents are not accessible through this surface, or if
its source list is incomplete. This rule is enforced in both the
authenticated service and the atomic SQL review update; the frontend does
not own the guard. A reviewer can reject and rerun with an accessible
deliverable. This resolves the cron-vs-task-creator conversation-ownership
problem for complete text outputs without pretending that artifact counts
are proof. Even after human approval, the receipt keeps
`independently_verified: false`, because it records a human attestation,
not independent automated external validation.

## Schema/deployment

Apply `supabase/migrations/20261016020000_29_saved_task_completion_review.sql`
**after** MI-08 migration 28 and **before** deploying worker/API/UI. Cut over
all binaries together. Old workers can write historical `Success` without a
reviewer and will violate the new database CHECK, which is intentional failure
rather than fabricated success.

This change retains existing tenant RLS. Review is owner-only even for other
users within the same tenant. No secrets are logged in the structured review
event. No provider selection, plugin execution, or fallbacks occur in routes.

## Proof

- `pytest tests/services/automation/test_task_verification.py -q`
- `pytest tests/services/automation/test_execution.py -q`
- `pytest tests/api/test_task_definition_routes.py -q`
- `pytest tests/services/automation/test_task_claim_ownership.py -q`
- Isolated PostgreSQL: `pytest tests/integration/test_live_automation_task_claims.py -q`
- `python -m compileall -q src`; Main Quality, Automation Authority,
  live Postgres, frontend build/type-check, production auth checks.

## Deliberate constraints / subsequent phase

This release stores latest task attempt and review truth, not a new append-only
run history table. ChatRuntime outcome records and existing auditing remain
separate evidence sources; the latest review has durable reviewer/time/decision
on the canonical task row. A retry resets the latest receipt, so historical
user-level verification events must be linked to the existing outcome/audit
authority in a follow-up instead of inventing a second event registry here.

Goal ancestry linking and machine-checkable acceptance verification still
require canonical goal ownership and trusted tool-execution receipts. Neither
model self-certification nor arbitrary user-submitted artifact URLs are trusted
as machine-verifiable proof.
