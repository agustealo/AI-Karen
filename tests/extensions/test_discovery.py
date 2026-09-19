"""Tests for the single plugin discovery and projection authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.contracts import (
    ExtensionExecutionContext,
    ExtensionExecutionRequest,
    ExtensionLifecycleState,
    TenantScope,
    TrustTier,
)
from ai_karen_engine.extensions.plugin_kernel import PluginKernel


def _write_plugin(
    root: Path,
    *,
    default_enabled: bool = True,
    roles: list[str] | None = None,
    permissions: dict[str, Any] | None = None,
    dependencies: dict[str, Any] | None = None,
) -> None:
    plugin_dir = root / "echo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin_manifest.json").write_text(
        json.dumps(
            {
                "name": "echo",
                "version": "1.0.0",
                "display_name": "Echo",
                "description": "Echo plugin used to prove canonical discovery.",
                "author": "Kari",
                "license": "MIT",
                "category": "test",
                "entrypoint": "handler:MainExtension",
                "capabilities": {
                    "provides_ui": False,
                    "provides_api": True,
                    "prompt_first": True,
                },
                "rbac": {
                    "allowed_roles": roles or ["user"],
                    "default_enabled": default_enabled,
                },
                "permissions": permissions or {},
                "dependencies": dependencies or {},
                "config_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additional_properties": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "handler.py").write_text(
        "class MainExtension:\n    pass\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_plugin_kernel_uses_platform_catalog_as_discovery_truth(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    kernel = PluginKernel(tmp_path)

    count = await kernel.refresh()

    assert count == 1
    record = kernel.get_record("echo")
    assert record is not None
    assert record["manifest"].name == "echo"
    assert record["manifest"].display_name == "Echo"
    assert record["status"] == ExtensionLifecycleState.ENABLED.value

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.manifest.id == "echo"
    assert registration.manifest.tenant_scope is TenantScope.SINGLE
    assert [cap.id for cap in registration.manifest.capabilities] == ["execute"]
    assert registration.manifest.input_schema["required"] == ["message"]


@pytest.mark.asyncio
async def test_custom_plugin_root_is_not_promoted_to_first_party_trust(tmp_path: Path) -> None:
    _write_plugin(tmp_path)
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.manifest.trust_tier is TrustTier.UNTRUSTED


@pytest.mark.asyncio
async def test_manifest_default_disabled_projects_to_disabled_runtime_state(tmp_path: Path) -> None:
    _write_plugin(tmp_path, default_enabled=False)
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    assert registration.state is ExtensionLifecycleState.DISABLED


@pytest.mark.asyncio
async def test_catalog_permission_families_survive_runtime_projection(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        permissions={
            "memory_read": True,
            "tools": ["clock"],
            "data_access": ["read"],
            "plugin_access": ["execute"],
            "system_access": ["metrics"],
            "network_access": ["outbound_https"],
        },
    )
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    registration = kernel.runtime_registry.get("echo")
    assert registration is not None
    required = set(registration.manifest.required_permissions)
    assert {
        "memory_read",
        "tool_access",
        "tool_access:clock",
        "data_access",
        "data_access:read",
        "plugin_access",
        "plugin_access:execute",
        "system_access",
        "system_access:metrics",
        "network_access",
        "network_access:outbound_https",
    }.issubset(required)


@pytest.mark.asyncio
async def test_missing_extension_dependency_never_reaches_runtime_registry(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        dependencies={"plugins": ["missing-plugin"]},
    )
    kernel = PluginKernel(tmp_path)

    await kernel.refresh()

    assert kernel.runtime_registry.get("echo") is None
    record = kernel.get_record("echo")
    assert record is not None
    assert record["status"] == "error"
    assert record["dependencies_resolved"] is False
    assert "Missing extension dependencies: missing-plugin" in str(
        record["error_message"]
    )


@pytest.mark.asyncio
async def test_denied_request_does_not_import_or_initialize_plugin_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_plugin(tmp_path, roles=["admin"])
    kernel = PluginKernel(tmp_path)
    await kernel.refresh()

    load_calls: list[str] = []

    def forbidden_load(plugin_id: str) -> Any:
        load_calls.append(plugin_id)
        raise AssertionError("plugin code loaded before authorization completed")

    monkeypatch.setattr(kernel.loader, "load_extension", forbidden_load)
    plan = AuthorizedExecutionPlan(
        execution_id="execution-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id="tenant-1",
        authorized_session_id="session-1",
        allowed_plugins=["echo"],
    )
    context = ExtensionExecutionContext(
        request_id="request-1",
        correlation_id="correlation-1",
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        policy_decision_id="policy-1",
        audit_context={"user_roles": ["user"]},
    )

    result = await kernel.execute(
        ExtensionExecutionRequest(
            plugin_id="echo",
            capability=PluginKernel.EXECUTE_CAPABILITY,
            payload={"message": "hello"},
            context=context,
            authorized_plan=plan,
        )
    )

    assert result.status == "failed"
    assert result.error_code == "rbac_denied"
    assert load_calls == []


def test_duplicate_top_level_discovery_and_manifest_loaders_are_retired() -> None:
    root = Path(__file__).parents[2] / "src" / "ai_karen_engine" / "extensions"
    assert not (root / "discovery.py").exists()
    assert not (root / "manifest.py").exists()
