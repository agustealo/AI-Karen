"""Cross-language AG-UI HTTP body bound must match the backend owner.

The canonical FastAPI ingress owns the upper bound. The Next.js CopilotKit
adapter enforces the same strict bound before forwarding authenticated
requests so it cannot promise an envelope that FastAPI always rejects.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_PYTHON_ROUTE = (
    _ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
)
_TYPESCRIPT_ROUTE = (
    _ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/api/copilotkit/[[...slug]]/route.ts"
)


def _python_limit() -> int:
    tree = ast.parse(_PYTHON_ROUTE.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "AG_UI_MAX_REQUEST_BYTES"
                for target in node.targets
            )
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("Canonical AG-UI request byte bound is missing")


def test_sdk_run_request_byte_bound_matches_canonical_fastapi_limit() -> None:
    text = _TYPESCRIPT_ROUTE.read_text(encoding="utf-8")
    match = re.search(r"const MAX_RUN_BYTES\s*=\s*(\d+)\s*;", text)
    assert match is not None, "CopilotKit request bound is missing"
    assert int(match.group(1)) == _python_limit()
    assert 1024 <= _python_limit() <= 524288


def test_sdk_request_validator_counts_utf8_bytes_and_rejects_oversize() -> None:
    text = _TYPESCRIPT_ROUTE.read_text(encoding="utf-8")
    assert "new TextEncoder().encode(body).length > MAX_RUN_BYTES" in text
    assert 'status: 413' in text
    assert "validateRunEnvelope(request)" in text
