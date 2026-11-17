# KCHAT-BUDGET-02: Shared quota for fallback model-engine attempts

**Date:** 2026-11-16  
**Source candidate:** `fix/expression-fallback-engine-quota-20261116`  
**Canonical authorities:** RuntimePolicy / `ExecutionBudgetMeter` for admission;
`ChatRuntime` for first-call reservation;
`ExpressionGateway` for actual engine attempt ordering and fallback.

## Confirmed defect

Before this patch, ChatRuntime charged `consume_model_call()` once per
ExpressionGateway generation. That gateway may invoke multiple enabled engines
in sequence when the first provider fails or delivers an unverified response.
The second and later invocations were not charged against the original
RuntimePolicy model-call budget. This could exceed the authorized model-call
quota without a new user decision.

## Minimal canonical correction

The server-owned `ExpressionTask` exposes a non-serializable, trusted
`reserve_additional_model_call` coroutine. ChatRuntime binds this to the
**same** `meter.consume_model_call` already used for the initial reservation.
The binding is set at all current ChatRuntime ExpressionTask construction
points:

1. Direct chat, including the shared streaming producer and reasoning synthesis
   when it follows `_run_simple`.
2. Grounded search and direct-capability observation synthesis.
3. Verified compositional surface-layout planning.

ExpressionGateway counts only configured, enabled, non-circuit-blocked engines
actually selected for invocation. Before a second or later invocation, it
requires a literal `True` admission receipt from the original meter.

When the budget is exhausted, the gateway emits a bounded rejection event and
raises `EngineUnavailableError("execution_budget_exhausted_max_model_calls")`
**before calling** the next engine. A guard exception also fails closed.
Previously emitted streamed text remains non-switchable. No static answer,
fresh authorization plan, independent meter, backend override, UI approval, or
unauthorized provider selection is introduced.

Skipped disabled/circuit-open entries do not consume model calls. The first
Runtime reservation remains in place, preserving all existing first-call
fail-closed semantics and the existing tests that verify rejection before
initial execution.

## Tests

- `tests/core/expression/test_gateway_additional_engine_budget.py`:
  initial + fallback succeeds with two available calls; a one-call plan denies
  the fallback **before invocation**; disabled engines do not consume calls;
  invalid callback receipts and exceptions fail closed; incomplete stream
  cannot change models or add a call; one successful engine needs one call.
- `tests/core/runtime/test_chat_generation_budget.py`:
  direct and grounded-search tasks carry the original meter.
- `tests/core/runtime/test_ksi_surface_planning.py`:
  surface-planning task binds the original metered callback.
- `.github/workflows/chat-system-burn.yml` executes all of the above.

## Scope and residual risk

The guard meters **actual ExpressionGateway engine invocations**, not every
low-level HTTP retry inside a provider client or nested agent SDK. Those
separate mechanisms must be reconciled with Runtime observability and
provider-specific retry contracts before claiming exact wire-attempt, token
or invoice accounting. This change does not alter the `ExpressionGateway`
fallback sequence or the provider registry. Tenant/user/session authority
remains with the Runtime's existing plan and meter.

**Release gate:** exact-head compile, quality, chat burn, authenticated
PostgreSQL, Medusa, Ollama and production first-boot workflows. No production
readiness claim solely from isolated test doubles.

## KCHAT-TRUST-01: Inline fetched-page synthesis admission

During the new grounded-synthesis test burn, a separate response-integrity
issue was found. The previous ChatRuntime synthesis path used plan-approved
plugin identity to gate *stored article_id* retrieval, but an inline
`fetched_page` excerpt could enter its model prompt without independently
verifying the source was a completed tool/plugin execution eligible under
`AuthorizedExecutionPlan`.

ChatRuntime now verifies the identical evidence admission contract for every
fetched-page source, inline or stored:

- `success is True` and `degraded is False`.
- Source is a registered `tool` or `plugin` with a source ID present in
  that execution's `allowed_tools` or `allowed_plugins` respectively.
- An actual attempt receipt must match source type and ID and report
  `status == "success"`.
- Invalid, missing, failed, degraded or foreign receipts return without
  constructing a model prompt or reserving another model call.
- Tenant-scoped stored-artifact lookup remains additionally mandatory for
  `article_id` references.

Tests in `test_chat_generation_budget.py` cover untrusted inline
excerpts, malformed booleans, wrong source type, unapproved IDs, failed
attempts and a valid separately admitted tool. RuntimePolicy and the
DirectCapabilityExecutor still own authorization and execution; the
synthesis gate only verifies their receipts before making content model-visible.

## KCHAT-POLICY-03: Prevent external engine opt-out bypass

The gateway previously treated an enabled `cloud` engine as executable
even when its independent `allow_external_engines` policy was false. This
could occur with an explicitly selected remote provider, an active cloud
engine, or a configured fallback engine. Provider-selection policy checks
were insufficient because the gateway also directly appended the active
engine and fallback order, regardless of the policy decision.

The canonical `ExpressionGateway` now denies an eligible-looking cloud
engine **before engine instantiation, fallback-budget reservation, or
network execution** if external execution is disabled. It emits a bounded
`external_engines_forbidden` rejection receipt. A disabled engine does
not consume an additional model call. Configured local providers may
continue only under their existing independent engine and RuntimePolicy
admission rules.

Adversarial test cases cover an enabled cloud engine selected explicitly
and the same cloud endpoint inserted in the fallback chain, verifying
zero cloud-engine invocation and correct shared budget accounting. Tests
which intentionally exercise authorized cloud fallback now explicitly
enable the external-engine policy rather than relying on implicit
configuration. No user request or persisted UI preference can override
the installation-level external-execution policy.
