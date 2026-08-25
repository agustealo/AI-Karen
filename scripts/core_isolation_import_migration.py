from __future__ import annotations

"""One-shot import-direction migration for CORE-ISO-2.

This script performs exact module-path rewrites only. It does not alter business
logic. The target modules are Core-owned compatibility facades that delegate to
canonical runtime authority. Safe to re-run: replacements are idempotent.
"""

from pathlib import Path

ROOT = Path("src/ai_karen_engine/core")

REPLACEMENTS = {
    "ai_karen_engine.integrations.llm_utils": "ai_karen_engine.core.model_runtime.llm_adapter",
    "ai_karen_engine.integrations.llm_registry": "ai_karen_engine.core.model_runtime.runtime_registry_adapter",
    "ai_karen_engine.integrations.registry": "ai_karen_engine.core.model_runtime.model_registry_compat",
    "ai_karen_engine.integrations.providers.openai_compatible_provider": "ai_karen_engine.core.model_runtime.openai_compatible_provider_compat",
    "ai_karen_engine.integrations.providers.openai_provider": "ai_karen_engine.core.model_runtime.openai_compatible_provider_compat",
    "ai_karen_engine.integrations.providers.fallback_provider": "ai_karen_engine.core.model_runtime.unavailable_provider",
    "ai_karen_engine.copilotkit.session_state_manager": "ai_karen_engine.core.runtime.session_state_manager_compat",
}


def main() -> int:
    changed: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in REPLACEMENTS.items():
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path))

    print(f"CORE-ISO-2 import migration changed {len(changed)} file(s)")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
