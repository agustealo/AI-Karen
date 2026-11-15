# 05. Runtime execution, hooks and public API boundaries

[Wiki index](README.md) · [Manifest reference](03-manifests-and-prompts.md)

**Status: Implemented core execution gate.** Not every legacy route or
compatibility wrapper is a recommended new extension surface.

## Admission sequence

~~~text
HTTP request / ChatRuntime authorized tool request
  -> validated actor, tenant, session and correlation
  -> CORTEX + RuntimePolicy choice
  -> AuthorizedExecutionPlan
  -> PluginKernel installed manifest and loaded capability
  -> extension enabled, version compatible, dependencies healthy
  -> execution_input_schema validation
  -> RBAC + permission validation + tenant scope
  -> ActionExecutionGate for relevant side effects
  -> capacity / timeout / cancellation safeguards
  -> handler call
  -> result schema, audit, provenance, telemetry
~~~

The canonical execution service is
[extensions/executor.py](../../src/ai_karen_engine/extensions/executor.py).
[extensions/contracts.py](../../src/ai_karen_engine/extensions/contracts.py)
defines typed request/context/result models.
[PluginKernel](../../src/ai_karen_engine/extensions/plugin_kernel.py)
projects catalog schemas and manages lifecycle concurrency.
[PluginService](../../src/ai_karen_engine/services/plugin_service.py)
provides the app-facing operations and tenant configuration readiness.

The handler receives only a bounded, validated action payload. Never accept
"tenant_id", "user_id", "role", "secret" or "provider" from arbitrary action
JSON as authority to change identity, privileges or the runtime's provider.

## Invocation and configuration schemas

The declared "execution_input_schema" is the only per-action field contract.
For configured plugins, missing invocation schema means an empty object.
The "config_schema" is **not** invocation data; it is a separate persistent
admin settings contract. A secret field cannot be requested as an ordinary
action parameter. Consult
[Settings and Credentials](06-settings-and-credentials.md).

The schema validator must run in the actual host execution path. Handler-side
defensive validation is an additional layer, never a replacement for it.

## Hook points

The current canonical manifest enumerates:

| Hook | When it can apply |
| --- | --- |
| pre_intent_detection | Before intent classification |
| pre_memory_retrieval | Before governed recall |
| post_memory_retrieval | After scoped recall |
| pre_llm_prompt | Before runtime-controlled prompt execution |
| post_llm_result | After model result |
| post_response | After response delivery |

Declaring a hook does not automatically grant permission to mutate prompts,
memory or responses. For new plugins, request only the hooks that have a real
governed use case, require typed hook payloads, and make mutating effects
auditable. Most task plugins should not need any global hook.

## Backend handler lifecycle

The host base class exposes "initialize()", "shutdown()" and
"execute_hook()" as abstract operations; a typical plugin also exposes
"run(params)" for explicit actions. The loader resolves the declared
"entrypoint" to a reviewed Python class. The full deterministic
[Quickstart](02-quickstart.md) provides all three files.

Use async-safe operations, bound native CPU work appropriately, implement
timeouts where the host can enforce them, honor shutdown, and propagate
structured errors. Do not spawn durable detached workers from a request
without the platform's scheduler and lifecycle contract.

## API surfaces and authentication

- Plugin catalogs, install/enable/lifecycle and invocation live under the
  canonical [plugin](../../src/ai_karen_engine/api_routes/plugins/plugins.py)
  and [extension](../../src/ai_karen_engine/api_routes/extensions/extensions.py)
  routes.
- Backend plugin settings and credential management are served under
  "/api/extensions" as documented in
  [Settings and Credentials](06-settings-and-credentials.md).
- File upload uses the governed "/api/store/upload" path but does not imply
  execution.
- Specialized APIs such as "/api/voice" are thin ingress to an existing
  first-class runtime, not a license for each plugin to mount a competing API.
- Authenticated context and tenant UUID come from host middleware/dependencies,
  not the request payload.

Never create a second route such as "/run-my-plugin" to bypass the canonical
validation and audit chain.

## Result semantics

Return a typed, truthful success or error. A handler's successful Python
return is not always successful delivery, external publication, durable
persistence or model health. Separate observed facts from provider assertions.

Document for each action: input schema, output schema, side effects,
idempotency/replay policy, latency and memory budget, rollback or compensation,
permission requirements, and error codes.

## Failure behavior

| Failure | Correct behavior |
| --- | --- |
| Plugin missing / disabled | Deny, no handler invocation |
| Tenant or role mismatch | Deny and audit, no data leakage |
| No authorized plan | Fail closed |
| Invalid payload | Reject before handler |
| Dependency unavailable | Report unavailable, not success |
| Native inference fails | Return bounded error without leaking paths/audio |
| Request cancelled | Preserve model worker safety; do not leak capacity |
| Output violates schema | Reject result, record typed error |
| Persistence/audit unavailable | Do not announce saved or completed effects |

The UI cannot bypass these failures or silently substitute a cloud action.

## Observability required on all actions

Capture request and correlation IDs; tenant/user/session/conversation scope;
plugin ID, version and capability; requested/actual runtime details; policy
decision; provider/model if relevant; durations; lifecycle status; and typed
error. Avoid logging secrets, audio, whole prompts or arbitrary user payloads.

More: [Testing and Observability](09-testing-and-observability.md).
