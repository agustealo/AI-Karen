# Karen AI Plugin Development Guide

This guide provides everything you need to know to build, register, and deploy plugins for the Karen AI Extension System.

## 1. Plugin Architecture

Plugins in Karen AI consist of three main components:
1.  **Backend Handler**: Python code that implements the logic (located in `src/ai_karen_engine/extensions/plugins/{plugin-id}/handler.py`).
2.  **Frontend UI**: React components for the admin interface (located in `src/ai_karen_engine/extensions/plugins/{plugin-id}/ui/`).
3.  **Manifests**: Metadata files defining the plugin's identity, requirements, and UI entry points.

## 2. Manifest Requirements

Every plugin **must** have two manifest files at its root:

### `plugin_manifest.json` (Backend/System Manifest)
Used by the discovery service to register the plugin in the database.

```json
{
  "id": "my-plugin",
  "name": "my-plugin",
  "display_name": "My Great Plugin",
  "version": "1.0.0",
  "entrypoint": "handler:MainExtension",
  "category": "productivity",
  "author": "Your Name",
  "license": "MIT",
  "capabilities": {
    "provides_ui": true,
    "provides_api": true,
    "prompt_first": true
  },
  "rbac": {
    "allowed_roles": ["admin", "developer"],
    "default_enabled": true
  }
}
```

### `manifest.json` (Frontend/GUI Manifest)
Used by the UI Materialization Pipeline to generate the frontend import map.

```json
{
  "id": "my-plugin",
  "plugin_id": "my-plugin",
  "gui_manifest_version": "1.0",
  "entry": {
    "id": "my-plugin-main",
    "default": true,
    "entry_file": "MyPluginPage.tsx"
  }
}
```

## 3. Frontend Development

- Store your UI code in the `ui/` subdirectory of your plugin.
- The `entry_file` specified in `manifest.json` must export a default React component.
- The UI Materialization Pipeline will automatically sync these files to `src/ui_launchers/Karen-AI-Theme/src/plugin_repo/` during installation.

## 4. Database & Persistence

### Storing Plugin Data
Plugins can store specific data using several mechanisms:
1.  **Extension Config**: Use the `/api/extensions/{id}/config` endpoint to store key-value settings.
2.  **JSONB Columns**: The `extension_registry` table includes `capabilities`, `resources`, and `ui_config` JSONB columns for plugin-specific metadata.

### Automatic Table Creation
The system automatically manages the `extension_registry` and related tables. If you need custom tables for your plugin, implement a migration script in your plugin directory.

## 5. Installation & Registration Process

1.  **Discovery**: The system scans `src/ai_karen_engine/extensions/plugins/` for folders containing `plugin_manifest.json`.
2.  **Validation**: `ManifestStandardsEnforcer` ensures all required fields (`id`, `entrypoint`, etc.) are present.
3.  **Database Sync**: Discovered plugins are added to the `extension_registry` table with an `inactive` status.
4.  **UI Materialization**:
    - Files are copied to the `plugin_repo`.
    - `src/ui_launchers/Karen-AI-Theme/src/plugin-import-map.generated.ts` is updated.
5.  **Enabling**: Once registered and materialized, a plugin can be enabled via the Admin UI, which triggers the backend `handler`.

## 6. Best Practices

- **Naming**: Use kebab-case for `id` (e.g., `web-search`) and CamelCase for UI components (e.g., `WebSearchPage.tsx`).
- **Entrypoints**: Ensure your `handler.py` contains a `MainExtension` class.
- **Cleanup**: Always provide a mechanism to clean up plugin-specific data if the plugin is uninstalled.


## 7. Current execution trust and isolation boundary

The manually uploaded ZIP package path is **local installation only** until a
verified isolated execution worker is implemented. The canonical
`/api/store/upload` endpoint validates a ZIP, installs it with a durable disabled
marker, and records `.karen-upload-origin` as untrusted package provenance.
Uploading a package **does not** authorize execution or convert it into a
first-party extension, even though it shares the installed-plugin directory.

The current canonical extension executor runs Python handlers in-process.
Only explicitly first-party/built-in code is eligible for that execution mode.
For user uploads, third-party signed packages, remote plugins, or manifests
requesting unsupported subprocess/container/WASM modes, execution fails with
`isolation_unavailable` before loading the handler. An attempt to enable a
manually uploaded plugin is rejected until a verified isolation runtime exists.
The `SANDBOX` compatibility argument on `PluginService` does not provide an
operating-system security boundary.

Do not remove the upload-origin marker, modify the executor's trust decision,
or treat a role grant as permission to execute untrusted Python in the
application process. First-party eligibility is an operator-controlled source
provenance decision, not a value accepted from an uploaded plugin manifest.

**Migration limitation:** Older manually installed packages that predate the
origin marker require a separate operator provenance audit. Merely finding a
package under the built-in directory is not proof that it was shipped as a
built-in. Do not claim historical packages have been reclassified until that
audit is complete.
