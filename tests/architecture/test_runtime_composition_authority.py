from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.cortex import CortexExecutionDecider
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


def test_chat_runtime_has_no_direct_cortex_implementation_import() -> None:
    runtime = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    source = runtime.read_text(encoding="utf-8")

    assert "core.cortex.executive" not in source
    assert "core.intelligence" not in source
