# 07. Frontend contributions and Settings UX

[Wiki index](README.md) · [Settings and credentials](06-settings-and-credentials.md)

**Status: Implemented UI materialization and generic plugin settings, with
future dynamic modality controls proposed.**

## Existing frontend surfaces

The React/Next.js theme lives in
"src/ui_launchers/Karen-AI-Theme/". The plugin store and host UI components
live in "src/components/plugins/" relative to that app. The host also has
a "plugin_host/" directory for loading, permission guards, component
registration, slots and error boundaries.

A UI-capable plugin supplies a GUI "manifest.json" and React entry file.
The materialization process publishes trusted frontend sources to
"src/ui_launchers/Karen-AI-Theme/src/plugin_repo/" and updates the generated
import map through the governed install path. Do not edit the generated
import map by hand or load arbitrary untrusted JavaScript directly from ZIP
contents.

Relevant sources:

- [UI materialization](../../src/ai_karen_engine/extensions/platform/core/registry/ui_materialization.py)
- [Materialization API](../../src/ai_karen_engine/extensions/platform/api_routes/ui_materialization_routes.py)
- [Plugin host](../../src/ui_launchers/Karen-AI-Theme/src/components/plugins/PluginHost.tsx)
- [Plugin Store](../../src/ui_launchers/Karen-AI-Theme/src/components/plugins/PluginStorePage.tsx)
- [Frontend hook zones](../../src/ui_launchers/Karen-AI-Theme/src/plugin_host/hook-zones.ts)
- [Permission guard](../../src/ui_launchers/Karen-AI-Theme/src/plugin_host/permission-guard.tsx)

## UI trust and ownership

Plugin UI cannot become an alternate API client that decides which providers
are healthy, who has permission, whether a secret was saved, or whether a
side effect succeeded. It must render backend receipts and implement loading,
error, empty, denied and unavailable states. No secret should be included in
frontend import-map metadata, client bundles or telemetry.

The built-in plugin UI hook zones are not permission grants. A backend
capability can be available without any plugin-owned panel, and a panel can
be installed while the engine is disabled.

## Authoring a GUI contribution

For a plugin that needs a page:

1. Use a stable, matching "id" / "plugin_id" in its GUI manifest.
2. Put the React entry inside the plugin's "ui/" directory and export a
   default component.
3. Declare a valid entry file and any supported hook-zone contribution.
4. Keep all API calls routed through the existing authenticated client and
   platform-authorized endpoints.
5. Do not invent a chat window, memory store, provider picker, or independent
   settings persistence to service the plugin.
6. Test production build, UI materialization, isolation of enabled and
   disabled states, permission-denied state and accessibility.

See existing
[Time Query GUI manifest](../../src/ai_karen_engine/extensions/plugins/time-query/manifest.json)
and its [UI components](../../src/ai_karen_engine/extensions/plugins/time-query/ui/)
for an implemented example.

## Generic admin plugin settings

The Plugin Store details dialog already exposes **Configure** when the
backend advertises a writable configuration contract. The existing
"PluginSettingsForm" uses the backend's approved field projection and
revision-fenced save/reset APIs. Secret enrollment and revocation are shown
as separate write-only controls. See
[Settings](06-settings-and-credentials.md).

Do **not** create a bespoke settings database or hidden form just because
the plugin has advanced controls. Extend the shared schema projection and
trusted renderer only when the plugin features genuinely require a new safe
field type.

## Proposed: shared modality Settings UI

The planned Voice settings evolution should use an authenticated,
versioned host-owned capability catalog:

- User selects an installed, enabled, healthy and permitted TTS engine.
- TTS plugin supplies verified voice IDs, language support and safe options.
- A different installed STT plugin may be selected for transcription.
- VoiceRuntime owns transcription/synthesis execution, cancel and streaming.
- Admin enables engines and controls tenant-wide resources/permissions.
- User's personal voice preferences persist through canonical user
  preferences, not the plugin's admin settings or device-only localStorage.

**This dynamic capability catalog is not an implemented API yet.** The
existing [VoiceSettings.tsx](../../src/ui_launchers/Karen-AI-Theme/src/components/settings/VoiceSettings.tsx)
supports browser speech selection. Browser voices may be missing even when a
local engine becomes available; the two statuses must not be conflated.

## Accessibility and browser proof

- Control labels, descriptions, focus order, keyboard operation, screen-reader
  announcements and visible denial/errors.
- Confirm controls at 390, 768, 1024 and 1440 pixels.
- Reload and revisit settings after persisted changes; verify the same
  values were fetched from the backend.
- Exercise switching tenants, roles, plugins and devices.
- Confirm abort/stop actually stops playback and does not restart a message.
- Ensure server-side rendering cannot read browser-only audio APIs.

Frontend regression sources:
[Plugin settings tests](../../src/ui_launchers/Karen-AI-Theme/tests/plugins/plugin-settings-persistence.test.tsx),
[Credential management tests](../../src/ui_launchers/Karen-AI-Theme/tests/plugins/plugin-vault-credential-management.test.tsx),
[Voice settings tests](../../src/ui_launchers/Karen-AI-Theme/tests/settings/voice-settings.test.tsx).
