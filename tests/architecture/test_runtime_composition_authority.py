from __future__ import annotations

from pathlib import Path

import pytest

from ai_karen_engine.core.cortex import CortexExecutionDecider
from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
    DependencyStatus,
    ProviderRouterProbe,
)
from ai_karen_engine.core.runtime.composition import (
    RuntimeComposition,
    build_runtime_composition,
    get_cortex_execution_decider,
    get_expression_gateway,
    get_runtime_composition,
    reset_runtime_composition,
    set_runtime_composition,
)
from ai_karen_engine.core.runtime.cortex_execution_decider import (
    get_cortex_execution_decider as get_compat_cortex,
)


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_composition_owns_process_cortex_and_expression_gateway() -> None:
    reset_runtime_composition()

    composition = get_runtime_composition()

    assert composition.cortex is get_cortex_execution_decider()
    assert composition.cortex is get_compat_cortex()
    assert composition.expression_gateway is get_expression_gateway()


def test_runtime_composition_can_be_explicitly_injected() -> None:
    fresh = build_runtime_composition()
    replacement = RuntimeComposition(
        cortex=fresh.cortex,
        expression_gateway=fresh.expression_gateway,
    )

    set_runtime_composition(replacement)

    assert get_runtime_composition() is replacement
    assert get_cortex_execution_decider() is replacement.cortex
    assert get_expression_gateway() is replacement.expression_gateway

    reset_runtime_composition()


def test_cortex_public_surface_does_not_export_process_singleton_accessor() -> None:
    import ai_karen_engine.core.cortex as cortex

    assert "get_cortex_execution_decider" not in cortex.__all__
    assert CortexExecutionDecider is cortex.CortexExecutionDecider


def test_runtime_compatibility_shim_delegates_instance_ownership_to_composition() -> None:
    shim = ROOT / "src/ai_karen_engine/core/runtime/cortex_execution_decider.py"
    source = shim.read_text(encoding="utf-8")

    assert "core.runtime.composition import get_cortex_execution_decider" in source
    assert "core.cortex.executive import (" not in source


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


class _AvailabilityOnlyGateway:
    def __init__(self, healthy: bool, reason: str | None = None) -> None:
        self.healthy = healthy
        self.reason = reason
        self.calls = 0

    def availability(self) -> tuple[bool, str | None]:
        self.calls += 1
        return self.healthy, self.reason


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
