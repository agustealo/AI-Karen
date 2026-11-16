# 08. Voice, TTS, STT and future modality plugins

[Wiki index](README.md) · [Architecture](01-architecture.md)

**Status: Implemented first-party source integration slice; proposed plugin integration
for arbitrary untrusted/third-party engines and incremental streaming.**
VoiceRuntime retains local Faster-Whisper STT and complete-WAV contracts.
The first-party Pocket TTS integration adds a versioned voice modality
declaration, permission-filtered plugin/voice inventory, authenticated local
model synthesis, and durable per-user engine selection. **It does not yet
discover or execute arbitrary TTS plugins** from untrusted uploads; those
remain quarantined. Real model acceptance still requires separately installed
gated model files, approved voices, optional runtime dependencies and hardware
tests. Passing source CI does not prove spoken output on an actual device.

The shared runtime keeps conversation, playback selection, installation,
lifecycle and authorization separate from the Pocket inference adapter.

## Responsibility split

| Capability | Owner | Contract |
| --- | --- | --- |
| Microphone capture | Karen browser | Browser capture controls and explicit consent |
| Input voice activity / segmentation | Host or authorized VAD adapter | Bounded, local, measured audio |
| Transcription / listening | VoiceRuntime + STT adapter | Typed AudioInput and TranscriptionResult |
| Spoken replies | VoiceRuntime + TTS adapter | Typed SynthesisInput and SynthesizedSpeech |
| Audio playback | Karen browser | Session-based play, stop, seek if supported |
| Conversation intent and turn selection | ChatRuntime + CORTEX | Authorized runtime decision |
| Model catalog / installation | Existing model lifecycle and PluginKernel | Installed model provenance, digest, readiness |
| User engine and voice preference | Authenticated user preferences | Tenant/user scope and revision fencing |
| Admin permitted plugin settings | PluginService | Nonsecret tenant settings and approved credentials |
| Voice cloning / uploaded references | Consent and governed media owner | Explicit grants, TTL, deletion and audit |

Pocket TTS is a **synthesis plugin**. It does not listen, transcribe, manage
conversations, or own browser playback merely because it emits audio.

## Implemented runtime baseline

Canonical source:

- [VoiceRuntime and protocols](../../src/ai_karen_engine/services/voice_runtime.py)
- [Voice contracts](../../src/ai_karen_engine/core/voice/contracts.py)
- [Authenticated voice routes](../../src/ai_karen_engine/api_routes/voice.py)
- [Application lifespan](../../src/ai_karen_engine/server/application_runtime.py)
- [Faster-Whisper adapter](../../src/ai_karen_engine/services/local_whisper_adapter.py)
- [Browser voice settings](../../src/ui_launchers/Karen-AI-Theme/src/components/settings/VoiceSettings.tsx)
- [Browser read-aloud](../../src/ui_launchers/Karen-AI-Theme/src/components/chat/KarenBrowserSpeechPlayback.tsx)

Today the available authenticated endpoints include:

| Method/path | Existing semantics |
| --- | --- |
| GET /api/voice/capabilities | Actual registered STT/TTS health and single engine/voice status |
| POST /api/voice/transcriptions | Bounded WAV request to registered local STT |
| POST /api/voice/synthesis | Bounded text to verified complete WAV, if local synthesis registered |
| GET /api/voice/engines | Verified installed local TTS plugins/voices, scoped to authenticated principal |
| POST /api/voice/engines/{engine_id}/synthesis | Chosen approved TTS plugin via PluginService, RuntimePolicy and VoiceRuntime, bounded private WAV |
| GET /api/settings/voice | Durable user-level engine and voice selection plus current availability |
| PUT /api/settings/voice | Validate against live engine catalog and persist on authenticated user record |

"VoiceRuntime" currently holds one "LocalSynthesisEngine" interface with
"engine_id", "voice_id", "is_ready()" and "synthesize(request)" and one
transcription interface. A placeholder engine must never be reported ready.
The synthesis contract limits input text to 2,000 characters and output to
a bounded WAV byte payload. The streaming flag is not populated by an
incremental TTS implementation today. Revocation and concurrency locking
must survive client cancellation until native inference drains.

