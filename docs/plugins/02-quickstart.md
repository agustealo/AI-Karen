# 02. Quickstart: complete deterministic plugin

[Wiki index](README.md) · [Manifest reference](03-manifests-and-prompts.md)

**Status: Developer example, not a preinstalled plugin.** This reference
illustrates the shape of a **first-party reviewed** local plugin. It does not
authorize execution of an uploaded package.

## Prerequisites

Work from the repository checkout with the project Python environment
installed. Review the [architecture](01-architecture.md) and
[trust rules](04-lifecycle-and-trust.md). A new built-in plugin is added and
reviewed in source control; manually uploaded third-party ZIPs remain
execution-quarantined until a verified isolation worker exists.

The canonical built-in directory is:

~~~text
src/ai_karen_engine/extensions/plugins/
    text-statistics/
        __init__.py
        plugin_manifest.json
        handler.py
~~~

A GUI manifest is needed for a frontend contribution, not for this backend-only
example. The example exposes a single pure text transformation and requires
no network, database, credential, migration, custom prompt or alternate API
route.

## plugin_manifest.json (full file)

~~~json
{
  "id": "text-statistics",
  "name": "text-statistics",
  "version": "1.0.0",
  "display_name": "Text Statistics",
  "description": "Local character, word and line counts for explicitly supplied text.",
  "purpose": "Analyze supplied text deterministically without network access.",
  "author": "KAREN Engineering",
  "license": "MIT",
  "category": "productivity",
  "entrypoint": "handler:MainExtension",
  "tags": ["local", "text", "deterministic"],
  "capabilities": {
    "provides_ui": false,
    "provides_api": false,
    "prompt_first": true
  },
  "prompt_files": {
    "prompt_first": true,
    "mode": "none"
  },
  "execution_input_schema": {
    "type": "object",
    "properties": {
      "text": {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000
      }
    },
    "required": ["text"],
    "additional_properties": false
  },
  "permissions": {
    "memory_read": false,
    "memory_write": false,
    "user_data_read": false,
    "user_data_write": false,
    "network_access": []
  },
  "rbac": {
    "allowed_roles": ["user", "admin", "developer"],
    "default_enabled": false
  }
}
~~~

This is a request for a capability, not a global grant. "mode: none" is
appropriate because the operation is deterministic. For an AI-backed plugin,
use an existing versioned PromptRegistry contract; see the manifest chapter.

## handler.py (full file)

~~~python
"""First-party local text-statistics plugin reference implementation."""

from __future__ import annotations

from typing import Any

from ai_karen_engine.extensions.platform.core.host.base import (
    ExtensionBase,
    ExtensionContext,
    HookContext,
    HookPoint,
)


class MainExtension(ExtensionBase):
    """Deterministic text statistics, without external side effects."""

    def __init__(self, manifest: Any, context: ExtensionContext) -> None:
        super().__init__(manifest, context)
        self._ready = False

    async def initialize(self) -> None:
        self._ready = True

    async def shutdown(self) -> None:
        self._ready = False

    def get_status(self) -> dict[str, Any]:
        return {
            "status": "ready" if self._ready else "unavailable",
            "initialized": self._ready,
            "version": self.manifest.version,
        }

    async def execute_hook(
        self,
        hook_point: HookPoint,
        context: HookContext,
    ) -> dict[str, Any]:
        if not self.supports_hook_point(hook_point):
            raise ValueError("unsupported_hook_point")
        return await self.run(dict(context.data))

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self._ready:
            raise RuntimeError("plugin_not_ready")
        if set(params) != {"text"}:
            raise ValueError("invalid_input_fields")
        content = params["text"]
        if not isinstance(content, str) or not 0 < len(content) <= 2000:
            raise ValueError("invalid_text")
        return {
            "character_count": len(content),
            "word_count": len(content.split()),
            "line_count": len(content.splitlines()),
        }
~~~

## __init__.py (full file)

~~~python
"""Built-in text-statistics extension reference."""
~~~

## Verify the manifest

From the repository root, with dependencies installed:

~~~bash
python - <<'PY'
import json
from pathlib import Path

from ai_karen_engine.extensions.platform.core.manifest import ExtensionManifest
from ai_karen_engine.extensions.platform.core.registry.validator import ExtensionValidator

path = Path("src/ai_karen_engine/extensions/plugins/text-statistics/plugin_manifest.json")
raw = json.loads(path.read_text(encoding="utf-8"))
manifest = ExtensionManifest.from_dict(raw)
valid, errors, warnings = ExtensionValidator().validate_manifest(manifest)
assert valid, errors
assert manifest.execution_input_schema is not None
print({"name": manifest.name, "valid": valid, "warnings": warnings})
PY
~~~

Do not run this against an unreviewed uploaded plugin as a substitute for
host-provenance checks. A successful validation proves schema compatibility,
not execution permission or production readiness.

## Add tests before enabling

Exercise correct counts, Unicode, empty/oversized requests, unknown keys,
unready state and unexpected input types. Test the real
PluginService/PluginKernel execution gate for disabled state, tenant/RBAC
denials and audit. **Never** mark the plugin ready because its handler can be
called directly in a unit test.

## Next steps

For plugin-specific nonsecret admin configuration add a bounded
"config_schema" and obey the separate action-input rules
([Settings](06-settings-and-credentials.md)). For frontend contributions read
[UI integration](07-frontend-integration.md). For AI-dependent actions
register a versioned prompt contract rather than constructing prompts in the
handler.
