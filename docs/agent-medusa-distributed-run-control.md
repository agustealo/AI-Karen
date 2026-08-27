# Agent Medusa Distributed Run Control

Agent Medusa execution tasks remain owned by the runtime worker that created the concrete `asyncio.Task`. KAREN uses the canonical Redis connection manager only for shared run metadata, ownership leases, cluster observation, and remote cancellation requests.

Redis is not a durable execution ledger. PostgreSQL remains the durable system of record where durable execution history is required. Redis coordination may disappear after its retention window without changing model, memory, prompt, provider, plugin, or policy authority.

## Runtime settings

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `KAREN_MEDUSA_DISTRIBUTED_RUN_CONTROL_ENABLED` | `true` | Enables shared run coordination when canonical Redis is healthy. |
| `KAREN_MEDUSA_RUN_LEASE_TTL_SECONDS` | `30` | Ownership claim/lease duration. Minimum 3 seconds. |
| `KAREN_MEDUSA_RUN_HEARTBEAT_INTERVAL_SECONDS` | `10` | Owner heartbeat and remote-cancel polling interval. Must be less than the lease TTL. |
| `KAREN_MEDUSA_RUN_TERMINAL_RETENTION_SECONDS` | `3600` | Redis retention for terminal and orphan-observation metadata. Must be at least the lease TTL. |
| `KAREN_MEDUSA_RUN_KEY_PREFIX` | `kari:medusa:runs` | Namespace for shared coordination keys. |
| `KAREN_WORKER_ID` | `<hostname>:<pid>` | Runtime-worker identity used for lease ownership. Set explicitly in orchestrated deployments. |

All options are loaded and validated by `ai_karen_engine.config.agent_medusa`.

## Failure semantics

If Redis is unavailable or in degraded mode, the worker continues to own and cancel its local concrete tasks. KAREN does not use the Redis connection manager's in-memory fallback for cluster authority. Cross-worker visibility and cancellation are reported unavailable rather than fabricated.

An active shared run whose lease expires is projected as `orphaned`. Orphaned runs are not cancellable because no live owner has proven it can enforce cancellation. Repeated cancellation requests are rejected after a run reaches `cancelling` or any terminal state.

## Security boundary

Tenant scope comes from authenticated runtime/API context, never from browser-selected ownership. Admin run reads require the existing runtime-read permission and cancellation requires runtime-manage. Worker IDs and Redis keys are infrastructure details and are not required by the frontend contract.

## Scaling contract

A worker atomically claims a run with Redis `SET NX EX`, writes sanitized shared metadata, and renews the claim on heartbeat. A remote cancellation request marks the shared run `cancelling`; the owning worker observes the request during heartbeat and cancels its actual local task. Terminal completion releases the ownership claim and retains only bounded coordination metadata.
