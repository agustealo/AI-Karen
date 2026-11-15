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

- Shows independently verified `/api/voice/capabilities` listening readiness
  and the authorized `/api/voice/engines` speaking catalog. Neither
  advertises an uninstalled model.
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
