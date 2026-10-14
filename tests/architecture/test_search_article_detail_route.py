"""Article detail ingress never takes user or tenant scope from the caller."""

import ast
from pathlib import Path


ROUTES = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/api_routes/plugins/plugins.py"
)


def test_article_detail_uses_authenticated_principal_and_scoped_service():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    fn = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "get_search_article"
    )
    args = [arg.arg for arg in fn.args.args]
    assert args == ["article_id", "current_user"]
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read"
        and {kw.arg for kw in node.keywords} == {"tenant_id", "user_id", "article_id"}
        for node in ast.walk(fn)
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Depends"
        for node in ast.walk(fn)
    )
