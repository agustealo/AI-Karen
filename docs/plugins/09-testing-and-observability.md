# 09. Testing, security and observability

[Wiki index](README.md) · [Execution](05-execution-and-apis.md)

**Status: Policy plus implemented regression suites.** This chapter is a
minimum proof contract for plugins and modality adapters, not a claim that
all currently shipping features have completed consumer acceptance.

## The testing pyramid

### Unit and contract tests

- Parse manifest through "ExtensionManifest.from_dict" and its validator.
- Ensure no undeclared/unknown action keys are accepted after schema
  projection, and configured-plugin action inputs are closed.
- Assert role/tenant/permission denial before handler invocation.
- Exercise success, invalid input, missing resource and error states.
- Verify "initialize", "shutdown", reinitialize and lifecycle idempotence.
- Confirm no raw user payload, credentials or references in structured logs.

### Integration tests

- Actual "PluginService" through "PluginKernel" to
  "ExtensionExecutionService", not just direct handler methods.
- Dependency validation and lifecycle revocation fencing.
- Real PostgreSQL tenant RLS and revision conflicts for settings.
- Identity Vault rotation/status/revocation, not plaintext pass-through.
- Audit record atomicity with settings writes.
- UI materialization failure, signed/trust provenance, and disabled state.
- Runtime/voice routes authenticated, bounded and no implicit cloud fallback.

### Consumer/e2e tests

- Install/enable approved plugin and verify runtime catalog.
- Select feature in actual UI, save and reload, then execute through canonical
  runtime on the chosen engine and verify observed result.
- Reload, logout, revoke and switch tenant while a session is active.
- Verify keyboard/focus/contrast at mobile and desktop widths.
- Verify production first-boot with real migrations, no fixture-only pass.

## Existing test entry points

These paths exist in the repository at this wiki snapshot:

- [Governance closure](../../src/ai_karen_engine/tests/test_plugin_governance_closure.py)
- [Authority collapse](../../src/ai_karen_engine/tests/test_plugin_authority_collapse.py)
- [Plugin settings contracts](../../tests/extensions/test_plugin_settings_contract.py)
- [PostgreSQL settings](../../tests/integration/test_plugin_settings_postgres.py)
- [Credential Vault](../../tests/extensions/test_plugin_credential_vault_contract.py)
- [Tenant execution readiness](../../tests/extensions/test_plugin_tenant_execution_readiness.py)
- [UI materialization](../../tests/extensions/test_ui_materialization_governance.py)
- [Voice runtime](../../tests/core/voice/test_voice_runtime.py)
- [Voice synthesis contract](../../tests/core/voice/test_voice_synthesis_contract.py)
- [Voice HTTP ingress](../../tests/core/voice/test_voice_synthesis_http.py)
- [Frontend settings persistence](../../src/ui_launchers/Karen-AI-Theme/tests/plugins/plugin-settings-persistence.test.tsx)
- [Frontend Voice settings](../../src/ui_launchers/Karen-AI-Theme/tests/settings/voice-settings.test.tsx)

A file existing does not mean it passed on the target commit. CI job success
must be checked against the **exact PR head SHA**.

## Commands

From the repository root, using the appropriate installed environments:

~~~bash
python -m compileall -q src/ai_karen_engine
pytest tests/extensions/ -q
pytest tests/core/voice/ -q
pytest tests/integration/test_plugin_settings_postgres.py -q
ruff check src tests
mypy src
~~~

From "src/ui_launchers/Karen-AI-Theme" (consult that workspace's package
scripts for available test commands):

~~~bash
npm run lint
npm run typecheck
npm run test
npm run build
~~~

At repository root, where available:

~~~bash
docker compose config
~~~

Some integration suites need PostgreSQL, migrations, services, native model
assets or permitted hardware. Missing dependencies are blockers to the
claimed proof, not permission to replace them with mocks and call the feature
ready.

## Non-negotiable adversarial cases

| Security boundary | Negative acceptance |
| --- | --- |
| Trust | Uploaded ZIP cannot execute in-process or self-relabel |
| Tenant | Tenant A cannot query B's plugin config/audio/credential status |
| Actor | User without ADMIN_PLUGINS_MANAGE cannot mutate admin settings |
| Schema | Oversized, nested, forged, undeclared inputs rejected |
| Execution | Disabled, stale, unregistered or unauthorized plugin never called |
| Secrets | No generic settings read or execution input reveals Vault plaintext |
| Side effects | Missing audit/idempotency approval fails closed |
| Lifecycle | Disable/revoke fences inflight and new work correctly |
| Model provenance | Corrupt or unknown local weights cannot advertise ready |
| Audio | Raw media not logged, no silent external fallback |
| UI | No fake "saved", "ready", "installed", "deleted" or "playing" state |

## Telemetry contract

Prefer structured events over print statements. Event fields should include
"correlation_id", "request_id", tenant/user/session scope, conversation ID,
plugin ID/version, capability, intent, requested and actual provider/model
when applicable, runtime engine, permission decision, fallback level,
degraded mode, response source, execution status, error type/code and latency.

Emit events for discovery, validation, enable/disable, execution admitted/
denied, credential lifecycle, model readiness, synthesis/transcription
started/completed/failed, cancellation, and persistence/audit outcome.

Never use unbounded request or tenant identifiers as Prometheus metric labels.
Use low-cardinality labels for timing and status. High-cardinality IDs belong
in logs/traces. Exclude secrets, user text, full prompts and raw audio from
telemetry by default.

## Release proof ledger

A plugin PR should include: exact SHA; manifest validation; source-provenance
classification; dependency and migration requirements; actual test commands;
CI links; supported host/model versions; negative tests; measured resource
use where relevant; unverified real-environment acceptance; rollback plan;
and truthfully scoped consumer readiness.

Do not close security gates by changing thresholds, removing tests,
manufacturing receipts or substituting data.
