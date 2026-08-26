# Security and Observability

## 1. Security is runtime/backend authority

Security decisions are enforced server-side. UI state is presentation, not authorization.

Must preserve:

- authentication/session validity;
- RBAC;
- tenant isolation;
- least privilege;
- action/extension permission checks;
- secret/credential protection;
- audit trail;
- safe error translation;
- request/correlation identity;
- production fail-closed behavior.

## 2. Tenant rules

Tenant scope must be explicit at trust boundaries. Never silently substitute `tenant_id="default"` in production security-sensitive execution, memory recall, plugin execution, admin operations, or persistence.

Cross-tenant access is a critical defect.

## 3. Development bypasses

Development bypasses must be:

- impossible or fail-closed in production;
- explicit/configured;
- tested with production security contracts;
- never inferred from UI headers alone in a production path.

## 4. Credentials and secrets

- use canonical credential/config services;
- redact secrets from logs/events/errors;
- do not pass production secrets as Docker build args;
- do not persist raw credentials into memory;
- avoid long-lived credentials in client-side storage;
- privileged integrations require explicit scopes and ownership.

## 5. Admin actions

Admin APIs live under the dedicated admin surface and enforce backend RBAC plus audit. Do not hide admin logic inside generic user routes or frontend-only checks.

## 6. Action security

Tool/plugin/extension side effects must preserve:

```text
authenticated actor
 -> tenant scope
 -> RBAC/permission
 -> RuntimePolicy eligibility
 -> ActionExecutionGate
 -> action
 -> audit/telemetry
```

## 7. Safe errors

Errors returned to clients should expose stable error categories/codes and useful recovery information without leaking credentials, stack internals, SQL, private filesystem paths, or provider secrets.

Do not catch broad exceptions simply to return fake success.

---

# Observability

## 8. One observability platform

Canonical observability lives under:

```text
src/ai_karen_engine/platform/observability/
```

Subsystems emit through canonical contracts/adapters rather than maintaining private telemetry platforms.

## 9. Correlation context

Capture when applicable:

- correlation_id;
- request_id;
- user_id;
- tenant_id;
- session_id;
- conversation_id;
- intent;
- topology;
- provider/model/runtime engine;
- fallback/degraded state;
- response source;
- memory recall count;
- plugin/agent/tool identity;
- latency/status/error code.

Sensitive IDs must follow privacy/logging policy.

## 10. Structured lifecycle events

Important events include:

- request received/completed/failed;
- auth result;
- intelligence/CORTEX/policy start/complete/deny;
- memory recall start/complete;
- prompt start/complete/fail;
- provider selection/execution/fallback;
- workflow/agent/tool/extension execution;
- persistence result;
- degraded/unavailable result.

Use structured logging. Runtime code must not rely on `print()`.

## 11. Metrics

`platform/observability/MetricsCollector` is the process numeric metrics authority.

Prometheus is an exposition adapter. It must export the same collector that runtime middleware/services update, not a separate registry.

Use bounded labels. High-cardinality values such as request/user/session/correlation IDs, raw prompts, arbitrary URLs, and error messages belong in structured events/traces.

## 12. Health vs readiness vs diagnostics

```text
/health/live   -> process liveness only
/ready         -> traffic readiness
/api/health/*  -> detailed monitoring
/admin/health/* -> privileged operator diagnostics
/metrics       -> metrics exposition with configured scrape policy
```

Optional provider degradation should not automatically cause container restart loops.

## 13. Degraded response metadata

Where applicable return/record:

```text
degraded_mode
degradation_reason
requested_provider
requested_model
actual_provider
actual_model
runtime_engine
fallback_level
response_source
latency_ms
correlation_id
```

Never disguise an unavailable provider with canned model-like text.

## 14. Tests

Security/observability changes should prove:

- production bypass disabled;
- RBAC/tenant isolation;
- secret redaction;
- action permission denial;
- admin audit behavior;
- correlation propagation;
- canonical metrics authority;
- bounded label enforcement;
- liveness/readiness contract;
- degraded metadata and fallback truth.