The built-in Faster-Whisper STT remains separately opt-in and is not
silently replaced by Pocket.

## Proposed common Voice Capability API v1

The **first-party TTS inventory** has implemented a versioned
`capabilities.voice_modality` manifest declaration and authenticated
`/api/voice/engines` catalog. The more general multi-modal contract below
remains a **design proposal**, not a published schema for uploaded third-party
plugins, streaming media, cloning or arbitrary model inventory. Its purpose
is to prevent future engines from adding their own router and settings store.

~~~json
{
  "contract_version": "1.0.0",
  "plugin_id": "pocket-tts",
  "plugin_version": "1.0.0",
  "modalities": ["tts"],
  "features": {
    "streaming": true,
    "voice_catalog": true,
    "voice_clone": false,
    "custom_voice_upload": false
  },
  "models": [
    {
      "model_id": "validated-local-model-id",
      "revision": "approved-pinned-revision",
      "installed": true,
      "healthy": false
    }
  ],
  "voices": [],
  "readiness": {
    "status": "unavailable",
    "verified_at": null
  }
}
~~~

The model ID and revision strings above illustrate **shape only**; they are
not actual Pocket model identifiers. Likewise, "streaming: true" is only a
proposed declaration, not verified readiness. A future implemented response
must derive live availability from the running engine and independent model
health tests, and must not accept a plugin's self-reported status unchecked.

### Capability negotiation

1. PluginKernel returns installed, enabled, provenance-approved candidates.
2. Host validates declared modality contract version and supported feature
   vocabulary.
3. Canonical model store verifies installed pinned artifacts and licenses.
4. Runtime probes genuine cold/warm readiness, supported voices, format and
   streaming behavior without making user content an arbitrary test payload.
5. RuntimePolicy filters the candidates for actor, tenant, consent and
   resource budgets.
6. Assistant Voice settings displays only selectable verified candidates.
7. Runtime executes the chosen engine without route-level provider selection.
8. Revocation, shutdown or engine replacement atomically prevent new sessions.

Dynamic voice options should be typed and bounded, not arbitrary plugin HTML.
Useful fields: installed voice ID, language, display name, source, trust,
cloning policy, model revision, supported sample rates, stable features, and
permission requirements.

## Pocket TTS first-plugin implementation plan

**Upstream version check:** Kyutai Pocket TTS released "v4.0.1" on
2026-10-21. That upstream tag and its dependencies should be inspected and
pinned when implementation starts:
[GitHub release](https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1).
Release notes state the English "english_2026-10" default was updated and
small-model fixes were included. They do not prove Karen has installed
any model.

### Package ownership

- First-party, source-reviewed built-in plugin ID "pocket-tts".
- Only engine-specific inference logic, voice catalog adapter and approved
  model version pins belong in the package.
- Existing model registry installs/validates artifacts; do not introduce a
  second model downloader or filesystem registry.
- Canonical VoiceRuntime coordinates selection, cancellation, concurrency
  and streaming; no independent ASGI server, WebSocket gateway or chat
  orchestrator inside the plugin.
- Plug into shared backend capability negotiation only after the bridge and
  admission checks exist.
- Start English-first and CPU-first, measure actual memory/cold-start/first
  audio on Karen's supported hardware.
- Native binary, Rust or Python runtime choice follows benchmarks, dependency
  policy, compatibility and safe process lifecycle, never a guess.

### Voice cloning, consent and licensing

Voice cloning is **off by default**. Enabling it requires a separate explicit
user consent, reference ownership policy, tenant isolation, authorization,
malicious-upload controls, retention/deletion rules, and proof that every
individual bundled/reference voice may legally be used and redistributed.
Upstream repository code license is not enough to determine weights or
individual voice-data licensing.

Do not persist reference audio as ordinary plugin JSON settings, duplicate
user preferences, log speaker data, or implicitly call network endpoints.

### Streaming contract, proposed

A first-class streaming API must have explicit session ID, message ID,
sample format and rate, monotonically ordered chunks, cancellation, end-of-
stream outcome, and backpressure limits. Browser playback consumes these
chunks; it never authorizes which model runs. Avoid caching private audio in
shared HTTP caches. Failure must not reuse audio from another user's session.

