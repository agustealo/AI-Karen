from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/core/runtime/platform_resource_service.py"
SYSTEM_ROUTE = ROOT / "src/ai_karen_engine/api_routes/system/system.py"
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
DOWNLOAD_CONTROL = (
    ROOT / "src/ai_karen_engine/core/model_runtime/model_download_control_service.py"
)
SYSTEM_TOOL = ROOT / "src/ai_karen_engine/tools/system_resources_tool.py"
TOOLS = ROOT / "src/ai_karen_engine/tools/web_search_tool.py"


def test_platform_resource_service_is_canonical_read_only_authority() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "class PlatformResourceService" in source
    assert "class PlatformResourceSnapshot" in source
    assert "class ResourceMetric" in source
    assert "available: bool" in source
    assert "get_platform_resource_service" in source
    assert "trigger_resource_cleanup" not in source
    assert "ModelDownload" not in source


def test_system_resource_api_reuses_platform_authority() -> None:
    route = SYSTEM_ROUTE.read_text(encoding="utf-8")
    routers = ROUTERS.read_text(encoding="utf-8")

    assert '@router.get("/resources")' in route
    assert "get_platform_resource_service().snapshot().as_dict()" in route
    assert 'RouterSpec(system_router, "/api/system", ("system",))' in routers


def test_model_downloads_consumes_platform_resources_without_owning_them() -> None:
    source = DOWNLOAD_CONTROL.read_text(encoding="utf-8")

    assert "get_platform_resource_service().snapshot" in source
    assert "resource_snapshot.as_dict()" in source
    assert "resource_monitor" not in source
    assert "monitor_resources_once" not in source


def test_system_resource_tool_reuses_same_platform_authority() -> None:
    tool = SYSTEM_TOOL.read_text(encoding="utf-8")
    registry = TOOLS.read_text(encoding="utf-8")

    assert 'name="system_resources"' in tool
    assert "get_platform_resource_service().snapshot().as_dict()" in tool
    assert "SystemResourcesTool()" in registry
    assert "ToolCategory.SYSTEM" in tool
