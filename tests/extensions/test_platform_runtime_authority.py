"""Regression proofs for retiring duplicate platform execution authorities."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.extensions.platform.core.host import manager as host_manager_module
from ai_karen_engine.extensions.platform.core.host import router as host_router_module
from ai_karen_engine.extensions.platform.core.integration import manager as integration_module
from ai_karen_engine.services.plugin_service import ExecutionStatus


class _CanonicalService:
    def __init__(self) -> None:
        self.initialized = True
        self.calls: list[dict[str, Any]] = []
        self.enabled: list[str] = []
        self.disabled: list[str] = []

    async def execute_plugin(self, plugin_name: str, **kwargs: Any) -> Any:
        self.calls.append({"plugin_name": plugin_name, **kwargs})
        return SimpleNamespace(
            status=ExecutionStatus.COMPLETED,
            result={"ok": True},
            error=None,
            error_code=None,
        )

    async def discover_plugins(self, force_refresh: bool = False) -> dict[str, Any]:
        self.calls.append({"discover": True, "force_refresh": force_refresh})
        return {"echo": {"status": "enabled"}}

    async def get_plugin_info(self, plugin_name: str) -> dict[str, Any] | None:
        return {"name": plugin_name, "status": "enabled"}

    async def enable_plugin(self, plugin_name: str) -> bool:
        self.enabled.append(plugin_name)
        return True

    async def disable_plugin(self, plugin_name: str) -> bool:
        self.disabled.append(plugin_name)
        return True

    async def refresh_plugins(self) -> int:
        return 1


@pytest.mark.asyncio
async def test_platform_integration_delegates_execution_identity_to_plugin_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _CanonicalService()
    monkeypatch.setattr(integration_module, "get_plugin_service", lambda: service)
    manager = integration_module.PluginManager()

    result = await manager.run_plugin(
        "echo",
        {"message": "hello"},
        {
            "user_id": "user-1",
            "tenant_id": "tenant-a",
            "session_id": "session-1",
            "conversation_id": "conversation-1",
            "correlation_id": "correlation-1",
            "roles": ["user"],
            "permissions": ["read"],
        },
    )

    assert result == {"ok": True}
    assert service.calls == [
        {
            "plugin_name": "echo",
            "parameters": {"message": "hello"},
            "user_id": "user-1",
            "tenant_id": "tenant-a",
            "session_id": "session-1",
            "conversation_id": "conversation-1",
            "correlation_id": "correlation-1",
            "roles": ["user"],
            "permissions": ["read"],
            "policy_decision_id": None,
            "authorized_plan": None,
            "allowed_capabilities": [],
            "forbidden_capabilities": [],
        }
    ]


@pytest.mark.asyncio
async def test_host_manager_load_unload_are_canonical_enable_disable_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _CanonicalService()
    monkeypatch.setattr(host_manager_module, "get_plugin_service", lambda: service)
    manager = host_manager_module.ExtensionManager()

    record = await manager.load_extension("echo")
    disabled = await manager.unload_extension("echo")

    assert record == {"name": "echo", "status": "enabled"}
    assert disabled is True
    assert service.enabled == ["echo"]
    assert service.disabled == ["echo"]


@pytest.mark.asyncio
async def test_legacy_router_dispatch_fails_closed_without_identity_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DenyingService(_CanonicalService):
        async def execute_plugin(self, plugin_name: str, **kwargs: Any) -> Any:
            self.calls.append({"plugin_name": plugin_name, **kwargs})
            return SimpleNamespace(
                status=ExecutionStatus.FAILED,
                result=None,
                error="Plugin execution requires authenticated user and tenant scope",
                error_code="identity_scope_missing",
            )

    service = DenyingService()
    monkeypatch.setattr(host_router_module, "get_plugin_service", lambda: service)
    router = host_router_module.PluginRouter()

    with pytest.raises(PermissionError, match="authenticated user and tenant scope"):
        await router.dispatch("echo", {"message": "hello"}, roles=["user"])

    assert service.calls[0]["user_id"] is None
    assert service.calls[0]["tenant_id"] is None


def test_retired_platform_lifecycle_authorities_stay_deleted() -> None:
    root = (
        Path(__file__).parents[2]
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
    )
    retired_paths = (
        root / "plugin_lifecycle_manager.py",
        root / "integration" / "lifecycle_manager.py",
    )
    for path in retired_paths:
        assert not path.exists(), f"retired lifecycle authority resurrected: {path}"


def test_platform_runtime_surfaces_do_not_construct_duplicate_execution_stack() -> None:
    root = (
        Path(__file__).parents[2]
        / "src"
        / "ai_karen_engine"
        / "extensions"
        / "platform"
        / "core"
    )
    source_expectations = {
        root / "host" / "manager.py": (
            "ExtensionLoader",
            "register_loaded_instance",
            "load_extension(extension_name)",
        ),
        root / "host" / "router.py": (
            "ExtensionLoader",
            "ExtensionRunner",
            "register_loaded_instance",
            "_execute_extension_with_timeout",
        ),
        root / "host" / "factory.py": (
            "from ai_karen_engine.extensions.registry import ExtensionRegistry",
            "from ai_karen_engine.plugins.router import PluginRouter",
            "ExtensionRegistry(",
            "PluginRouter(",
        ),
        root / "integration" / "manager.py": (
            "PermissionsManager",
            "SandboxManager",
            "get_plugin_router",
            ".router.dispatch(",
        ),
        root / "manager.py": (
            "ExtensionManager(",
            "get_plugin_router",
            "get_registry",
        ),
    }
    for path, forbidden_fragments in source_expectations.items():
        source = path.read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in source, (
                f"{path} still contains retired authority: {fragment}"
            )
