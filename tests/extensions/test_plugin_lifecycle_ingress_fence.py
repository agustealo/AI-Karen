"""KPLUG-CONV-02C3B3A: compatibility routes never mint lifecycle authority.

These tests do not claim that package install/uninstall, refresh on startup,
or the legacy low-level kernel method have been globally migrated. They prove
that unapproved HTTP and extension-manager lifecycle ingress fail closed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request

from ai_karen_engine.api_routes.extensions import extensions as extension_routes
from ai_karen_engine.api_routes.plugins import plugins as plugin_routes
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
    PluginLifecycleApprovalScope,
)
from ai_karen_engine.extensions.platform.core.manager import ExtensionCoreManager


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "root_path": "",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
    })


def _scope(action: str = "enable") -> tuple[ChatExecutionContext, PluginLifecycleApprovalScope]:
    tenant_id = str(uuid.uuid4())
    actor = str(uuid.uuid4())
    conversation = str(uuid.uuid4())
    context = ChatExecutionContext(
        user_id=actor,
        tenant_id=tenant_id,
        session_id="authenticated-session",
        conversation_id=conversation,
        request_id="request-1",
        correlation_id="correlation-1",
        authenticated_user=UserData(
            user_id=actor,
            tenant_id=tenant_id,
            roles=["admin"],
        ),
    )
    scope = PluginLifecycleApprovalScope(
        installation_id="approved-plugin",
        action=action,
        manifest_checksum="a" * 64,
        expected_state="disabled" if action == "enable" else "enabled",
        expected_revision=4,
        tenant_id=tenant_id,
        user_id=actor,
        session_id="authenticated-session",
        conversation_id=conversation,
    )
    return context, scope


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_legacy_admin_mutation_does_not_call_raw_service(
    monkeypatch: pytest.MonkeyPatch, enabled: bool,
) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        plugin_routes, "get_audit_logger",
        lambda: SimpleNamespace(log_audit_event=events.append),
    )

    class Service:
        async def enable_plugin(self, _name: str) -> bool:
            pytest.fail("No raw service enable may run from HTTP ingress")

        async def disable_plugin(self, _name: str) -> bool:
            pytest.fail("No raw service disable may run from HTTP ingress")

    with pytest.raises(HTTPException) as exc:
        await plugin_routes._set_enabled(
            plugin_name="approved-plugin",
            request=_request("/api/plugins/approved-plugin/enable"),
            user={"user_id": "operator", "tenant_id": "tenant-a", "roles": ["admin"]},
            service=Service(),
            enabled=enabled,
        )
    assert exc.value.status_code == 409
    assert "approval required" in str(exc.value.detail).lower()
    assert [event["metadata"]["outcome"] for event in events] == [
        "attempt", "rejected",
    ]


@pytest.mark.asyncio
async def test_legacy_admin_reload_cannot_refresh_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        plugin_routes, "get_audit_logger",
        lambda: SimpleNamespace(log_audit_event=events.append),
    )

    class Service:
        async def refresh_plugins(self) -> int:
            pytest.fail("Registry rebuild must not run through unapproved admin ingress")

    with pytest.raises(HTTPException) as exc:
        await plugin_routes.reload_plugins(
            request=_request("/api/plugins/reload"),
            current_user={"user_id": "operator", "tenant_id": "tenant-a"},
            plugin_service=Service(),
        )
    assert exc.value.status_code == 409
    assert "governed lifecycle admission" in str(exc.value.detail)
    assert [event["metadata"]["outcome"] for event in events] == [
        "attempt", "rejected",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["enable", "disable"])
async def test_extension_mutation_http_route_rejects_without_manager_call(
    monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    from ai_karen_engine import audit_logging

    events: list[dict] = []
    monkeypatch.setattr(
        audit_logging, "get_audit_logger",
        lambda: SimpleNamespace(log_audit_event=events.append),
    )
    monkeypatch.setattr(
        extension_routes, "get_extension_manager",
        lambda: pytest.fail("Ungoverned extension manager cannot run"),
    )
    handler = (
        extension_routes.load_extension if action == "enable"
        else extension_routes.unload_extension
    )
    with pytest.raises(HTTPException) as exc:
        await handler(
            "approved-plugin",
            request=_request("/api/extensions/approved-plugin/" +
                             ("load" if action == "enable" else "unload")),
            user={"user_id": "operator", "tenant_id": "tenant-a"},
        )
    assert exc.value.status_code == 409
    assert events[-1]["metadata"]["action"] == action
    assert events[-1]["metadata"]["outcome"] == "rejected"
    assert events[-1]["metadata"]["reason"] == "lifecycle_approval_required"


@pytest.mark.asyncio
async def test_extension_compatibility_methods_reject_missing_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExtensionCoreManager()
    monkeypatch.setattr(
        manager, "_ensure_service",
        AsyncMock(side_effect=AssertionError("No unapproved service call")),
    )
    with pytest.raises(PermissionError, match="Approved lifecycle"):
        await manager.load_extension("approved-plugin")
    with pytest.raises(PermissionError, match="Approved lifecycle"):
        await manager.unload_extension("approved-plugin")
    with pytest.raises(PermissionError, match="separately approved"):
        await manager.reload_extension("approved-plugin")
    with pytest.raises(PermissionError, match="governed lifecycle admission"):
        await manager.refresh_registry()
    with pytest.raises(PermissionError, match="governed lifecycle admission"):
        await manager.reload_runtime()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["enable", "disable"])
async def test_extension_facade_reuses_governed_service_for_exact_approval(
    monkeypatch: pytest.MonkeyPatch, action: str,
) -> None:
    manager = ExtensionCoreManager()
    context, scope = _scope(action)
    approval_id = str(uuid.uuid4())
    service = SimpleNamespace(
        execute_approved_lifecycle=AsyncMock(
            return_value={"status": "verified_committed"},
        ),
        get_plugin_info=AsyncMock(return_value={"name": "approved-plugin"}),
    )
    monkeypatch.setattr(manager, "_ensure_service", AsyncMock(return_value=service))
    monkeypatch.setattr(
        manager, "_status_from_record", lambda record: {
            "name": record["name"], "status": "enabled",
        },
    )

    # Fail before touching the service when the approval targets a different
    # installation or verb, even if the caller supplies a real object.
    with pytest.raises(ValueError, match="differs"):
        if action == "enable":
            await manager.load_extension(
                "other-plugin", context=context, scope=scope, approval_id=approval_id,
            )
        else:
            await manager.unload_extension(
                "other-plugin", context=context, scope=scope, approval_id=approval_id,
            )
    service.execute_approved_lifecycle.assert_not_awaited()

    if action == "enable":
        result = await manager.load_extension(
            "approved-plugin", context=context, scope=scope, approval_id=approval_id,
        )
        assert result == {"name": "approved-plugin", "status": "enabled"}
    else:
        assert await manager.unload_extension(
            "approved-plugin", context=context, scope=scope, approval_id=approval_id,
        )

    service.execute_approved_lifecycle.assert_awaited_once_with(
        context=context, scope=scope, approval_id=approval_id,
    )


@pytest.mark.asyncio
async def test_extension_catalog_read_cannot_refresh_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = ExtensionCoreManager()
    service = SimpleNamespace(
        list_plugins=AsyncMock(return_value=[{"name": "approved-plugin"}]),
        refresh_plugins=AsyncMock(
            side_effect=AssertionError("Catalog read must not refresh"),
        ),
    )
    monkeypatch.setattr(manager, "_ensure_service", AsyncMock(return_value=service))
    monkeypatch.setattr(
        manager, "_status_from_record", lambda record: dict(record),
    )
    assert await manager.refresh_extensions() == [{"name": "approved-plugin"}]
    service.refresh_plugins.assert_not_awaited()
