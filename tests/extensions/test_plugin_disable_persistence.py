from pathlib import Path
from types import SimpleNamespace
import pytest
from ai_karen_engine.extensions.plugin_kernel import PluginKernel

@pytest.mark.asyncio
async def test_disable_persists_gate_before_runtime_transition(tmp_path: Path):
    kernel = PluginKernel(tmp_path)
    (tmp_path / "demo").mkdir()
    marker = tmp_path / "demo/.karen-manual-disabled"
    observations = []
    class Registry:
        def get(self, name):
            return SimpleNamespace(manifest=SimpleNamespace(id=name))
        async def update_state(self, name, state):
            observations.append((state.value, marker.is_file()))
    kernel.runtime_registry = Registry()
    assert await kernel.disable("demo")
    assert observations == [("disabled", True)]
    assert marker.is_file()

@pytest.mark.asyncio
async def test_symlink_gate_refused(tmp_path: Path):
    kernel = PluginKernel(tmp_path)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo/.karen-manual-disabled").symlink_to(tmp_path / "outside")
    class Registry:
        def get(self, name):
            return SimpleNamespace(manifest=SimpleNamespace(id=name))
        async def update_state(self, name, state):
            pytest.fail("Unexpected state transition")
    kernel.runtime_registry = Registry()
    with pytest.raises(ValueError):
        await kernel.disable("demo")


@pytest.mark.asyncio
async def test_failed_disable_keeps_restart_gate(tmp_path: Path):
    kernel = PluginKernel(tmp_path)
    (tmp_path / "demo").mkdir()
    marker = tmp_path / "demo/.karen-manual-disabled"
    class Registry:
        def get(self, name):
            return SimpleNamespace(manifest=SimpleNamespace(id=name))
        async def update_state(self, name, state):
            raise RuntimeError("disable rejected")
    kernel.runtime_registry = Registry()
    with pytest.raises(RuntimeError, match="disable rejected"):
        await kernel.disable("demo")
    assert marker.is_file()
