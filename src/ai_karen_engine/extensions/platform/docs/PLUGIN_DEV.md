# HISTORICAL: pre-consolidation plugin guide

> **Do not use this page to implement new plugins.** Its root paths, handler
> conventions, generic prompt.txt and implicit prompt injection are obsolete.
> The current authoritative developer wiki is
> [docs/plugins/README.md](../../../../../docs/plugins/README.md), based on
> the canonical ExtensionManifest, PluginKernel and governed execution owner.
> This file is retained only for archive/reference purposes.

---

# Plugin Development Guide: Prompt-First Modular Architecture

This guide explains how to build and package plugins for the AI Karen Unified Modular Platform.

## ⚖️ The Governing Law: Prompt-First
All modular units in AI Karen are governed by the **Prompt-First Law**. This means:
1. Every plugin MUST define an **Intent** (the "why" the AI should use it).
2. Every plugin MUST define an **Input Schema** (OpenAPI format).
3. Every plugin's primary interface is its **Prompt Contract** (`prompt.txt`), not just its code.

---

## 📁 Plugin Package Structure
A plugin is a directory containing:

```text
my-plugin/
├── plugin_manifest.json  # Required: Metadata & Capabilities
├── prompt.txt            # Required: The AI Contract (Jinja2 supported)
├── handler.py            # Optional: Python logic adapter
├── ui/                   # Optional: Static UI assets (HTML/JS)
├── api/                  # Optional: Backend routes
└── tasks/                # Optional: Scheduled background logic
```

## 📄 The Manifest (`plugin_manifest.json`)
The manifest is the source of truth for the Plugin Registry.

```json
{
  "name": "weather-plugin",
  "version": "1.0.0",
  "intent": "get_weather_info",
  "parameters": {
    "type": "object",
    "properties": {
      "location": { "type": "string" },
      "units": { "type": "string", "enum": ["c", "f"] }
    },
    "required": ["location"]
  },
  "capabilities": {
    "provides_ui": true,
    "provides_mcp": true
  }
}
```

## 📝 The Prompt Contract (`prompt.txt`)
The `prompt.txt` file is rendered by the runtime and injected into the LLM's context. It tells the AI *exactly* how to use your plugin. You can use Jinja2 variables based on the manifest.

```markdown
# Plugin: {{ display_name }}
Use this plugin to get weather data for any location.
Parameters:
- location: The city name.
- units: "c" for Celsius or "f" for Fahrenheit.
```

## ⚙️ The Handler (`handler.py`)
The handler is a Python script with an `async def handle` function. This is where the actual work happens.

```python
async def handle(params, context=None):
    location = params.get("location")
    # ... call weather API ...
    return {"status": "success", "temp": 22, "condition": "Sunny"}
```

## 🚀 Registration
Plugins placed in `src/extensions/plugins/` (User) or `src/extensions/sys_extensions/` (System) are automatically discovered and validated by the `PluginRegistry` on startup.

---
*For runtime details, see the [Platform Overview](../README.md).*
