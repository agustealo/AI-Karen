# Agent System Audit and Burn Test — 2026-08-28

## Scope

This audit covers the canonical Agent Medusa execution path and its LangGraph boundary after the repository branch collapse to `main`.

Primary path reviewed:

`LangGraph medusa_node -> RuntimeRequest -> MedusaCoordinator -> CapabilityAwareMedusaPlanner -> specialist registry/factory -> MedusaRunManager -> Redis live coordination + PostgreSQL durable history`

The audit is intentionally authority-first. It checks whether each responsibility is owned once, whether identity and policy survive handoff, whether degraded paths are truthful, and whether CI proves the real execution boundary rather than adjacent helpers.

## Canonical ownership

- **RuntimePolicy/CORTEX** decides whether multi-agent execution is authorized and supplies the authorized execution plan.
- **LangGraph `medusa_node`** is an adapter only. It may transport authorized state into Medusa but must not invent policy, tenant identity, or routing authority.
- **MedusaCoordinator** coordinates a previously authorized multi-agent plan.
- **MedusaRunManager** owns concrete worker-local `asyncio.Task` lifecycle and cancellation.
- **Redis** owns live distributed lease and cancellation truth.
- **PostgreSQL durable run ledger** owns long-lived execution history only.
- **Registry/factory** owns specialist implementation discovery/resolution.

## Burn-test findings

### P0 — LangGraph boundary was incompatible with hardened tenant scope

`RuntimeRequest` correctly rejects missing tenant identity, but `agent_medusa_node.py` constructed `RuntimeRequest` without passing `tenant_id`. The node simultaneously created an `ExecutionContext` using a legacy `"default"` tenant fallback.

Impact: the LangGraph-to-Medusa path could fail before execution after the tenant-hardening cut, while unit tests around lower Medusa layers still passed.

Remediation applied:

- LangGraph state now requires explicit tenant identity.
- Request and correlation identity may fall back to each other, but never to synthetic `"unknown"` sentinels.
- `RuntimeRequest.request_id` now preserves the upstream request identity rather than generating a new UUID.
- `RuntimeRequest.tenant_id` now receives the validated explicit tenant.
- The compatibility context receives the same explicit tenant value.

### P0 — CI did not execute the Agent Medusa test suite

`medusa-core-ci.yml` watches Agent Medusa source changes, but its main pytest jobs execute `tests/core/runtime/**`; it does not execute `tests/agent_medusa/**`.

Impact: distributed cancellation, durable ledger, run-manager, tenant-consistency, and LangGraph boundary regressions could remain green in the nominal Medusa workflow.

Remediation applied:

A dedicated `.github/workflows/agent-system-burn.yml` now executes:

- compile checks for Medusa and core runtime;
- the LangGraph -> Medusa boundary tests;
- tenant/execution consistency tests;
- worker-local run-manager tests;
- Redis distributed authority tests;
- PostgreSQL durable-history tests;
- a static rejection guard for the known LangGraph `default` tenant fallback.

### P1 — Coordinator still contains defensive legacy tenant fallback expressions

`MedusaCoordinator.handle_request()` and specialist execution context construction currently use expressions equivalent to `request.tenant_id or "default"`.

The hardened `RuntimeRequest` means a valid request cannot normally reach these expressions without an explicit tenant, so this is not presently the active P0 break. It is still duplicated tenant authority and should be removed in the next tenant-scope cleanup so only the request contract owns validation.

Required follow-up proof: coordinator tests must demonstrate that tenant identity is transported unchanged from `RuntimeRequest` into run registration and every specialist execution context.

### P1 — Core `ExecutionContext` still defaults tenant scope to `"default"`

The generic runtime `ExecutionContext` dataclass retains `tenant_id: str = "default"`.

This is broader than Agent Medusa and may have compatibility consumers. It should not be changed blindly. A repository-wide caller audit is required first, followed by migration to explicit tenant scope and removal of the default from the canonical contract.

### P1 — Some existing CI behavioral proofs are structural demonstrations, not behavioral tests

The existing Medusa core workflow includes inline Python sections that instantiate mocks and print success without exercising the complete agent boundary. These checks are useful smoke indicators but must not be treated as proof of production behavior.

The new burn workflow intentionally uses pytest against real Medusa contracts and execution components instead.

## Security and authority checks

Current strengths retained:

- missing durable-ledger tenant identity fails closed;
- RuntimeRequest rejects missing tenant identity;
- RuntimePolicy authorization is required before Medusa planning;
- non-`multi_agent` policy decisions are rejected at the LangGraph Medusa boundary;
- Redis remains live execution coordination authority;
- PostgreSQL remains durable history authority;
- only the worker owning the concrete `asyncio.Task` cancels that task;
- durable reconciliation flows from Redis observation into PostgreSQL rather than treating stale PostgreSQL heartbeat as lease truth.

## Burn matrix

| Boundary | Failure injected / invariant | Expected result |
| --- | --- | --- |
| LangGraph -> Medusa | missing tenant | fail closed |
| LangGraph -> Medusa | missing request + correlation identity | fail closed |
| LangGraph -> Medusa | non-multi-agent policy | deny execution |
| LangGraph -> Medusa | valid scoped request | preserve request/tenant/policy identity |
| Medusa run manager | stale/wrong owner | reject task authority |
| Distributed store | remote cancel | owner worker receives cancellation signal |
| Durable ledger | missing tenant | fail closed |
| Durable ledger | invalid transition | fail closed |
| Redis -> PostgreSQL reconciliation | Redis unavailable | defer, do not fabricate orphan state |
| Redis -> PostgreSQL reconciliation | expired/missing ownership | reconcile eligible durable run to orphaned |

## Next hardening cut

1. Remove remaining `"default"` tenant fallback expressions from `MedusaCoordinator` after adding transport tests.
2. Audit all `ExecutionContext(...)` constructors repository-wide and migrate callers before removing the generic default tenant value.
3. Fold the new agent burn suite into the required `main` quality gate once its first run is proven stable.
4. Replace print-only Medusa workflow demonstrations with executable assertions or delete them when redundant.
5. Extend the burn suite through specialist tool/plugin adapters to prove `ActionExecutionGate` cannot be bypassed below Medusa planning.

## Proof commands

```bash
python -m compileall src/ai_karen_engine/agent_medusa src/ai_karen_engine/core/runtime
pytest tests/agent_medusa/test_langgraph_medusa_boundary.py -q
pytest tests/agent_medusa/test_execution_consistency.py tests/agent_medusa/test_run_manager.py tests/agent_medusa/test_distributed_run_authority.py -q
pytest tests/agent_medusa/test_durable_run_ledger.py -q
```

## Status

The agent system is materially stronger than the pre-audit state, but it is **not yet architecturally closed**. The P0 LangGraph boundary defect is repaired and now has executable regression coverage. Remaining tenant authority duplication in the coordinator and generic runtime context is explicitly tracked as P1 cleanup rather than silently accepted.
