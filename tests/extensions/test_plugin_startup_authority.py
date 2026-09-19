"""Proofs that server startup uses the single canonical plugin service."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.server import startup
import ai_karen_engine.services.plugin_service as plugin_service_module


class _FakePluginService:
    def __init__(self, root: Path, *, initialized: bool = False) -> None:
        self.marketplace_path = root
        self.core_plugins_path = root
        self.initialized = initialized

    def get_service_stats(self) -> dict[str, Any]:
        return {"registry_stats": {"total_plugins": 2}}


@pytest.mark.asyncio
async def test_initialize_extension_kernel_uses_global_plugin_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _FakePluginService(tmp_path)
    calls: list[tuple[Path | None, Path | None, bool]] = []

    def get_service() -> _FakePluginService:
        return service

    async def initialize_service(
        marketplace_path: Path | None = None,
        core_plugins_path: Path | None = None,
        auto_discover: bool = True,
    ) -> _FakePluginService:
        calls.append((marketplace_path, core_plugins_path, auto_discover))
        service.initialized = True
        return service

    monkeypatch.setattr(plugin_service_module, "get_plugin_service", get_service)
    monkeypatch.setattr(
        plugin_service_module,
        "initialize_plugin_service",
        initialize_service,
    )

    await startup.initialize_extension_kernel(
        SimpleNamespace(plugin_dirs=[str(tmp_path)])
    )

    assert calls == [(tmp_path, tmp_path, True)]
    assert service.initialized is True


@pytest.mark.asyncio
async def test_initialize_extension_kernel_reuses_matching_initialized_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = _FakePluginService(tmp_path, initialized=True)

    def get_service() -> _FakePluginService:
        return service

    async def should_not_initialize(*args: Any, **kwargs: Any) -> _FakePluginService:
        raise AssertionError("matching initialized service must be reused")

    monkeypatch.setattr(plugin_service_module, "get_plugin_service", get_service)
    monkeypatch.setattr(
        plugin_service_module,
        "initialize_plugin_service",
        should_not_initialize,
    )

    await startup.initialize_extension_kernel(
        SimpleNamespace(plugin_dirs=[str(tmp_path)])
    )


@pytest.mark.asyncio
async def test_initialize_extension_kernel_rejects_multiple_roots(
    tmp_path: Path,
) -> None:
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ValueError, match="one canonical plugin root"):
        await startup.initialize_extension_kernel(
            SimpleNamespace(plugin_dirs=[str(tmp_path), str(other)])
        )


def test_startup_has_no_retired_discovery_or_ghost_registry_authority() -> None:
    init_source = inspect.getsource(startup.initialize_extension_kernel)
    bootstrap_source = inspect.getsource(startup.run_canonical_runtime_bootstrap)

    assert "extensions.discovery" not in init_source
    assert "extensions.manifest" not in init_source
    assert "ExtensionRegistry()" not in bootstrap_source
    assert "get_plugin_service" in init_source
    assert "get_plugin_service" in bootstrap_source
