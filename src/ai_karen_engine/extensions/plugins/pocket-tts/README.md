# Pocket TTS: first-party local synthesis plugin

**State:** Built-in source implementation; **disabled by default**. No model
is downloaded, licensed or approved by installing this package. No synthetic
voice is shown until an authorized runtime has actually loaded the model.

**Upstream:** Kyutai [Pocket TTS v4.0.1](https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.1).
Runtime dependency: optional \`pocket-tts==4.0.1\` installed in the host's
trusted environment; no new mandatory heavy Torch dependency at first boot.
Model and weights licenses differ from package code; operators must separately
accept the gated Hugging Face model terms and verify approved speaker states.

## Installation and operation

1. Use the opt-in trusted CPU API image profile `API_BUILD_TARGET=runtime-pocket-tts`
   when building Karen's existing Docker Compose service. This inherits Karen's
   verified CPU PyTorch image and installs `pocket-tts==4.0.1` from
   `requirements/pocket-tts.txt`, followed by `pip check` and a real import
   check. The default `runtime` image remains unchanged. On a bare-metal host,
   install the same pinned requirements using your approved deployment process.
   No plugin request may run pip or download its own runtime.
2. Use Karen's **existing** Model Downloads flow to install
   \`kyutai/pocket-tts\` at the pinned revision in \`model_spec.json\` using
   channel \`plugin_audio\`. The model is gated and may require Hugging Face
   enrollment before an operator can download it. Do not bypass that gate.
3. Verify that the installed snapshot includes
   \`languages/english_18m_refl_2026-10/model.safetensors\`,
   \`tokenizer.model\`, and approved precomputed \`embeddings/*.safetensors\`.
4. An authorized plugin administrator explicitly enables \`pocket-tts\`
   through Plugin Store. The plugin's default state is disabled.
5. Call the authenticated \`GET /api/voice/engines\` catalog. It will
   report the plugin as selectable **only after real local load succeeds**.
6. \`POST /api/voice/engines/pocket-tts/synthesis\` accepts a JSON body with
   \`voice_id\` from the verified catalog and bounded \`text\`. The engine
   is selected by the authenticated route path, not a JSON parameter. The
   request passes canonical PluginService, RuntimePolicy, Kernel, RBAC and
   tenant readiness before the plugin runs.

## First-class consumer interface

The authenticated application sidebar now contains **Plugins → Pocket TTS**,
with a standalone workspace for model installation, verified voices, preview,
Stop and the user's persisted Read aloud preference. The Pocket workspace
reuses `PluginRecommendedModels` and `LocalVoiceEngineSettings` owned by
Karen's host. This is a **host-provided presentation**, not an independently
installable frontend bundle, and the plugin manifest correctly retains
`provides_ui: false`.

Ordinary authenticated users can select and preview authorized installed
voices. Only a permitted administrator can accept gated model terms and queue
a licensed download through the existing worker. A failed download is visible
with redacted recovery guidance, not silently retried or treated as ready.
Engine readiness must be verified by `GET /api/voice/engines` after the
worker's completed installation; actual sample synthesis and playback
establish the next level of readiness. If Pocket is missing, no browser or
alternate-engine fallback is substituted inside its workspace.

**Target deployment still needs independent operator proof:** approved gated
model access, the actual completed model job, native CPU import/load, a
non-silent authentic WAV and audible browser playback. Source CI and build
configuration alone cannot certify this.

## Security and behavior

No remote config, downloaded conditioning audio, custom reference upload,
arbitrary file path, dynamic plugin import, voice-clone enrollment, external
TTS fallback, automatic cloud provider, or second voice/orchestration server.
All audio is returned in bounded PCM16 WAV and must not be persisted by the
plugin. Voice IDs are **precomputed local state basenames** only; users cannot
supply paths. Model assets are resolved only from completed, tenant-eligible
durable model-download jobs and remain under the canonical model root.
Configurations used by the Pocket runtime are generated into a temporary
local YAML with trusted paths. No HTTP requests from inference.

\`catalog\` uses the canonical plugin execution gate, not a direct loader
shortcut. An unavailable installation, denied user, missing dependency or
failed load must not present \`ready\`.

## Scope

This first slice reuses the complete-WAV transport. **Incremental streaming,
cloning, multilingual models, native binary
distribution and local CPU browser acceptance are not yet implemented.**
Do not advertise them as ready.

See [Plugin Developer Wiki](../../../../../docs/plugins/README.md) and
[Voice Modality Guide](../../../../../docs/plugins/08-voice-and-modalities.md).
