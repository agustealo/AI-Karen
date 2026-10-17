"""Guard the canonical model gateway against logging generated conversation text."""

import ast
import inspect
import textwrap

from ai_karen_engine.core.expression.gateway import ExpressionGateway


def test_expression_gateway_never_logs_generated_response_text() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(ExpressionGateway.generate)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
        ):
            continue
        for child in ast.walk(node):
            assert not (
                isinstance(child, ast.Attribute)
                and isinstance(child.value, ast.Name)
                and child.value.id == "result"
                and child.attr == "text"
            ), "Never log the raw generated response or personal conversation content"
