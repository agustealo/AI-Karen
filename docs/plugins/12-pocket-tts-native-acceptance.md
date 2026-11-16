# Pocket TTS: native and browser consumer acceptance ledger

[Plugin wiki](README.md) · [Voice/modality contract](08-voice-and-modalities.md) ·
[First-party Pocket plugin](../../src/ai_karen_engine/extensions/plugins/pocket-tts/README.md)

> **Status (2026-11-15): source integration merged, native consumer acceptance
> unverified.** This ledger is the auditable release record because the GitHub
> repository does not currently accept new Issues. Do not mark a test complete
> without linking its exact code revision, real runtime log/artifact and observed
> outcome. Source-level mocked WAV tests are not evidence of real audio.

## Milestones and truth table

| Gate | Evidence | State |
| --- | --- | --- |
| Governed plugin source, VoiceRuntime, settings, browser controller | [PR #861](https://github.com/agustealo/AI-Karen/pull/861) | **Merged**, source integration only |
| Recommended model pin and durable worker test | [PR #865](https://github.com/agustealo/AI-Karen/pull/865) | **Under CI / merge review** when ledger opened |
| Target hardware runtime + licensed model install | No attested target artifact | **Not proven** |
| Native Pocket audio and WAV integrity | No non-mocked target WAV | **Not proven** |
| Browser preview/read-aloud on real target | No device/browser capture | **Not proven** |
| CPU/RAM/latency/cancellation measurements | No machine observations | **Not proven** |

**Release policy:** do not advertise Pocket as ready merely because a plugin
manifest validates, a user preference persists, a synthetic WAV test passes, or
CI is green. Streaming, cloning, uploaded engines and cloud fallback remain
out of scope.

## Exact implementation and authority

- Runtime/model version: `pocket-tts==4.0.1`, `kyutai/pocket-tts` at
  `db04f0e653473e5c7333c69686ac92b7460b0c1d`.
- Channel: `plugin_audio`; runtime language:
  `english_18m_refl_2026-10`. Reviewed paths in
  `model_spec.json`: `languages/english_18m_refl_2026-10/model.safetensors`,
  `tokenizer.model` and `embeddings/*.safetensors`.
- Model-download control owns license acceptance, pinned provenance, job
  completion and installed paths. There is no inference-time download.
- PluginKernel and PluginService govern installation, enablement, tenant and
  RBAC admission. VoiceRuntime owns session capacity and engine execution.
  The Pocket plugin owns only model load and synthesis.
- Assistant > Voice persists the user's selected engine and voice through
  authenticated user settings. The browser controls opt-in playback only.
- Voice cloning is disabled and uploaded reference voices are not accepted.

## Operator preflight (record all observations)

1. Identify the *actual* test device: OS/release, CPU, processor architecture,
   usable RAM, Python runtime, container image digest or deployment commit,
   browser version, audio output stack, and installed `pocket-tts` version.
2. Have the operator approve the gated upstream model terms and voice licenses
   as applicable. Never include access tokens or private speaker recordings in
   the acceptance artifact. Model code, model weights and individual voice
   rights require separate verification.
3. Install the model using Karen's existing Model Downloads UI and
   `plugin_audio` channel at the exact revision above. Record a completed,
   license-accepted model job, canonical install root, actual SHA/digest
   evidence and tenant eligibility. Reject stale jobs or paths with symlinks.
4. Install the approved optional CPU dependency in the **trusted host**,
   not by running a plugin-level pip command. An administrator explicitly
   enables `pocket-tts`. Recheck its actual authorized engine catalog.
5. Confirm a missing model, denied license or disabled plugin does **not**
   produce a selectable engine. This negative control must run before
   testing the happy path.

Read-only operator checks from the repo root:

```bash
python -m pip show pocket-tts
python -m compileall -q src/ai_karen_engine/services/voice_runtime.py \
  src/ai_karen_engine/api_routes/voice.py \
  src/ai_karen_engine/extensions/plugins/pocket-tts/handler.py
PYTHONPATH=src pytest -q \
  tests/core/voice/test_pocket_tts_plugin.py \
  tests/core/voice/test_voice_plugin_catalog.py \
  tests/core/voice/test_voice_plugin_http.py \
  tests/api_routes/test_consumer_voice_preferences.py
```

These commands establish source and environment prerequisites, **not**
non-mocked speech or consumer acceptance. Preserve test exit codes and the
exact repository commit in the evidence report.

## Real API and UI acceptance

Use an authenticated test identity with explicit tenant membership. Retrieve
`GET /api/voice/engines` and record the real returned `engine_id`,
`model_revision`, voice IDs and capabilities. If Pocket is not reported ready,
**stop**; do not synthesize by direct plugin import or invent a fallback voice.

For a ready catalog, send a bounded JSON body containing `text` and an
**actual catalog voice ID** to
`POST /api/voice/engines/pocket-tts/synthesis`. Keep credentials out of
terminal history and artifacts. Independently inspect the returned WAV:
`audio/wav`, RIFF/WAVE headers, mono PCM16, nonzero frames, supported
sample rate, valid duration, audible/understandable speech, and absence of
response caching. The server must identify `pocket-tts` as the actual engine.

Then use Assistant > Voice with the same authenticated identity: preview
the selected voice, save it, reload the application, confirm the durable
engine/voice pair, and read a fresh assistant reply aloud. Confirm the saved
plugin actually produced playback. Repeat in supported browsers and at
390, 768, 1024, and 1440px. Do not count browser-speech fallback as Pocket
success. Validate that a browser with zero installed voices can still select
a genuinely ready local plugin.

## Adversarial matrix

| Scenario | Required observation |
| --- | --- |
| Model missing, wrong SHA, license missing, incomplete job | No selectable Pocket engine, no external download |
| Voice state missing, malformed or symlinked | Engine unavailable or rejected voice; no path escape |
| Wrong tenant, anonymous caller, insufficient RBAC | Fail closed before exposing audio/model paths |
| Disabled plugin or revoked execution eligibility | New requests denied and previously saved preference truthfully unavailable |
| Unapproved / invented voice ID | Reject without selecting another voice |
| Text over the synthesis limit or malformed JSON | Bounded validation error, no inference |
| Cross-user playback and cache inspection | No private audio response shared or persisted |
| Concurrent syntheses | Native capacity bounded; busy request rejected correctly |
| Stop button / client disconnect | Browser playback stops; model capacity retained until worker terminates |
| Shutdown during synthesis | In-flight work handled without capacity or state leak |
| Offline inference | Successful non-mocked output without Hugging Face or cloud requests |
| STT, cloning or streaming claims | Not advertised as enabled by this TTS-only slice |

## Required performance evidence

Measure three input lengths (short greeting, paragraph, maximum supported
text) with cold and warm runs. Capture processor utilization, peak resident
memory, end-to-end synthesis latency, audio duration, real-time factor, and
first playable sound in the actual browser. Report sample counts and p50/p95;
do not substitute synthetic/model-mocked measurements. Determine acceptable
budgets from measured supported hardware and document them as **release
criteria**, not unverified aspirational numbers.

Record per experiment: commit SHA, OS/CPU/RAM, Python and Pocket package
versions, model revision and digest, license/voice authorization state,
browser version, run count, cold/warm distinction, wall-clock measurements,
resource peaks, sound-quality verdict, outcome, correlation ID and a link to
sanitized logs/artifacts. Do not log raw user text, audio, secrets or unapproved
reference voices.

## Go/no-go

**GO:** all mandatory matrix rows pass with actual local model and device
evidence; voice preference survives session reload; owner-approved audio
is correctly played; license and privacy requirements are satisfied;
measured performance is within the documented hardware support budget.

**NO-GO:** missing real weights, incomplete license consent, a CI-only WAV
test, unexplained offline network access, silent browser/cloud fallback,
tenant/RBAC bypass, private-audio persistence, corrupted playback, or an
unreproducible performance result.

When acceptance is complete, replace each **Not proven** cell with an
evidence link and exact verified result. Update the voice modality chapter
and release notes in the same pull request. Preserve the original unverified
state here as the historical checkpoint, not a fabricated success claim.
