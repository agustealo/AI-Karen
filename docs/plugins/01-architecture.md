# 01. Architecture and ownership

[Wiki index](README.md) · [Next: Quickstart](02-quickstart.md)

**Status: Implemented core boundaries.** A few legacy namespaces remain in the
repository; a file existing is not evidence that it is the active owner.

## Authority map

| Responsibility | Canonical owner | Not owned by |
| --- | --- | --- |
| HTTP ingress and authentication | API routes and auth dependencies | Plugin handler |
| Intent, tool and policy decisions | CORTEX / RuntimePolicy | FastAPI routes, React |
| Chat execution and context | ChatRuntime | Plugin, UI, API route |
| Discovery, provenance and lifecycle | PluginKernel / registry | Handler's private registry |
| Allowed capability and schema execution | ExtensionExecutionService | Plugin-specific endpoint |
| Admin plugin configuration | PluginService / PluginSettingsRepository | localStorage, handler JSON file |
| Credential values and rotation | Identity Vault | Generic settings DB / plugin logs |
| Provider/model eligibility | Canonical model registry and runtime | Extension UI |
| Audio orchestration | VoiceRuntime | TTS model adapter |
| UI presentation | CopilotKit / theme components | A second conversation runtime |

## The execution chain

~~~text
HTTP / chat / scheduled entry
  -> authenticated user + tenant + correlation
  -> CORTEX capability decision
  -> RuntimePolicy / AuthorizedExecutionPlan
  -> PluginKernel catalog + validated manifest
  -> ExtensionExecutionService execution gates
  -> approved capability adapter
  -> output validation + provenance + audit + telemetry
  -> ChatRuntime presentation / persistence
~~~

The execution path must preserve the authorized plan and cannot silently fall
back to a different plugin, provider or network transport. A plugin **may**
call its own internal helpers after admission, but cannot independently decide
which global capability should run.

## Extension taxonomy

**Tool extension:** performs a narrowly typed action such as search or time
arithmetic. It receives validated invocation inputs, not arbitrary conversation
state or credential values.

**UI extension:** contributes a page or hook-zone component through the
UI materialization flow. Visibility is not execution permission.

**Communication extension:** declares a versioned
"capabilities.communication_channel" contract, but channel connections remain
governed by the Channel Gateway. A channel is not an alternative chat runtime.

**Modality engine:** implements a capability like text-to-speech or
transcription, but is registered under an existing host runtime. The voice
plugin extension contract is **proposed**; see
[Voice and Modalities](08-voice-and-modalities.md).

**Core service:** stays in core if it is foundational to orchestration,
memory governance, policy or runtime model selection. Creating an extension
wrapper does not transfer authority out of core.

## How PluginKernel fits together

The active kernel is
[extensions/plugin_kernel.py](../../src/ai_karen_engine/extensions/plugin_kernel.py).
It projects validated catalog manifests into the typed runtime extension
contracts. The kernel tracks dependencies, loaded instances, enabled state,
provenance, concurrent executions, and refresh/disable fencing. Its registered
capabilities use
[ExtensionExecutionService](../../src/ai_karen_engine/extensions/executor.py).
[PluginService](../../src/ai_karen_engine/services/plugin_service.py)
is the application facade, not a second kernel.

The manifest owner is
[platform/core/manifest.py](../../src/ai_karen_engine/extensions/platform/core/manifest.py).
Its strict Pydantic model may be reached through compatibility normalization
for older manifests. New extensions must target the canonical model, not
legacy schemas or unknown top-level keys.

## A practical responsibility audit

Before adding a file, answer:

1. Which existing component owns this operation?
2. What would be duplicated by adding another service, route or registry?
3. Is the implementation active, transitional, legacy, experimental or dead?
4. Does the work add a capability or try to steal core authority?
5. Does the state survive restarts, tenant switches, revocation and failures?
6. What direct test proves that a real authorized caller can execute it?

Keep classes small, typed and dependency-injected. Register or delegate through
the existing owners. Don't hardcode ports, models, credentials, directory
roots, fallbacks or shared-policy decisions inside plugin packages.

## Architecture anti-patterns

| Forbidden approach | Correct approach |
| --- | --- |
| Plugin directly calls another provider from route | Runtime-authorized provider/capability |
| Handler reads arbitrary tenant memory | Governed, scoped memory service |
| React chooses model availability | Render backend-reported readiness |
| ZIP claims "trusted" in manifest | Host verifies source provenance |
| Plugin creates its own user settings storage | Reuse canonical preferences owner |
| Plugin launches unrestricted shell command | Explicit approved runtime and isolation |
| Manifest promises streaming without inference proof | Report tested, active capability |
| Plugin catches failure and invents a success response | Typed failure + audit |

## Related source contracts

- [Manifest](../../src/ai_karen_engine/extensions/platform/core/manifest.py)
- [Kernel](../../src/ai_karen_engine/extensions/plugin_kernel.py)
- [Execution contract types](../../src/ai_karen_engine/extensions/contracts.py)
- [Executor](../../src/ai_karen_engine/extensions/executor.py)
- [Action gate](../../src/ai_karen_engine/extensions/platform/core/governance/execution_gate.py)
- [Broader platform architecture](../development/EXTENSIONS_TOOLS.md)
