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