The existing complete-WAV route remains the compatibility transport until
a streaming protocol is actually implemented and tested.

## First-class Copilot consumer voice controls

The CopilotKit v2 chat now mounts its speech controls in one
[Copilot voice dock](../../src/ui_launchers/Karen-AI-Theme/src/components/chat/copilotkit/KarenCopilotVoiceDock.tsx),
rather than a disconnected two-microphone footer. This dock is a **consumer UI
slice**, not another runtime or model registry.

- Shows independently verified `/api/voice/capabilities` listening readiness.
  Heavy `/api/voice/engines` and saved output preference discovery run only
  after the user opens Voice options, so chat boot/first prompt does not
  cold-load a TTS model. Neither advertises an uninstalled model.
- Uses the existing
  [durable user voice preference](../../src/ai_karen_engine/api_routes/system/settings.py)
  and `/api/settings/voice` for inline engine and voice selection.
  The UI confirms a save **only after server acknowledgement and readback**;
  failed readback is not a saved setting.
- A previously saved but revoked or missing model is visibly unavailable.
  Browser speech is an explicitly saved selection, never an automatic
  replacement for an unavailable local model.
- Reuses KarenLocalDictationCapture and opt-in KarenBrowserDictationCapture.
  Their output only edits the verified Copilot composer draft; it cannot
  submit messages or bypass the draft CAS workflow.
- Disables/unmounts microphone capture while the chat run or draft is locked.
  Read-aloud remains an explicit action on a Copilot assistant message and
  resolves its selected voice at playback time.
- Applies responsive, browser-standard HTML controls and the existing design
  system. No operating-system-specific executable or packaged speech binary
  is shipped by the UI slice.

### Global read-aloud lifecycle (follow-on source slice)

CopilotKit now displays the active output phase (**Preparing speech** or
**Karen is speaking**) and a global **Stop audio** control in the same dock,
even when the assistant message that initiated playback is scrolled away.

The existing `KarenBrowserSpeechPlayback` module is the **sole per-tab
playback owner**. Its `useAssistantPlaybackPhase` subscription shares only an
ephemeral phase value; `stopAssistantPlayback` delegates to the current
session's existing abort/cancel handler. It does **not** retain speech text,
audio blobs, voice credentials, or execution context. The message's own Stop
button and unmount cleanup remain in force. Starting another assistant reply
still preempts the previous reply; no automatic speech starts on chat mount,
history replay, draft edit or agent completion.

Provider and transport errors never show raw backend exception messages in
the chat. Explicit local UX errors remain actionable, including missing
saved engines and unavailable browser voices. Local synthesis aborts before
creating playable audio if the user clicks Stop while it is preparing.

**Proof:** `tests/chat/browser-speech-playback.test.tsx` verifies
preparing/speaking/idle status, global cancellation during pending local
inference, single active reply, no autoplay and error redaction.
`tests/chat/copilotkit-consumer-architecture.test.ts` verifies the dock
delegates to this existing owner instead of synthesizing speech itself.
These are source/browser-API unit tests, **not** non-mocked device proof.

**Source proof:**
[Copilot voice dock tests](../../src/ui_launchers/Karen-AI-Theme/tests/chat/copilotkit-voice-dock.test.tsx)
cover no-engine truth, separate STT readiness, backend-acknowledged settings,
revocation, readback mismatch, error sanitization, and disabled capture.
The existing local dictation and speech playback tests remain authoritative
for microphone teardown and audio cancellation.

**Acceptance still open:** real Pocket model installation, CPU synthesis and
browser playback must pass on supported target hardware. Unit/UI contract
proof does not establish native quality, hardware performance, consent, or
release readiness. See the
[Pocket acceptance ledger](12-pocket-tts-native-acceptance.md) when available
on the release branch.

### 2026-11-16: TTS admission and model publication safety audit

Two canonical-owner corrections protect model-backed consumer voice:

