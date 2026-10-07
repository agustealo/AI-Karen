from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.runtime.prompt.prompt_contract import (
    PromptDefinition,
    PromptLifecycleStatus,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry


def _prompt(version: str, instructions: str, *, default: bool = False) -> PromptDefinition:
    return PromptDefinition(
        prompt_id="test.prompt",
        version=version,
        name="Test prompt",
        system_instructions=instructions,
        status=PromptLifecycleStatus.ACTIVE,
        is_default=default,
    )


def test_prompt_registry_keeps_versions_distinct(tmp_path: Path) -> None:
    registry = PromptRegistry(tmp_path)
    registry.register_prompt(_prompt("v1.0.0", "one", default=True))
    registry.register_prompt(_prompt("v1.1.0", "two"))

    assert registry.get_prompt("test.prompt", "v1.0.0").system_instructions == "one"
    assert registry.get_prompt("test.prompt", "v1.1.0").system_instructions == "two"
    assert registry.get_prompt("test.prompt").version == "v1.0.0"


def test_prompt_registry_active_version_switch_is_durable(tmp_path: Path) -> None:
    registry = PromptRegistry(tmp_path)
    registry.register_prompt(_prompt("v1.0.0", "one", default=True))
    registry.register_prompt(_prompt("v1.1.0", "two"))
    registry.set_active_version("test.prompt", "v1.1.0")

    reloaded = PromptRegistry(tmp_path)

    assert reloaded.get_prompt("test.prompt").version == "v1.1.0"
    assert reloaded.get_prompt("test.prompt", "v1.0.0").is_default is False
    assert reloaded.get_prompt("test.prompt", "v1.1.0").is_default is True


def test_prompt_registry_retires_only_requested_version(tmp_path: Path) -> None:
    registry = PromptRegistry(tmp_path)
    registry.register_prompt(_prompt("v1.0.0", "one", default=True))
    registry.register_prompt(_prompt("v1.1.0", "two"))
    registry.retire_prompt("test.prompt", "v1.0.0")

    assert registry.get_prompt("test.prompt").version == "v1.1.0"
    assert registry.list_versions("test.prompt") == [
        registry.get_prompt("test.prompt", "v1.1.0").parsed_version
    ]
