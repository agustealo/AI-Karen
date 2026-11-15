# 10. Packaging, upgrades and operations

[Wiki index](README.md) · [Trust and lifecycle](04-lifecycle-and-trust.md)

**Status: Implemented first-party installation/trust controls; third-party
isolated execution remains unavailable.**

## Supported distribution categories

| Package | Current execution position |
| --- | --- |
| Built-in, reviewed and operator-shipped | Eligible for canonical in-process host after runtime gates |
| Manually uploaded ZIP | Quarantined and disabled; not executable |
| Third-party package claiming to be signed | Still needs verified trust and isolation policy |
| Model weights, native voice binaries | Separate installation/provenance and dependency requirements |
| Frontend module | Governed UI materialization, not automatic remote code injection |

Do not use a README or manifest field to override trust classification.
"Uploaded but visible" is not "installed and ready".

## First-party release checklist

1. Confirm this capability belongs in an extension, not a new core owner.
2. Preserve the stable plugin ID, versioned manifest and action schema.
3. Keep all permissions minimal and document network/filesystem privileges.
4. Verify source license, dependency licenses, SPDX metadata, SBOM and
   redistribution rights for external models/media/voice references.
5. Pin reproducible versions and checksums; reject moving model aliases for
   installed release artifacts.
6. Include full dependency and optional-accelerator behavior in documentation.
7. Confirm no unrequested auto-download, network fallback or shell execution.
8. Implement bounded request resources, cancellation, startup and shutdown.
9. Test lifecycle, tenant isolation, RBAC, settings/Vault and UI.
10. Run exact-head CI and required live integration acceptance.
11. Document deployment prerequisites: migrations, persistent encryption key,
    storage capacity, model directory, OS/architecture and audio backend.
12. Preserve rollback, revision fencing, audit evidence and safe data retention.

## Versioning rules

Maintain version separation between:

- plugin package semantic version;
- canonical manifest/API compatibility version;
- prompt contract ID/version;
- model revision and artifact digest;
- application/host minimum version;
- persisted settings schema/migration version;
- proposed modality capability-contract version.

The plugin version cannot substitute for a model digest. A new installed
plugin does not certify a machine can run the required native accelerator.

## Deploying schema changes

Migration files, not runtime plugin initialization, own schema creation
and DDL. Use additive migrations wherever possible. Ensure RLS, permissions,
indexes, tenant scope and audit survive upgrades. Test against disposable
PostgreSQL and verify that the same migration is applied to the actual
deployment; CI alone cannot prove production migration state.

For current plugin settings and credential bindings, see
[Settings and Credentials](06-settings-and-credentials.md).

## Operational lifecycle

### Install

Review source and provenance, validate manifests, dependency graph,
capability schemas, UI materialization and secrets policy. Upload does not
enable code.

### Configure

An authorized admin supplies tenant nonsecret settings and secret slots via
existing revisioned controls. Required fields missing means unready; a
successful HTTP response is not enough unless a new DB revision is returned.

### Enable

Only the host grants lifecycle eligibility. Confirm active runtime engine,
license acceptance and resource budget before advertising a capability.

### Observe

Record status and latency from real requests. Expose readiness/health
separately from installed/enabled. Watch worker memory, timeouts, native
process exit codes, error rate, cancellation and audit delivery.

### Upgrade

Block new work, drain active work, verify artifact hashes and module eviction,
then publish a new version. If upgrade fails, retain the prior trusted state
or honestly report unavailable. Never cross-load stale native libraries.

### Disable or revoke

Close admission, revoke sessions/credentials where appropriate, drain
inference, verify model shutdown and invalidate catalog/UI selections.
Don't silently run a different cloud model.

### Uninstall

Remove executable artifacts through the governed lifecycle only after
reference/retention checks. Secrets, user-owned audio, audit and historical
revisions need independently authorized cleanup and evidence.

## Voice plugin shipping specifics

For Pocket TTS: pin verified upstream release and model revision, audit
licenses for weights and speaker samples separately, prove offline inference
on supported CPUs, measure first-audio and memory. A working Python import,
mock audio file or browser-only speech synthesis is insufficient.

## Rollback drill

Before merge/rollout, document the previous plugin and host versions,
required migrations, model/cache compatibility, and whether downgrade would
expose a newer settings schema. Exercise a failed upgrade with concurrent
inference, a revoked credential, and a user-selected now-missing model.
System truth should be "unavailable" until a permitted replacement is ready.

## Release status vocabulary

- **Implemented**: source and contract tests pass.
- **CI-verified**: exact-head jobs passed.
- **Integration-verified**: real DB and service dependencies exercised.
- **Hardware-verified**: actual model/media outputs and performance measured.
- **Consumer-ready**: install, update, settings, runtime and UI flow
  independently passed on supported environments.

Never collapse all five into "done".
