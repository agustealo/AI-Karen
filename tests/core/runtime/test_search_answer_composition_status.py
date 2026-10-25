"""Executable contract test for runtime-owned search answer provenance."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace


def _composition_harness(synthesis):
    path = Path(__file__).resolve().parents[3] / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    runtime = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChatRuntime")
    method = next(node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_compose_direct_capability_answer")
    compiled = ast.fix_missing_locations(ast.Module(
        body=[ast.ClassDef(name="Harness", bases=[], keywords=[], body=[method], decorator_list=[])],
        type_ignores=[],
    ))
    namespace = {}
    exec(compile(compiled, str(path), "exec"), namespace)

    class Harness(namespace["Harness"]):
        async def _synthesize_search_evidence(self, *args):
            return synthesis

        async def _plan_verified_surface(self, *args, **kwargs):
            return None

    return Harness()


def test_grounded_model_answer_retains_execution_receipt():
    runtime = _composition_harness(("Verified model answer", {
        "actual_provider": "verified_provider",
        "actual_model": "verified_model",
        "response_source": "grounded_search_model",
    }))
    result = SimpleNamespace(success=True, text="Original retrieved evidence")
    answer, receipt = asyncio.run(runtime._compose_direct_capability_answer(
        None, SimpleNamespace(intent="search.general"), None, None, result,
        {"response_source": "plugin"},
    ))
    assert answer == "Verified model answer"
    assert receipt["answer_composition_status"] == "grounded_model"
    assert receipt["actual_model"] == "verified_model"


def test_failed_synthesis_retains_evidence_and_marks_it_not_generated():
    runtime = _composition_harness(None)
    result = SimpleNamespace(success=True, text="Original retrieved evidence")
    answer, receipt = asyncio.run(runtime._compose_direct_capability_answer(
        None, SimpleNamespace(intent="search.general"), None, None, result,
        {"response_source": "plugin", "actual_model": None},
    ))
    assert answer == "Original retrieved evidence"
    assert receipt["answer_composition_status"] == "retrieved_evidence"
    assert receipt["actual_model"] is None


def test_weather_fallback_is_observation_not_model_answer():
    runtime = _composition_harness(None)
    result = SimpleNamespace(success=True, text="Measured observation")
    answer, receipt = asyncio.run(runtime._compose_direct_capability_answer(
        None, SimpleNamespace(intent="search.weather"), None, None, result, {},
    ))
    assert answer == "Measured observation"
    assert receipt["answer_composition_status"] == "source_observation"


def test_failed_capability_is_neither_evidence_nor_model_answer():
    runtime = _composition_harness(("Should not synthesize", {
        "actual_provider": "unreachable",
        "actual_model": "unreachable",
    }))
    result = SimpleNamespace(success=False, text="Capability unavailable")
    answer, receipt = asyncio.run(runtime._compose_direct_capability_answer(
        None, SimpleNamespace(intent="search.weather"), None, None, result,
        {"response_source": "capability_unavailable", "actual_model": None},
    ))
    assert answer == "Capability unavailable"
    assert receipt["answer_composition_status"] == "capability_unavailable"
    assert receipt["actual_model"] is None
