"""Extension UI install route must expose real HTTP outcomes."""

from __future__ import annotations

import pytest

from ai_karen_engine.api_routes.extensions import extensions as routes
from ai_karen_engine.extensions.platform.core.registry import ui_installer


@pytest.mark.asyncio
async def test_failed_ui_install_returns_http_failure(monkeypatch):
    monkeypatch.setattr(routes, "get_extension_manager", lambda: object())
    monkeypatch.setattr(
        ui_installer,
        "install_ui",
        lambda *_: ui_installer.UIInstallationResult(
            plugin_id="demo",
            status=ui_installer.UIInstallationStatus.VALIDATION_FAILED,
            state=ui_installer.UIInstallationState.ERROR,
            message="Baseline unavailable",
            error_code="INTEGRITY_BASELINE_UNAVAILABLE",
        ),
    )
    with pytest.raises(routes.HTTPException) as exc:
        await routes.install_extension(routes.InstallRequest(plugin_id="demo"), user={"id": "admin"})
    assert exc.value.status_code == 422
    assert exc.value.detail["error_code"] == "INTEGRITY_BASELINE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_success_ui_install_reports_installed_state(monkeypatch):
    monkeypatch.setattr(routes, "get_extension_manager", lambda: object())
    monkeypatch.setattr(
        ui_installer,
        "install_ui",
        lambda *_: ui_installer.UIInstallationResult(
            plugin_id="demo",
            status=ui_installer.UIInstallationStatus.SUCCESS,
            state=ui_installer.UIInstallationState.INSTALLED,
            message="Installed",
        ),
    )
    result = await routes.install_extension(
        routes.InstallRequest(plugin_id="demo"), user={"id": "admin"}
    )
    assert result["success"] is True
    assert result["ui_state"] == "installed"
