"""Fail-closed regression tests for explicit Intelligent Search mode selection."""

import ast
from pathlib import Path


def _dispatcher_module():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    dispatcher = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WebSearchDispatcher"
    )
    resolver = next(
        node for node in dispatcher.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_mode"
    )
    mapping = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MODE_HANDLER_MAP" for t in node.targets)
    )
    # Only load the existing pure resolver and its known-mode keys. No plugin
    # initialization or network/provider imports should be necessary.
    known_modes = ast.literal_eval(
        ast.Dict(keys=mapping.value.keys, values=[ast.Constant(value=None) for _ in mapping.value.keys])
    )
    resolver.decorator_list = []
    minimal_tree = ast.fix_missing_locations(
        ast.Module(
            body=[
                ast.Assign(targets=[ast.Name(id="MODE_HANDLER_MAP", ctx=ast.Store())],
                           value=ast.Constant(value=None)),
                ast.ClassDef(name="Resolver", bases=[], keywords=[],
                             body=[resolver], decorator_list=[]),
            ],
            type_ignores=[],
        )
    )
    # The extracted resolver uses typing annotations from its original module.
    # Supply those dependencies instead of changing production annotations.
    from typing import Any, Dict

    scope = {"Any": Any, "Dict": Dict}
    exec(compile(minimal_tree, str(path), "exec"), scope)
    scope["MODE_HANDLER_MAP"] = known_modes
    scope["resolve_capability_decision"] = lambda query: type(
        "Decision", (), {"intent": "search.weather" if query == "weather in Detroit" else "general.chat"}
    )()
    return scope["Resolver"]()


def test_explicit_invalid_mode_is_not_silently_downgraded():
    resolver = _dispatcher_module()
    for invalid in ("does_not_exist", "", 12, {"mode": "general"}):
        assert resolver._resolve_mode({"mode": invalid}) not in {
            "general", "news", "docs", "weather", "deep_research",
            "structured_extract", "stock_market"
        }


def test_explicit_valid_modes_preserve_requested_selection():
    resolver = _dispatcher_module()
    assert resolver._resolve_mode({"mode": "weather"}) == "weather"
    assert resolver._resolve_mode({"mode": "deep-research"}) == "deep_research"
    assert resolver._resolve_mode({"context": {"mode": "news"}}) == "news"


def test_context_mode_cannot_silently_fall_back():
    resolver = _dispatcher_module()
    assert resolver._resolve_mode({"context": {"mode": "not_supported"}}) == "not_supported"


def test_auto_selection_uses_cortex_decision_and_explicit_general_is_respected():
    resolver = _dispatcher_module()
    assert resolver._resolve_mode({"query": "weather in Detroit"}) == "weather"
    assert resolver._resolve_mode({"mode": "auto", "query": "weather in Detroit"}) == "weather"
    assert resolver._resolve_mode({"mode": "general", "query": "weather in Detroit"}) == "general"


def test_governed_search_handlers_remain_identical():
    root = Path(__file__).resolve().parents[2]
    shipped = root / "free_plugins/essential/intelligent-search/handler.py"
    bundled = root / "src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py"
    assert shipped.read_bytes() == bundled.read_bytes()


def test_governed_handler_forwards_original_plan_and_meter():
    import asyncio
    from types import SimpleNamespace
    from typing import Any, Dict
    from unittest.mock import AsyncMock

    from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionBudgetMeter, ExecutionContext
    from ai_karen_engine.extensions.contracts import ExtensionExecutionContext
    from ai_karen_engine.services.tooling.internet_capability_service import InternetExecutionContext

    path = Path(__file__).resolve().parents[2] / "free_plugins/essential/intelligent-search/handler.py"
    tree = ast.parse(path.read_text())
    dispatcher = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "WebSearchDispatcher")
    run = next(n for n in dispatcher.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run")
    scope = dict(Any=Any, Dict=Dict, ExtensionExecutionContext=ExtensionExecutionContext,
                 ExecutionContext=ExecutionContext, InternetExecutionContext=InternetExecutionContext)
    exec(compile(ast.Module(body=[run], type_ignores=[]), str(path), "exec"), scope)
    plan = AuthorizedExecutionPlan(execution_id="e", policy_decision_id="p")
    meter = ExecutionBudgetMeter(plan.budget)
    ctx = ExtensionExecutionContext(request_id="r", correlation_id="c", user_id="u")
    object.__setattr__(ctx, "runtime_authority", lambda plugin: (plan, meter))
    handler = SimpleNamespace(prepare=AsyncMock(return_value={}), execute=AsyncMock())
    service = SimpleNamespace(execute=AsyncMock(return_value={"success": False, "status": "permission_denied"}))
    dispatcher = SimpleNamespace(_resolve_mode=lambda params: "general",
                                 _effective_mode_query=lambda query, mode, context: query,
                                 _get_handler=lambda mode: handler,
                                 _get_manifest_id=lambda: "intelligent-search",
                                 _internet_service=service,
                                 logger=__import__("logging").getLogger(__name__))
    result = asyncio.run(scope["run"](dispatcher, {"query": "release notes"}, ctx))
    assert result["success"] is False
    assert service.execute.await_args.kwargs["authorized_plan"] is plan
    assert service.execute.await_args.kwargs["execution_meter"] is meter
    handler.execute.assert_not_awaited()
    dispatcher._internet_service = None
    result = asyncio.run(scope["run"](dispatcher, {"query": "release notes"}, ctx))
    assert result["success"] is False
    handler.execute.assert_not_awaited()