- `api_routes/voice.py` does **not** probe the plugin engine catalog before
  `VoiceRuntime.synthesize_with_plugin`. That runtime operation already
  performs the actor/tenant/RBAC-eligible catalog verification before governed
  execution. A duplicate route probe previously loaded/probed Pocket twice per
  speech chunk and widened a check/use race. The ingress retains bounded JSON,
  authentication and busy rejection, and leaves admission to VoiceRuntime.
- `ModelDownloadControlService` installs a reviewed `validated_revision`
  under that pinned reference, not the mutable `main` directory, even when
  the incoming optional `revision` is absent or `main`. Model/revision
  publication paths reject traversal, empty segments and symlink escapes.
  Existing jobs are not silently migrated; their recorded installed paths
  remain durable evidence for independently authorized models.

Proof source: `tests/core/voice/test_voice_plugin_http.py` and
`tests/core/model_runtime/test_model_download_durable_worker.py`.
Exact-head CI and real licensed Pocket model/browser audio remain separate
required gates; no new runtime, model registry or installer was introduced.


### Tenant-scoped Pocket model installation provenance (2026-11-16)

Pocket TTS previously read only the last 500 globally completed download jobs,
then filtered their metadata in the plugin. An older authorized model could
disappear behind other tenants' downloads. Worse, its tenant filter accepted
empty tenant identities, even though migration 42 explicitly classifies
unowned legacy downloads as administrator-only pending reconciliation.

The **existing model-download PostgreSQL repository** now performs the exact
tenant/model/revision/channel, completed-state, accepted-license and
non-remote-code checks **before** pagination. VoiceRuntime and PluginService
still own authenticated caller admission and RBAC; Pocket receives eligible
installation evidence only through ModelDownloadControlService and continues
to inspect model assets for trusted paths and symlinks. The new filtered index
in migration 55 supports this canonical query without a second registry.

An unowned or foreign-tenant completed job is never promoted to consumer
inference eligibility, even when its model files exist on the shared host.
There is no migration of existing job ownership, silent fallback, automatic
license acceptance, or direct plugin database access.

Source proofs: `tests/core/model_runtime/test_model_installation_tenant_admission.py`
and `tests/core/voice/test_pocket_tts_plugin.py`. Run integration acceptance
with the actual PostgreSQL schema and a real authorized Pocket model before
claiming production tenant isolation or consumer-ready audio.

## UI behavior

User settings should offer separate *speech output* and *speech input*
selection. One user can use Pocket TTS for speaking and Faster-Whisper for
transcription. Missing browser voices do not mean local TTS is down.
When no verified local engine exists, the UI must say "Not installed" or
"Unavailable", not list fictitious default voices.

Admin installation and model configuration are separate from personal
engine/voice preferences. Preview must not append an assistant message.
Auto selection cannot silently route speech to a cloud service or a browser
voice that might transmit content to the OS vendor.

## Voice-specific acceptance

- Real model, offline and pinned checksum verification.
- Supported CPU, peak RAM, real-time factor and warm first-audio p50/p95.
- WAV header/channel/sample-rate integrity and spoken content quality.
- Model unavailable, path tampering, license missing, stale manifest and
  runtime disabled states.
- RBAC, tenant isolation, consent, voice reference revocation and no secret
  logging.
- Concurrent request limit and native cancellation/cleanup after disconnect.
- Actual settings selection survives reload and changes the runtime
  invocation; browser playback matches the chosen installed engine.
- Streaming chunks are ordered, bounded and stop correctly.

**Release gate:** no user-facing "Pocket TTS ready" or "streaming available"
until real local audio generation and end-to-end browser tests have passed.

### Consumer failure and cancellation reconciliation (2026-11-16)

The browser/Copilot voice audit fixes three edge cases without creating
another speech service:

- `LocalVoiceEngineSettings` ties preview-ended/error callbacks to the
  **specific audio element and abort controller** that created them.
  A late callback from a stopped or replaced preview can no longer stop
  newer audio or overwrite its status.
- Voice Settings uses the same authorized preference write-and-readback
  contract as the Copilot voice dock. A successful write response without
  matching durable `GET /api/settings/voice` is a **not verified** result,
  never a saved-success notification. Old responses after a settings
  refresh/unmount cannot claim a successful save.
