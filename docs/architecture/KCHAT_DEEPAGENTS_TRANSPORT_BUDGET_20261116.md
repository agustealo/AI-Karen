# KCHAT-BUDGET-03: governed Deep Agents transport admission and shared budget

**Date:** 2026-11-16  
**Dependency:** KCHAT-AUTH-04, merged as PR #965.  
**State:** SOURCE_CANDIDATE; no live model execution or exact-head acceptance is implied by this text.

## Existing owners and observed gap

- `ChatRuntime` receives the authenticated `ChatExecutionContext`, an exact tenant/user/session-bound RuntimePolicy plan, and one monotonic `ExecutionBudgetMeter`.
- `WorkflowRuntime` delegates true multi-agent workflows only, using canonical Medusa. Previously, it did not pass ChatRuntime's actual budget meter to Medusa.
- `MedusaCoordinator` reconstructed a fresh meter from the same numeric limits, restarting the time window and losing earlier model reservations.
- `DeepAgentsResearchSpecialist` charged `consume_model_call` from `on_chat_model_start`. SDK callback timing was not a transport authorization contract and could precharge a call that never happened or fail to charge a direct model invocation.
- `KarenGovernedChatModel._agenerate` called the canonical structured provider HTTP transport without an independent RuntimePolicy/budget admission check. Its endpoint can be custom and remote even if registered as `LOCAL_ENDPOINT`.

## Implementation contract

1. The existing `ExecutionBudgetMeter` owns `reserve_model_execution(external: bool)`: one event-loop-atomic commit of model plus external-request quota, always against the original monotonic deadline; rejection does not partially spend either quota. `remaining_duration_ms` projects that same deadline.
2. `ChatRuntime` passes its original in-process meter into `WorkflowRuntime` for both graph run and stream. `WorkflowRuntime` forwards it to Medusa using the typed host-only `RuntimeRequest.runtime_budget_meter` field, not the general-purpose `context` dictionary or a JSON projection. The field is excluded from `RuntimeRequest.to_dict()` and repr; the original authorized plan remains unchanged.
3. Medusa accepts a supplied shared meter only when an exact typed, active, verified authenticated principal and original policy plan match user, tenant, session, request, correlation and budget. Invalid supplied meters fail before planning. Standalone governed Medusa calls without a supplied meter keep a separately scoped internal meter.
4. The specialist carries the original authenticated principal only from that validated boundary; a quoted prompt, agent role list or task metadata cannot mint it.
5. Every actual `KarenGovernedChatModel._agenerate` invocation validates its in-process `GovernedToolModelAdmission`, even when called without SDK callbacks. It validates messages before reserving a call; then checks RuntimePolicy external authorization for the effective endpoint URL and atomically reserves the actual model attempt. Missing/foreign grant, revoked principal, external opt-out, exhausted model or external quota abort before any provider wire request.
6. `bind_tools` retains the same host-only admission object in LangChain model copies and nested subagents. `on_chat_model_start` may observe start/deadline, but does not charge quotas; no duplicate accounting.
7. Medusa waves and the Deep Agents SDK timeout use `remaining_duration_ms` from the original meter rather than a renewed child deadline.

## Focused proof owners

- `tests/core/runtime/test_execution_budget_meter_integrity.py`: atomic model/external quotas, concurrent reservations, invalid values, original monotonic deadline.
- `tests/core/model_runtime/test_structured_tool_transport_admission.py`: direct invocation with omitted callbacks, missing/mismatched grant, bind_tools clones, parallel nested calls, remote URL/override, spoofed roles, explicit non-admin policy, revoked principal, external opt-out, quota exhaustion.
- `tests/agent_medusa/test_deepagents_shared_budget_contract.py`: typed trusted-context validation and fail-before-planning for forged meters.
- `tests/core/runtime/test_deepagents_primary_routing.py`: run and stream hand off the **same** meter without adding phantom usage.
- `tests/agent_medusa/test_deepagents_research_harness.py`: SDK lifecycle callbacks do not double-charge.
- `.github/workflows/medusa-core-ci.yml`: existing real SDK compatibility job includes all new direct model and Medusa coverage. Chat System Burn already runs the modified canonical budget tests.

## Boundaries not yet certified

This is not proof of production readiness, charged-provider invoice reconciliation, DNS rebinding or socket-level destination guarantees, or budget admission for independent non-Medusa SDK/raw-transport callers. Legacy `ProviderRuntime._attempt_provider_with_retries` has a distinct retry loop whose active reachability must be separately proven before retirement or integration. Do not claim browser or actual licensed-model verification from mocked HTTP receipts.

**Release gate:** exact-head Main Quality, Chat Burn, Medusa SDK, Plugin Ecosystem, Ollama Live E2E, real PostgreSQL, first boot and all applicable security checks must pass before merge. Keep KCON-220, KCON-650, KCON-768, KCON-770 and KCON-902 unchecked until independent end-to-end proof.
