# MI-10: Atomic task review events and creator-scoped history

## Purpose and owners

Step 3C closes the gap between Karen's latest saved-task state and durable
review history. It does not introduce another task store, agent scheduler, or
orchestration layer.

- `SqlAutomationRepository.review_task` owns the task compare-and-swap and
  remains the **sole** authority to transition to `Success` or `Rejected`.
- `PostgresOutcomeStore` owns append-only evidence in the existing
  `public.outcome_records` table (migration 20).
- The task repository invokes the existing outcome insert statement with
  **the same SQLAlchemy async session** as the review UPDATE; there is no
  separate write or eventual success receipt.
- `services/automation/execution.py` revalidates the authenticated creator,
  and the history API exposes an owner-only read model.
- ChatRuntime, CORTEX, Medusa, pre-execution ApprovalService, scheduled
  principals and tenant RLS retain their existing owners.

## Transaction and idempotence

1. The reviewer supplies the exact execution UUID. SQL UPDATE verifies task,
   tenant UUID, authenticated `created_by`, `ReviewRequired`, matching
   `execution_id`, and the MI-09 reviewer-accessible evidence guard.
2. If no row updates, no history event is attempted. A double review or stale
   attempt remains a 409. Cross-tenant or noncreator access is hidden.
3. For a successful compare-and-swap, the same transaction appends one
   `user.feedback` outcome with `feedback_type =
   task_completion_confirmation`.
4. Its deterministic `out_task_review_<execution_uuid>` key refuses
   duplicates. The canonical outcome insert uses `ON CONFLICT DO NOTHING`;
   `append_in_transaction` verifies exactly one row inserted and otherwise
   raises. Both tables roll back on duplicate IDs or any persistence error.
5. The event contains the reviewer, decision, timestamp, original
   acceptance criteria, correlation ID, note, SHA-256 of the canonical JSON
   receipt and the bounded **original complete reviewer-visible receipt**.
   The receipt is a human attestation and remains
   `independently_verified: false`. Model output is not evidence that real
   work happened.
6. When a future run updates the saved task's latest-result fields, the prior
   outcome event remains intact. Rejected reviews persist as well.

No additional schema migration is needed: the canonical table already has
`trajectory_id`, `source`, `user_id`, `tenant_id`, `payload`, and the
tenant/trajectory index.

## Retrieval and UI

The new `GET /api/tasks/{task_id}/reviews?limit=50` endpoint validates
`get_current_user`. The service requires a creator-owned task through
`SqlAutomationRepository.get_task(..., created_by=user_id)`, then calls
`OutcomeStore.list_task_reviews_async`. The PostgreSQL query additionally
filters tenant, user, exact task trajectory, `user.feedback` source, task ID,
and feedback type, and limits results to 1..100. Cross-user, cross-tenant, or
deleted task reads cannot retrieve evidence through this API. If evidence
persistence is unavailable, the API returns 503, not an invented empty history.

The task UI has a per-task History action that retrieves the real reviews and
shows prior decisions, criteria, reviewer notes, original captured answer,
attempt IDs and receipt digests. Backend truth determines availability.

## Privacy and security

Human notes and model answers may be personal. Each outcome is tied to the
same authenticated task creator. The existing `outcome_records` tenant RLS
and user-deletion cascade still apply. Never log the full receipt, note, or
answer. Outcome events include a full bounded result snapshot because a
checksum alone cannot let the creator inspect previously reviewed work.
Do not expose raw event payloads through tenant-wide listings.

## Proof

- `tests/services/automation/test_task_review_history.py`: same-tenant user
  isolation, tenant isolation, event type filtering, deterministic duplicate,
  outage and API response.
- `tests/integration/test_live_automation_task_claims.py`: actual PostgreSQL
  concurrent task claims, rollback of review status on evidence insert
  failure, no history for invalid reviews, duplicate review guard, legitimate
  approval, rerun and rejection with both historical snapshots preserved.
- `tests/services/automation/test_task_verification.py`: existing MI-09
  authorization and evidence sufficiency behavior.
- `Automation Authority Gate`, `profile-memory-postgres`,
  `Main Quality Gate`, `Chat System Burn` and security checks.

## Remaining limitations

This is review-event history, not a complete per-step agent action ledger.
Unreviewed failed attempts, tool side effects, credential access, and
machine-verifiable external acceptance checks must reuse existing outcome,
audit, Medusa and RBAC authorities as the next distinct phase, not spawn new
registries. Task deletion hides review history from the task API; user erasure
follows existing outcome foreign-key cascade. Existing MI-09 deployment
migration must be applied before this application version is deployed.
