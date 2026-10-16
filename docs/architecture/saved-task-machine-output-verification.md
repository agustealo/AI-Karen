# MI-11: Governed machine checks for saved task structured output

## Why this is deliberately narrow

CORTEX/ChatRuntime output, web source counts, Medusa artifact references and
model statements are **not independently verified evidence that external
actions occurred**. Karen must never silently convert those signals into
business-goal success. This first Step 3D slice supports something machine
verification *can* safely prove today: whether the actual runtime
`ChatExecutionResult.structured_content` satisfies a creator-approved,
bounded, standard JSON Schema contract.

A passing check means `runtime_structured_content_only`, not external task
completion. Human review continues to own `Success`. A task without a
declared schema retains MI-09 human-review behavior.

## Canonical owners

- **Task definition and persistence:** existing `SqlAutomationRepository`
  and `public.automation_tasks`, adding one `verification_contract` JSONB
  column through migration 30. No parallel task or verifier registry.
- **Schema validation:** `core/runtime/task_output_verification.py`
  using the repository's existing production `jsonschema` dependency and
  Draft 2020-12. Only deterministic structure is examined, never textual
  self-certification, browser input at review time, remote URLs or tool calls.
- **Execution and verdict assembly:** existing
  `services/automation/execution.py` immediately after ChatRuntime returns,
  before the fenced `complete_task` update.
- **Task status:** existing `ReviewRequired`, then explicit human approve or
  reject via the atomic MI-10 review transaction.
- **History:** existing `PostgresOutcomeStore` captures the complete bounded
  machine-verdict snapshot inside each reviewed task event. No new outcome
  category/table.
- **HTTP/UI:** thin definition model, schema editor, backend-driven verdict
  display and disabled approve action for schema failures.
- **Prompt-first:** version `task-definition.v2` communicates the optional
  schema to ChatRuntime. It does not instruct the model to self-verify.

## Versioned contract

`verificationContract` is optional. When set, it is exactly:

```json
{
  "version": "structured-output.v1",
  "schema": {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "additionalProperties": false
  }
}
```

Supported keywords are a safe bounded subset of Draft 2020-12. Remote
`$ref`, local `$ref`, `pattern`, arbitrary formats and unrecognized
keywords are rejected at definition time. Schema size is at most 8 KiB,
complexity 256 schema nodes/depth 12, and runtime output at most 256 KiB.
No network is used for verification. A malformed schema returns HTTP 400,
not an executed task or a fabricated verification pass.

`machine_verification` in `resultReceipt` has
`passed|failed|not_configured`, a stable reason, contract and output hashes
when applicable, and `independently_verified=false` always. The actual
model output fields are not logged by the verifier. An unhealthy/degraded
runtime or missing structured payload cannot pass.

PostgreSQL enforces that a task with a declared verification contract
cannot be marked `Success` without `machine_verification.status=passed`.
The review SQL independently repeats the guard and requires the same
creator, tenant and current attempt, alongside the original evidence
availability checks. A passing schema **never auto-approves** a task.

## Tests and cutover

- `tests/services/automation/test_task_output_verification.py`: structured
  pass, type confusion (including boolean-as-integer), missing output,
  schema mismatch, degraded execution, malicious refs/patterns, large
  contracts, no automatic completion and SQL authority.
- `tests/integration/test_live_automation_task_claims.py`: migration 30
  applied on an isolated PostgreSQL schema; a claimed pass cannot bypass
  SQL when status failed; rejection and future reviewed successful run
  remain possible; history remains append-only.
- `tests/core/runtime/test_task_execution.py`: versioned prompt contract.
- Automation Authority, live PostgreSQL, Main Quality, frontend and security
  gates must pass on the exact head before merge.

Apply migration `20261016030000_30_saved_task_structured_output_verification.sql`
after MI-09's migration 29. Keep worker, API and UI binaries aligned.
Production deployment is not established by a GitHub merge.

## Remaining Step 3D scope

Real-world independent verification will require authoritative tool-execution
proofs from governed plugin/tool audit, not just model-supplied responses.
Each such proof must be bound to tenant, principal, attempt, action, tool
version, authorization decision and durable audit record, then checked against
registered acceptance requirements. Until that authority is wired,
`independently_verified` remains false and human attestation remains the
only overall completion decision. Do not invent confirmations.