- `KarenBrowserSpeechPlayback` bounds all synthesis chunks, including very
  long unspaced text/URLs, without truncation or breaking UTF-16 surrogate
  pairs. Both the browser speaker and the local plugin path use this one
  chunk generator.
- Optional browser-vendor dictation merges a final transcript against the
  **live current draft** rather than a snapshot taken when recording started.
  Each recording can commit at most once, and old recognition callbacks are
  fenced from later sessions. The vendor still requires explicit user consent
  and the feature remains disabled by default.

Proof: `tests/settings/local-voice-engine-settings.test.tsx`,
`tests/chat/browser-speech-playback.test.tsx`, and
`tests/chat/browser-dictation-capture.test.tsx`. These test UI behavior and
synthetic audio callbacks, **not** real Pocket model quality, browser vendor
processing, or device-level audio acceptance.


## First-class Voice Studio navigation (2026-11-16)

The plugin overview's **Frontend: not required (backend-only)** status is
correct for Pocket TTS. The extension provides model-backed synthesis through
the canonical backend, not a distributable React UI component. Installing a
second plugin frontend merely to hide that status would duplicate ownership.

The first-class consumer path is now:

1. **Plugins & Tools → Pocket TTS → Open Voice Studio** for TTS plugins with a
   backend-declared `capabilities.voice_modality` v1 contract. The canonical
   `ExtensionCoreManager` preserves the validated modality declaration in
   `/api/extensions/list`; it does not project model or runtime health.
2. **Assistant → Voice → Local Voice Studio** presents only engines returned
   by the authenticated `GET /api/voice/engines` VoiceRuntime catalog and
   the user's saved `GET /api/settings/voice` selection.
3. Voice selection presents real installed voice IDs, languages and verified
   model/revision information. A bounded, editable sample invokes the existing
   local WAV endpoint **only after the user clicks Preview**. Stop, source
   change, unmount, and abort retire the exact preview session.
4. Save still requires both the authenticated write receipt and a matching
   backend readback. The UI never claims a persisted voice solely from
   plugin enablement or an HTTP write acknowledgement.
5. Copilot retains its existing opt-in per-message Read aloud, voice dock,
   global Stop, and explicit microphone controls. No autoplay or inferred
   voice-cloning/streaming capability is introduced.

**Readiness is independent of installation status.** An enabled Pocket plugin
can have zero authorized selectable voices when the pinned model, accepted
license, first-party voice assets, dependency or tenant-scoped installation
evidence is missing. The Voice Studio must show **No Local TTS Plugin Ready**
with the existing administrator installation path in **Models & Runtime →
Model Downloads**, not synthesize test audio through an unverified engine.

Tests: `tests/extensions/test_extension_manifest_metadata_contract.py`,
`src/ui_launchers/Karen-AI-Theme/tests/plugin-host/plugin-registry.test.tsx`,
`src/ui_launchers/Karen-AI-Theme/tests/plugins/plugin-overview-page.test.tsx`
and `src/ui_launchers/Karen-AI-Theme/tests/settings/local-voice-engine-settings.test.tsx`.

Source CI validates contracts and UI behavior with controlled browser audio
stubs. Actual signed-in browser playback, native Pocket CPU inference, licensed
model installation, latency and accessibility on target devices remain separate
release gates, never implied by a frontend success badge.


### Plugin Store path to Voice Studio (2026-11-16)

The **Plugin Store → installed TTS plugin → Manage** flow now exposes
**Open Voice Studio** even when the plugin has no generic settings schema.
The button is conditionally passed from the Plugin Store only when its
authenticated extension registry confirms the selected installed plugin
declares the versioned TTS capability. Neither the plugin's name, tags,
marketplace description nor a successful install can assert runtime readiness.

The Store navigates through the single host deep link,
`/dashboard?view=settings&section=voice`, and Dashboard resolves it into
the existing **Assistant → Voice** panel. It does not mount a separate
voice settings implementation, infer provider selections from the URL, or
call the extension executor directly. Unavailable/failed extension catalog
reads fail closed and hide the shortcut, without preventing ordinary
plugin details or lifecycle controls.

