# KCHAT-BUDGET-01: Runtime execution-budget integrity audit

**Date:** 2026-11-16  
**Canonical owner:** `src/ai_karen_engine/core/runtime/contracts.py::ExecutionBudgetMeter`  
**Scope:** one existing budget meter, no second policy, router, retry engine, provider, store or UI authority.

## Confirmed pre-fix defects

1. The meter used `time.time()` to measure runtime deadlines. A system-clock
   correction can extend or prematurely expire a request despite unchanged
   monotonic elapsed time.
2. A repeated `start()` call reset the request deadline. A caller could
   inadvertently extend an already authorized execution window.
3. Every rejected reservation incremented its counter *before* rejecting.
   A ceiling of three model calls could be reported as four, even when the
   fourth call was refused. This also distorted reasoning/tool/token usage.
4. Token accounting accepted negative values. For example, adding `-100`
   reduced consumed tokens and could permit calls beyond the authorization.
5. Reservations did not independently enforce the duration deadline, so a
   caller omitting `check_duration()` between steps could continue reserving
   budget after the request timeout.

## Fix in the existing owner

Use `time.monotonic()` for one idempotently started request deadline.
All model, reasoning, tool, agent, network and input/output token reservations
go through one lock-protected `_reserve()` function. It validates nonnegative
integer quantities and limits; checks the same deadline; and increments a
counter **only after successful admission**. Denial is terminal for that
execution meter, without inventing usage for calls that never ran.

This preserves the RuntimePolicy-authorized `ExecutionBudget` object and
works with the previously merged KCHAT-INT-02 requirement that runtime
fallback reuse the exact original plan and meter. No new fallback or
unmetered execution path is introduced.

## Adversarial acceptance

`tests/core/runtime/test_execution_budget_meter_integrity.py` exercises:

- Deadline expiry despite an attempted repeated `start()`.
- Rejection of reservations after the deadline even without explicit
  `check_duration()` calls.
- Exactly three of 32 concurrent reservations admitted against a quota of
  three, with no counter overrun.
- Accurate non-inflated model, reasoning, tool, agent and network counters.
- Accurate token counts after failed reservations.
- Rejecting negative, Boolean, fractional, string and null token
  adjustments without modifying usage or authorization.
- Zero model quota and invalid configuration limits.
- An execution whose first recorded operation starts the deadline.

The canonical Chat System Burn workflow runs this suite in addition to the
existing model-authenticity and recovery-authorization regressions.

## Remaining release risks

The meter counts **admitted Runtime execution operations**. A single
`ExpressionGateway.generate` may consult more than one provider endpoint
inside its eligible fallback chain; this meter alone does not prove
one-to-one accounting for every underlying network attempt. Provider
attempt spans and telemetry must be separately reconciled before claiming
network-level quota enforcement or exact billing. Live model latency, CPU,
memory, cancellation and provider-specific metering remain empirical
acceptance requirements.

**Required proof:** exact-head Chat System Burn and Main Quality, first-boot,
model/provider, memory replay and security checks; no production readiness
claim from unit tests alone.
