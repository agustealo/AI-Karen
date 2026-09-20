"""Regression proofs for the post-kernel platform compatibility surfaces."""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.services.plugin_service import ExecutionStatus
from ai_karen_engine.extensions.platform.core import manager as core_manager_module
from ai_karen_engine.extensions.platform.core.host import manager as host_manager_module
from ai_karen_engine.extensions.platform.core.host import router as router_module
from ai_karen_engine.extensions.platform.core.integration import manager as integration_module


class _FakeExecutionService:
    def __init__(self, *, completed: bool = True) -> None:
        self.calls: list[dict[str, Any]] = []
        self.completed = completed

    async def execute_plugin(self, **kwargs: Any) -> Any:
        self.calls.append(dict(kwargs))
        if self.completed:
            return SimpleNamespace(
                status=ExecutionStatus.COMPLETED,
                result={"ok": True},
                error=None,
                error_code=None,
            )
        return SimpleNamespace(
            status=ExecutionStatus.FAILED,
            result=None,
            error="identity missing",
            error_code="identity_scope_missing",
        )


@pytest.mark.asyncio
async def test_legacy_router_delegates_identity_scope_to_plugin_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeExecutionService()
    monkeypatch.setattr(router_module, "get_plugin_service", lambda: service)

    router = router_module.PluginRouter()
    result = await router.dispatch(
        "weather",
        {"city": "Detroit"},
        roles=["user"],
        user_context={
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "session_id": "session-1",
            "conversation_id": "conversation-1",
            "correlation_id": "correlation-1",
            "permissions": ["network_access"],
        },
    )

    assert result == {"ok": True}
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["plugin_name"] == "weather"
    assert call["user_id"] == "user-1"
    assert call["tenant_id"] == "tenant-1"
    assert call["session_id"] == "session-1"
    assert call["conversation_id"] == "conversation-1"
    assert call["correlation_id"] == "correlation-1"
    assert call["roles"] == ["user"]
    assert call["permissions"] == ["network_access"]


@pytest.mark.asyncio
async def test_integration_manager_does_not_fabricate_missing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeExecutionService(completed=False)
    monkeypatch.setattr(integration_module, "get_plugin_service", lambda: service)

    manager = integration_module.PluginManager()
    with pytest.raises(RuntimeError, match="identity_scope_missing"):
        await manager.run_plugin("weather", {}, {"roles": ["user"]})

    assert service.calls[0]["user_id"] is None
    assert service.calls[0]["tenant_id"] is None


def test_exported_platform_surfaces_have_no_direct_execution_authority() -> None:
    core_source = inspect.getsource(core_manager_module)
    host_source = inspect.getsource(host_manager_module)
    router_source = inspect.getsource(router_module)
    integration_source = inspect.getsource(integration_module)

    assert "ExtensionLoader" not in host_source
    assert "register_loaded_instance" not in host_source
    assert "ExtensionRunner" not in router_source
    assert "_execute_extension_with_timeout" not in router_source
    assert "PermissionsManager" not in integration_source
    assert "SandboxManager" not in integration_source
    assert "ExtensionLifecycleManager" not in integration_source

    for source in (core_source, host_source, router_source, integration_source):
        assert "get_plugin_service" in source


def test_platform_facades_do_not_import_plugin_service_at_module_load() -> None:
    """Prevent PluginKernel -> platform -> PluginService -> PluginKernel cycles."""
    for module in (
        core_manager_module,
        host_manager_module,
        router_module,
        integration_module,
    ):
        tree = ast.parse(inspect.getsource(module))
        module_level_imports = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert "ai_karen_engine.services.plugin_service" not in module_level_imports


def test_dynamic_plugin_fastapi_router_mounting_is_retired() -> None:
    source = inspect.getsource(router_module.PluginRouter.get_api_router)

    assert "include_router" not in source
    assert "record.instance" not in source
