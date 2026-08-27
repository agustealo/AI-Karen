from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DependencyStatus,
    ProviderRouterProbe,
)
from ai_karen_engine.core.runtime.composition import (
    RuntimeComposition,
    get_cortex_execution_decider,
    get_expression_gateway,
    get_runtime_composition,
    reset_runtime_composition,
    set_runtime_composition,
)


ROOT = Path(__file__).resolve().parents[2]


class _FakeCortex:
    pass


class _AvailabilityOnlyGateway:
    def __init__(self, healthy: bool = True, reason: str | None = None) -> None:
        self.healthy = healthy
        self.reason = reason
        self.calls = 0

    def availability(self) -> tuple[bool, str | None]:
        self.calls += 1
        return self.healthy, self.reason


def test_runtime_composition_owns_explicit_cortex_and_expression_gateway() -> None:
    replacement = RuntimeComposition(
        cortex=_FakeCortex(),
        expression_gateway=_AvailabilityOnlyGateway(),
    )
    set_runtime_composition(replacement)

    assert get_runtime_composition() is replacement
    assert get_cortex_execution_decider() is replacement.cortex
    assert get_expression_gateway() is replacement.expression_gateway

    reset_runtime_composition()


def test_composition_contract_keeps_concrete_cognitive_imports_lazy() -> None:
    composition = ROOT / "src/ai_karen_engine/core/runtime/composition.py"
    source = composition.read_text(encoding="utf-8")

    assert "if TYPE_CHECKING:" in source
    assert "def build_runtime_composition()" in source
    build_body = source.split("def build_runtime_composition()", 1)[1]
    assert "from ai_karen_engine.core.cortex.executive import CortexExecutionDecider" in build_body
    assert "from ai_karen_engine.core.expression.gateway import ExpressionGateway" in build_body


def test_cortex_public_surface_does_not_export_process_singleton_accessor() -> None:
    cortex_init = ROOT / "src/ai_karen_engine/core/cortex/__init__.py"
    source = cortex_init.read_text(encoding="utf-8")

    assert '"CortexExecutionDecider"' in source
    assert '"get_cortex_execution_decider"' not in source


def test_cortex_executive_has_no_process_singleton() -> None:
    executive = ROOT / "src/ai_karen_engine/core/cortex/executive.py"
    source = executive.read_text(encoding="utf-8")

    assert "_decider:" not in source
    assert "def get_cortex_execution_decider(" not in source


def test_runtime_cortex_compatibility_shim_is_retired() -> None:
    shim = ROOT / "src/ai_karen_engine/core/runtime/cortex_execution_decider.py"

    assert not shim.exists()


def test_chat_runtime_consumes_composition_without_shadow_constructors() -> None:
    runtime = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    source = runtime.read_text(encoding="utf-8")

    assert "core.cortex.executive" not in source
    assert "core.intelligence" not in source
    assert "get_cortex_execution_decider()" not in source
    assert "ExpressionGateway()" not in source
    assert "self._composition.cortex.decide(request)" in source
    assert "self._composition.expression_gateway" in source


def test_control_plane_uses_composed_gateway_without_synthetic_generation() -> None:
    control_plane = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime_control_plane.py"
    source = control_plane.read_text(encoding="utf-8")

    assert "ProviderRouterProbe(self._composition.expression_gateway)" in source
    assert "ExpressionTask(" not in source
    assert "gateway.generate(" not in source
    assert '"builtin_vllm"' not in source
    assert '"builtin_transformers"' not in source


@pytest.mark.asyncio
async def test_provider_router_probe_checks_availability_without_generation() -> None:
    gateway = _AvailabilityOnlyGateway(True)
    probe = ProviderRouterProbe(gateway)

    health = await probe.check()

    assert health.status is DependencyStatus.HEALTHY
    assert health.reason is None
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_provider_router_probe_preserves_unavailability_reason() -> None:
    gateway = _AvailabilityOnlyGateway(False, "cloud:circuit_open")
    probe = ProviderRouterProbe(gateway)

    health = await probe.check()

    assert health.status is DependencyStatus.UNHEALTHY
    assert health.reason == "cloud:circuit_open"
    assert gateway.calls == 1
