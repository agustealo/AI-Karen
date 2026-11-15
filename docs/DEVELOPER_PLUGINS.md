# AI KAREN Plugin Development Guide

**Canonical plugin developer wiki:** [docs/plugins/README.md](plugins/README.md)

This page is an entry point for existing bookmarks. Detailed authoring and
operational guidance now lives in the **versioned in-repository wiki** under
"docs/plugins/" to avoid maintaining competing plugin authority documents.

## Start reading

1. [Architecture and canonical ownership](plugins/01-architecture.md)
2. [Quickstart with complete first-party plugin files](plugins/02-quickstart.md)
3. [Manifest, prompt contracts and capability declarations](plugins/03-manifests-and-prompts.md)
4. [Installation, lifecycle, quarantine and trust](plugins/04-lifecycle-and-trust.md)
5. [Runtime execution, gates and APIs](plugins/05-execution-and-apis.md)
6. [Admin settings, tenant configuration and Identity Vault](plugins/06-settings-and-credentials.md)
7. [Frontend extension and plugin settings UI](plugins/07-frontend-integration.md)
8. [Voice, TTS, STT and proposed Pocket TTS integration](plugins/08-voice-and-modalities.md)
9. [Security, tests, observability and release proof](plugins/09-testing-and-observability.md)
10. [Packaging, upgrades, rollback and operations](plugins/10-release-and-operations.md)
11. [Troubleshooting and authoritative source map](plugins/11-troubleshooting-and-source-map.md)

## Essential current constraints

- New plugins use the canonical manifest in
  "src/ai_karen_engine/extensions/platform/core/manifest.py" and the
  PluginKernel/ExtensionExecutionService runtime.
- Manually uploaded ZIPs are quarantined, **not executable** until a verified
  isolated worker is implemented. A "SANDBOX" enum does not supply OS
  sandboxing.
- Admin nonsecret settings use the PostgreSQL tenant-scoped
  PluginSettingsRepository and revision-fenced routes; secrets use
  Identity Vault. Neither is arbitrary handler-accessible data.
- Plugin action parameters use "execution_input_schema", not "config_schema".
  Their separation is enforced by the manifest/kernel.
- GUI manifests and React assets are materialized by the governed UI pipeline.
- PromptRegistry owns AI prompt contracts. A standalone "prompt.txt" is not
  automatically injected merely because a plugin folder contains one.
- VoiceRuntime provides existing engine-neutral STT/TTS contracts; a
  dynamic modality/plugin capability catalog and Pocket TTS plugin are
  **proposed**, not available to consumers yet.

This page replaces older instructions suggesting automatic runtime DDL,
legacy plugin roots, implicit prompt injection, or ungoverned plugin API
execution. Read the linked chapters and the live source before shipping.
