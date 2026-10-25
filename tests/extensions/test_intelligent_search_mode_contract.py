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
    scope = {}
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
