# Extensions, Plugins, Tools, and Governed Actions

## 1. Purpose

Extensions add capabilities without turning the core runtime into a dependency warehouse. Plugins/tools/actions are governed execution surfaces, not shortcuts around runtime policy.

## 2. Canonical flow

```text
manifest / definition
   -> validation
   -> canonical registry
   -> lifecycle/health
   -> capability resolution
   -> RuntimePolicy + RBAC eligibility
   -> ActionExecutionGate
   -> execution adapter
   -> output validation
   -> audit + telemetry
```

A manifest declares what an extension can do. It does not grant permission to do it.

## 3. Extension manifest requirements

As applicable, define:

- stable ID;
- semantic/versioned definition;
- display metadata;
- capabilities;
- input/output schemas;
- prompt contract ID/version for AI-backed operations;
- permissions/roles;
- tenant scope requirements;
- credential requirements;
- network access;
- filesystem access;
- side-effect class;
- idempotency behavior/key requirements;
- timeout/cancellation expectations;
- dependencies;
- health/readiness requirements.

## 4. ActionExecutionGate

All side-effecting extension/tool execution should pass through one governed gate that can enforce:

- authenticated actor;
- tenant scope;
- RBAC/permissions;
- policy eligibility;
- manifest validity;
- requested capability;
- credential access;
- network/filesystem boundaries;
- input schema validation;
- idempotency/replay behavior;
- timeout/cancellation;
- audit context.

Do not let API routes or AgentMedusa directly invoke extension implementations around this gate.

## 5. Core vs extension responsibility

Keep foundational AI/runtime capabilities in Core when they are necessary for KAREN's own operation, for example canonical classification/reasoning/provider/memory infrastructure.

Expose adapters/extensions later when external extensibility is useful.

Do not move a core responsibility into a plugin merely to make the folder smaller.

## 6. Extension lifecycle

Canonical extension lifecycle includes:

- discovery/registration;
- validation;
- initialization;
- health state;
- load/unload when supported;
- shutdown/cleanup;
- failure/degraded state.

There must not be a root-server extension runtime and a second canonical extension runtime running concurrently.

## 7. Prompt-first extensions

AI-backed extensions reference versioned prompt contracts instead of embedding uncontrolled prompt strings throughout implementation code.

An extension prompt contract should identify the task, expected inputs, output/schema requirements, and relevant capability assumptions.

## 8. Credentials

Extensions request credentials through canonical credential/governance services. They do not read arbitrary secret files/env values directly when a governed credential path exists.

Never log secrets, refresh tokens, API keys, private cookies, or password material.

## 9. API surfaces

Canonical management/listing lives under governed extension/plugin API routes. Do not add root shortcuts such as `/plugins` that expose a second registry truth.

Management/mutation endpoints require explicit authorization. Public metadata endpoints should expose only what is intended for unauthenticated users.

## 10. Failures and degradation

Extension failure must not be converted to fake success. Return typed errors/degraded metadata and allow runtime policy to decide whether another execution path is eligible.

## 11. Observability

Emit:

- extension/plugin ID/version;
- action/capability;
- tenant/actor context through safe identifiers;
- permission decision/reason code;
- execution latency;
- status/error code;
- side-effect/idempotency state;
- correlation/request IDs.

Use bounded metric labels. High-cardinality execution IDs belong in structured events/traces.

## 12. Tests

Prove:

- manifest validation;
- permission/RBAC denial;
- tenant isolation;
- ActionExecutionGate in actual invocation chain;
- schema validation;
- idempotency/replay behavior;
- timeout/cancellation;
- audit emission;
- no direct route/Medusa bypass;
- no duplicate extension registries/runtimes;
- safe failures and credential redaction.