Source proof:
- `tests/plugins/plugin-details-settings.test.tsx` confirms the host
  action coexists with generic plugin settings only when supplied.
- `tests/plugins/plugin-store-voice-studio.test.tsx` verifies installed
  TTS identity, catalog outages, uninstalled and non-TTS cases, and actual
  navigation to the authenticated existing settings route.
- `tests/plugins/voice-studio-navigation.test.ts` verifies the canonical
  route and rejects ambiguous or unrelated navigation parameters.

Browser/device acceptance remains separate from source-level checks.


### Governed model download inside plugin management (2026-11-16)

Pocket TTS and other backend-declared TTS plugins now provide an optional
**Download recommended model** panel from both **Plugins & Tools** and
**Plugin Store → Manage**. There is no plugin-provided frontend package or
plugin-specific downloader: the host renders
`PluginRecommendedModels.tsx`, lazily on operator request.

The model requirement is discovered by matching the selected plugin ID to
the curated `app_consumers` list returned from Karen's existing
`GET /api/models/download/recommendations`. In particular,
`pocket-tts` resolves to the pinned `kyutai/pocket-tts` model from
`config_assets/model_download_recommendations.json`. A test compares that
curated record with the plugin's reviewed `model_spec.json` so the
revision, channel, license and minimum required assets cannot silently drift.

The model setup panel:

1. Requires an administrator or super administrator in the presentation
   layer; the existing admin-scoped model-management router remains the
   actual permission enforcement.
2. Reads canonical recommendation, policy, channel and **owner-scoped**
   durable job state using `/api/runtime/model-library/my-downloads`.
   Failed or malformed reads disable the install control instead of
   inventing a missing model or a healthy download worker. The panel never
   displays arbitrary admin-global job history or other tenants' jobs.
3. Explains the pinned model ID, revision, missing/registered state and
   current download jobs. Pinned plugin recommendations qualify their
   **installed** label against the authenticated tenant's completed, licensed,
   safe-code download receipt and the local snapshot directory, not another
   tenant's registry entry. This still does **not** prove optional
   `pocket-tts` Python dependency, successful inference load or available voice.
4. Demands an explicit per-revision acceptance of the verified source's
   license and gated-access terms, with a model-source link. It rejects
   mutable/unverified revisions, unavailable access terms, disallowed
   channels, blocked policy and duplicate active jobs.
5. Calls existing `POST /api/models/download/validate` and checks the
   returned model ID, channel, authorization and exact immutable resolved
   revision **before** using `POST /api/models/download`. Requests retain
   the curated include-patterns, `validated_revision`, `pin: true`,
   `trust_remote_code: false`, and explicit license acknowledgement.
6. Displays the canonical job receipt/progress, without assuming queued
   means installed or completed means usable. Readiness and voice previews
   remain exclusively verified through VoiceRuntime / Voice Studio.

Plugin authors **must not** implement download helpers inside the plugin
process, accept raw model file paths, or call Hugging Face directly to
bypass credential, license, tenant, resource, policy or lifecycle controls.
The optional native dependency is still installed by an operator and
remains distinct from approved model weight installation.

**Audio channel policy compatibility:** The canonical `plugin_audio`
channel has `admin_only: false` by default. This is **not** an install
prohibition: the existing authenticated model-management endpoints enforce
administrator role requirements, while `effective_enabled`, download policy,
revision/license validation and tenant scope govern a permitted install.
The host UX must never require `channel.admin_only === true` to enable an
administrator's download button. Regression tests use the real backend channel
shape and separately deny a disabled audio channel. This correction removes
an incorrect client-only block, not backend RBAC enforcement.

Acceptance evidence includes
`tests/plugins/plugin-recommended-models.test.tsx`,
`tests/plugins/plugin-details-settings.test.tsx`, and
`tests/extensions/test_pocket_tts_recommendation_contract.py`, and
`tests/core/model_runtime/test_plugin_model_recommendation_tenant_truth.py`.
Real licensed-account, model download, tenant-specific readiness and CPU
synthesis remain hardware/operator acceptance requirements, not UI claims.
