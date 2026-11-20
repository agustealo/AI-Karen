# 03. Manifest schemas, prompts and capabilities

[Wiki index](README.md) · [Quickstart](02-quickstart.md)

**Status: Implemented, with legacy compatibility.**

## Two manifests, two audiences

The runtime system manifest is "plugin_manifest.json". The canonical Python
model is
[ExtensionManifest](../../src/ai_karen_engine/extensions/platform/core/manifest.py)
in the platform core. Discovery reads that file. If the plugin contributes
frontend UI, "manifest.json" describes the GUI materialization entrypoint.
The two files are not interchangeable.

Refer to [Time Query](../../src/ai_karen_engine/extensions/plugins/time-query/plugin_manifest.json)
and its [GUI manifest](../../src/ai_karen_engine/extensions/plugins/time-query/manifest.json)
for existing real packages. They are reference code, not guarantees that all
legacy fields will be accepted in a new strict manifest.

### Generative presentations (KGUI-01)

The optional `capabilities.generative_presentations` declaration is validated
by the canonical `ExtensionManifest`. It advertises compatible **existing**
host component types, a semantic version, allowed host surfaces (`chat`,
`workspace`) and `interaction_mode: read_only`. The projected plugin
catalog marks it `status: declaration_only` and never asserts provider,
renderer, model or plugin health. Unknown types, executable UI code, mutable
interaction modes, and unknown declaration keys are rejected.

The declaration is **not** installation, action permission, data evidence,
lifecycle readiness or a new presentation registry. RuntimePolicy, the
owned-snapshot gateway, completed-run evidence and
`presentation_contract.validate_presentation` still determine what may be
emitted, restored and displayed. The TypeScript
`KarenPresentationRegistry` continues validating the exact bounded envelope.
Do not create dynamic imports or trust arbitrary plugin JSX from chat content.

The first contract slice does **not** enable charts, code execution, movie
posters, forms, custom interactive components or full-card pinning. Add new
types only after host schema parity, source provenance, replay and authenticated
browser acceptance. See [Generative experiences and migration](13-generative-experiences.md).

### Canonical system manifest fields

| Field | Required or default | Meaning |
| --- | --- | --- |
| name | required | Lowercase kebab-case, up to 50 characters |
| version | required | Semantic version |
| display_name, description, author, license, category | required | Catalog metadata |
| purpose, tags | optional | Search and intent explanation |
| api_version | default 1.0 | Plugin API compatibility |
| kari_min_version | default 0.4.0 | Minimum compatible host declaration |
| entrypoint | optional | Python "module:ClassName" for executable code |
| capabilities | typed object | Declares UI/API/background/webhook/prompt/channel intent |
| prompt_files | typed object | PromptRegistry contract reference and mode |
| dependencies | typed object | Plugins, extensions and system services |
| permissions | typed object | Requested capabilities, never a grant |
| rbac | allowed_roles, default_enabled | Declared eligibility and initial state |
| resources | bounded resource hints | Resource requests, not proof of enforcement |
| config_schema | optional | Tenant admin settings declaration |
| execution_input_schema | optional | Invocation parameters, kept separate |
| hook_points | optional | Recognized host lifecycle hook enum |
| ui, api, background_tasks, marketplace | optional | Integration metadata |

The canonical Pydantic model rejects unexpected fields when constructed
directly. Its explicit "from_dict" compatibility path strips known legacy
fields and warns on unknown values. Do not rely on silent stripping to make
a new plugin deployable.

### Identity and versioning

The "id" compatibility key, when supplied, must match "name". Prefer a stable
plugin ID across versions. State migrations and dependency checks must not
silently rename it. Version bump whenever behavior, schema, security grants,
asset requirements or UI contracts change.

### Capabilities are declarations

Current typed top-level capability flags include "provides_ui",
"provides_api", "provides_background_tasks", "provides_webhooks", and
"prompt_first", plus the optional communication-channel declaration.
There is **not yet a standardized voice TTS/STT capability declaration** in
the runtime manifest. The proposed voice extension is described separately
in [Voice and Modalities](08-voice-and-modalities.md).

### Admin settings and action parameters are not interchangeable

"config_schema" configures persistent tenant settings, backed by a governed
repository. "execution_input_schema" validates one invocation's explicit
inputs. When a manifest declares configuration:

- invocation must not reuse any configuration field names;
- the input schema must declare "additional_properties": false;
- omitting the input schema means **no caller parameters are accepted**;
- host readiness is evaluated separately; declaring a default is not a save;
- the input contract never becomes a path for credential injection.

See [Settings and Credentials](06-settings-and-credentials.md) for the
restricted persisted field types and writable schema subset.

### Prompt-first rules

The registry supports modes "default", "custom" and "none".

- **default:** use host/runtime prompt authority. Discovery must not invent a
  plugin-specific default prompt ID.
- **custom:** supply a "prompt_files.contract_id" registered in the canonical
  PromptRegistry, optionally with explicit version. Validation fails when the
  declared contract cannot be resolved.
- **none:** non-LLM operations do not need a synthetic prompt. The action is
  still governed as a plugin.

"prompt_files.system", "user" and template metadata may describe files, but
the actual runtime prompt authority is the PromptRegistry. A file named
"prompt.txt" is **not automatically injected into every model request**.
Do not implement your own system-prompt merger in the handler, route or UI.

For AI-backed operations, specify expected inputs, outputs, language, safety,
token budgets, permitted tools, and fallback semantics in a versioned prompt
contract, with tests covering prompt assembly and context leakage.

### Communication channel declaration

The typed "capabilities.communication_channel" contract has a semver
"version"; "transport"; "ingress" from webhook/polling/session; inbound and
outbound kinds from text/media/command/event; "authentication" from
hmac/token/oauth2/session; and feature flags for edits, streaming, media and
delivery receipts. These fields are declarations only. Channel Gateway still
owns tenant pairing, consent, transport and delivery authorization.

### GUI manifest when UI exists

A frontend contribution normally declares stable "id", "plugin_id",
"gui_manifest_version", a category, and an "entry" with stable entry ID and
entry file. A typical structure is:

~~~json
{
  "id": "text-statistics",
  "plugin_id": "text-statistics",
  "name": "text-statistics",
  "version": "1.0.0",
  "display_name": "Text Statistics",
  "description": "Local text statistics screen.",
  "category": "productivity",
  "gui_manifest_version": "1.0",
  "entry": {
    "id": "text-statistics-main",
    "default": true,
    "entry_file": "TextStatisticsPage.tsx"
  }
}
~~~

This is a **GUI manifest shape example**; it does not create the React file.
Backend-only plugins should not advertise "provides_ui".

### Validation checklist

1. Parse the JSON and run the canonical "ExtensionManifest.from_dict".
2. Execute "ExtensionValidator.validate_manifest".
3. Confirm normalized IDs, dependencies, roles and prompt contract.
4. Validate GUI metadata if a frontend contribution is declared.
5. Ensure unknown fields do not silently disappear during normalization.
6. Test malicious inputs and incompatible versions; deny rather than guess.
7. Verify the host reports readiness independently of manifest content.

### Source references

- [Canonical manifest](../../src/ai_karen_engine/extensions/platform/core/manifest.py)
- [Discovery](../../src/ai_karen_engine/extensions/platform/core/registry/discovery.py)
- [Manifest validator](../../src/ai_karen_engine/extensions/platform/core/registry/validator.py)
- [Legacy GUI enforcer](../../src/ai_karen_engine/extensions/platform/core/registry/manifest_enforcer.py)
- [Kernel action projection](../../src/ai_karen_engine/extensions/plugin_kernel.py)
