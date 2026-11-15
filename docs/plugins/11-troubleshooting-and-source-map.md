# 11. Troubleshooting, error triage and source-of-truth map

[Wiki index](README.md) · [Testing](09-testing-and-observability.md)

**Status: Current source map as of 2026-11-15.** Verify the exact commit
when investigating a future regression.

## Troubleshooting decision tree

| Symptom | First check | Do not do |
| --- | --- | --- |
| Plugin not in catalog | Built-in root, manifest name, validator and discovery logs | Add a second registry |
| Invalid manifest | Canonical Pydantic fields and validator errors | Silence unknown fields |
| Upload visible but cannot enable | ".karen-upload-origin" and isolation policy | Delete quarantine marker |
| Enabled but cannot execute | Kernel status, dependency, authorized plan, RBAC, settings readiness | Call handler directly |
| Config saved but reverts | DB revision and tenant RLS scope | Cache in localStorage |
| Save returns 409 | Refresh settings and expected revision | Retry blind overwrite |
| Credentials configured but tool fails | Vault status plus execution-time authorization | Inject plaintext into payload |
| UI plugin screen missing | GUI entry, generated import map, materialization and permission | Import arbitrary ZIP code |
| "No Browser Voices Found" | Browser speech API; independent of local TTS | Claim runtime TTS is down |
| TTS 503 unavailable | Registered local synth and verified model readiness | Invent audio or cloud fallback |
| TTS 429 busy | VoiceRuntime capacity lock | Remove concurrency protection |
| Voice output wrong | Runtime-selected engine/voice ID and actual response provenance | Trust UI selected label alone |
| Duplicate output / stale behavior | Stale Python module or concurrent plugin revision | Reload code in parallel unsafely |
| Production first boot fails | Migrations, config, health, artifact presence and true logs | Fake readiness |
| Model does not load | Artifact digest, license, CPU/ABI, RAM, native process | Choose another model in route |

## Current source-of-truth directory

~~~text
docs/plugins/                                 canonical plugin developer wiki
src/ai_karen_engine/extensions/
  platform/core/manifest.py                  canonical catalog manifest model
  platform/core/registry/discovery.py        discovery and metadata
  plugin_kernel.py                           host catalog, lifecycle and projection
  contracts.py                               typed execution contracts
  executor.py                                invocation gates and results
  plugins/                                   built-in and installed plugin root
src/ai_karen_engine/services/
  plugin_service.py                          governed application facade
  plugin_settings_repository.py              tenant nonsecret settings
  voice_runtime.py                           canonical STT/TTS execution authority
src/ai_karen_engine/api_routes/
  extensions/extensions.py                   admin plugin settings and credentials
  plugins/plugins.py                         plugin listing and execution ingress
  voice.py                                   authenticated bounded voice ingress
src/ui_launchers/Karen-AI-Theme/src/
  components/plugins/                        plugin store and UI
  plugin_host/                               UI plugin hooks and registry
  components/settings/VoiceSettings.tsx      current browser voice settings
~~~

## Which documentation is authoritative?

1. [PROJECT_DEV_MANIFEST.md](../development/PROJECT_DEV_MANIFEST.md) is the
   platform-wide architectural rulebook.
2. [Development architecture authority](../development/ARCHITECTURE_AUTHORITY.md)
   defines cross-subsystem responsibilities.
3. This wiki covers plugin developer operations and source references.
4. Current source, tests and accepted ADRs resolve discrepancies.
5. Archived sprints and
   [pre-consolidation platform guide](../../src/ai_karen_engine/extensions/platform/docs/PLUGIN_DEV.md)
   are historical. Older names like "src/extensions/plugins",
   auto-loaded "prompt.txt", and plugin-created runtime tables must not be
   copied into new production code.

## Log and audit analysis

Search by correlation/request ID and plugin ID. Separate:

- discovery/manifest validation failure;
- installation provenance / sandbox denial;
- RBAC, tenant, capability or action schema denial;
- missing tenant settings, Vault status or migrations;
- native engine load failure versus runtime inference failure;
- cancellation, timeout, capacity exhaustion or audio transport failure;
- audit/persistence write failure versus UI rendering failure.

Never print decrypted credentials, full input payload, transcribed voice or
reference recordings while debugging. Use typed error codes, sanitized
error classes, high-cardinality trace IDs only in logs, and bounded metric
labels.

## Escalation template

Include the exact git SHA, plugin ID/version, manifest contract version,
tenant/role test scope (redacted), status/error code, request correlation,
expected and observed behavior, real dependency availability, CI links,
reproduction commands and rollback risk. Attach a minimal sanitized test
case. Do not include plaintext keys, personal chat contents or raw audio.

## Before declaring fixed

1. Confirm the change lives in the canonical owner.
2. Audit duplicate paths and stale references.
3. Exercise negative and failure paths.
4. Re-run matching unit/integration/UI tests.
5. Verify exact-head CI and required production gates.
6. Verify real user-visible result and persisted state.
7. Update the relevant wiki chapter and release ledger.

[Return to Wiki Index](README.md).
