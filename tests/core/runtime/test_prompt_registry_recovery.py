from __future__ import annotations

import json

from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry


def test_prompt_registry_migrates_legacy_versions_and_quarantines_invalid_records(tmp_path) -> None:
    registry_path = tmp_path / "registry"
    registry_path.mkdir()
    (registry_path / "registry.json").write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "prompt_id": "legacy.prompt",
                        "version": "v1",
                        "name": "Legacy prompt",
                        "description": "Legacy persisted prompt",
                        "system_instructions": "legacy",
                        "token_budget": 1024,
                        "is_default": True,
                    },
                    {
                        "prompt_id": "valid.prompt",
                        "version": "v2.3.4",
                        "name": "Valid prompt",
                        "description": "Strict semantic version",
                        "token_budget": 1024,
                    },
                    {
                        "prompt_id": "broken.prompt",
                        "version": "banana",
                        "name": "Broken prompt",
                        "description": "Must not take down the registry",
                        "token_budget": 1024,
                    },
                ],
                "active_versions": {
                    "legacy.prompt": "v1",
                    "valid.prompt": "v2.3.4",
                    "broken.prompt": "banana",
                },
            }
        ),
        encoding="utf-8",
    )

    registry = PromptRegistry(registry_path=registry_path)

    legacy = registry.get_prompt("legacy.prompt")
    assert legacy.version == "v1.0.0"
    assert registry.get_prompt("legacy.prompt", "v1.0.0") is legacy

    valid = registry.get_prompt("valid.prompt", "v2.3.4")
    assert valid.prompt_id == "valid.prompt"

    assert registry.list_versions("broken.prompt") == []

    # A stale persisted record must never prevent the canonical chat prompt
    # from being restored and resolved on first runtime use.
    builtin = registry.get_prompt("karen.chat.default", "v1.0.0")
    assert builtin.prompt_id == "karen.chat.default"


def test_prompt_registry_migrates_two_part_legacy_version(tmp_path) -> None:
    registry_path = tmp_path / "registry"
    registry_path.mkdir()
    (registry_path / "registry.json").write_text(
        json.dumps(
            {
                "prompts": [
                    {
                        "prompt_id": "legacy.minor",
                        "version": "1.7",
                        "name": "Legacy minor",
                        "token_budget": 1024,
                    }
                ],
                "active_versions": {"legacy.minor": "1.7"},
            }
        ),
        encoding="utf-8",
    )

    registry = PromptRegistry(registry_path=registry_path)

    prompt = registry.get_prompt("legacy.minor")
    assert prompt.version == "v1.7.0"
    assert registry.get_prompt("legacy.minor", "v1.7.0") is prompt
