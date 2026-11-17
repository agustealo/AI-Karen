#!/usr/bin/env python3
"""Read-only, non-certifying census of potential direct model execution callers.

KCHAT-AUTH-05B2B1 collects candidate callsites for a human-reviewed migration.
It never imports scanned source modules, executes model code, grants authorization,
or concludes that a call is safe merely because an admission keyword is present.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

SCHEMA = "kchat-auth-05b2b-caller-census-v1"

METHOD_CATEGORIES: dict[str, str] = {
    "generate_chat": "model_generation",
    "generate_embedding": "embedding_generation",
    "invoke_provider": "provider_invocation",
    "invoke_provider_sync": "provider_invocation",
    "stream_provider": "provider_stream",
    "stream_provider_sync": "provider_stream",
    "invoke_embedding": "embedding_invocation",
    "invoke_embedding_sync": "embedding_invocation",
    "get_embedding": "legacy_embedding",
    "get_embeddings_batch": "legacy_embedding",
    "embed": "legacy_embedding",
    "embed_authoritative": "authoritative_embedding",
    "generate_text": "direct_model_client",
    "generate_text_with_model": "direct_model_client",
    "reserve_transport": "existing_admission",
    "reserve_local_embedding": "existing_admission",
}
FACTORY_CATEGORIES: dict[str, str] = {
    "ModelManager": "runtime_construction",
    "EmbeddingManager": "embedding_construction",
    "OpenAICompatibleRuntimeClient": "raw_client_construction",
    "LLMUtils": "facade_construction",
}


def _receiver_name(expression: ast.AST) -> str:
    """Expose symbol names only, never prompt strings or argument expressions."""
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return f"{_receiver_name(expression.value)}.{expression.attr}"
    return "<expression>"


class _CallsiteVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.callsites: list[dict[str, Any]] = []

    def _visit_scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def _record(
        self,
        node: ast.Call,
        *,
        method: str,
        receiver: str,
        category: str,
        kind: str,
    ) -> None:
        keywords = {item.arg for item in node.keywords if item.arg is not None}
        self.callsites.append(
            {
                "path": self.relative_path,
                "line": node.lineno,
                "column": node.col_offset,
                "scope": ".".join(self.scope) or "<module>",
                "method": method,
                "receiver": receiver,
                "category": category,
                "kind": kind,
                "execution_admission_keyword": "execution_admission" in keywords,
                "selected_model_keyword": "model" in keywords,
                "review_status": "unverified_candidate",
            }
        )

    def visit_Call(self, node: ast.Call) -> None:
        callee = node.func
        if isinstance(callee, ast.Attribute):
            method = callee.attr
            if method in METHOD_CATEGORIES:
                self._record(
                    node,
                    method=method,
                    receiver=_receiver_name(callee.value),
                    category=METHOD_CATEGORIES[method],
                    kind="attribute_call",
                )
            elif method in FACTORY_CATEGORIES:
                self._record(
                    node,
                    method=method,
                    receiver=_receiver_name(callee.value),
                    category=FACTORY_CATEGORIES[method],
                    kind="construction",
                )
        elif isinstance(callee, ast.Name):
            if callee.id in FACTORY_CATEGORIES:
                self._record(
                    node,
                    method=callee.id,
                    receiver="<name>",
                    category=FACTORY_CATEGORIES[callee.id],
                    kind="construction",
                )
            elif (
                callee.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value in METHOD_CATEGORIES
            ):
                method = node.args[1].value
                self._record(
                    node,
                    method=method,
                    receiver=_receiver_name(node.args[0]),
                    category=METHOD_CATEGORIES[method],
                    kind="dynamic_attribute_lookup",
                )
        self.generic_visit(node)


def scan_sources(root: Path) -> dict[str, Any]:
    """Return deterministic candidate evidence; parsing errors are never hidden."""
    source_root = root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"Source root is not a directory: {root}")

    candidates: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    scanned_files = 0

    for path in sorted(source_root.rglob("*.py")):
        if not path.is_file() or not path.resolve().is_relative_to(source_root):
            continue
        relative_path = path.relative_to(source_root).as_posix()
        scanned_files += 1
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=relative_path,
            )
        except (SyntaxError, UnicodeError) as exc:
            parse_errors.append(
                {
                    "path": relative_path,
                    "line": getattr(exc, "lineno", None),
                    "error_type": type(exc).__name__,
                }
            )
            continue
        visitor = _CallsiteVisitor(relative_path)
        visitor.visit(tree)
        candidates.extend(visitor.callsites)

    candidates.sort(
        key=lambda item: (
            item["path"],
            item["line"],
            item["column"],
            item["category"],
            item["method"],
        )
    )
    categories = Counter(item["category"] for item in candidates)
    return {
        "schema": SCHEMA,
        "root": root.as_posix(),
        "source_sha": os.environ.get("GITHUB_SHA", ""),
        "scanned_python_files": scanned_files,
        "candidate_total": len(candidates),
        "categories": dict(sorted(categories.items())),
        "candidates": candidates,
        "parse_errors": parse_errors,
        "limitations": [
            "Static candidates only: no proof of active runtime reachability.",
            "Admission keyword presence does not prove authentication.",
            "Dynamic dispatch and reflection may evade this AST inventory.",
            "No network traffic or model execution is exercised.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("src/ai_karen_engine"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        report = scan_sources(args.root)
    except ValueError as exc:
        parser.error(str(exc))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(
        "KCHAT-AUTH-05B2B1 non-certifying caller census: "
        f"files={report['scanned_python_files']} "
        f"candidates={report['candidate_total']} "
        f"parse_errors={len(report['parse_errors'])}"
    )
    for category, count in report["categories"].items():
        print(f"  {category}: {count}")
    return 1 if report["parse_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
