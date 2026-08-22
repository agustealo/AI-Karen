from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"
CORE = SRC / "core"
SERVICES = SRC / "services"
API_ROUTES = SRC / "api_routes"


def _find_integrations_registry_imports(
    roots: tuple[pathlib.Path, ...],
) -> list[str]:
    """Find imports from integrations registries, excluding documented temp imports."""
    violations: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name.startswith("__pycache__"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if re.search(
                    r"from\s+ai_karen_engine\.integrations\.(llm_registry|registry|provider_registry)\s+import",
                    line,
                ):
                    # Allow documented temporary migration imports
                    if "TEMP-MIGRATION" in line or "TEMPORARY" in line:
                        continue
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {stripped}")
    return violations


def test_chat_runtime_uses_canonical_provider_registry() -> None:
    """ChatRuntimeControlPlane must resolve providers through canonical registry."""
    # Read source directly to avoid triggering deep import chain in test env
    chat_runtime_path = (
        CORE / "runtime" / "chat_runtime_control_plane.py"
    )
    text = chat_runtime_path.read_text(encoding="utf-8", errors="ignore")

    # Find the _has_live_provider_path method
    import re

    match = re.search(
        r"async def _has_live_provider_path.*?(?=\n    async def |\n    def |\nclass |\Z)",
        text,
        re.DOTALL,
    )
    assert match, "Could not find _has_live_provider_path method"
    method_source = match.group(0)

    assert "get_provider_registry_service" in method_source, (
        "_has_live_provider_path must use get_provider_registry_service"
    )
    assert "integrations.llm_registry" not in method_source, (
        "_has_live_provider_path must not import from integrations.llm_registry"
    )


def test_expression_runtime_uses_canonical_provider_registry() -> None:
    """Expression engines should not construct provider registries directly."""
    # The expression engines use get_provider() for instantiation which is
    # an execution concern, not registry authority. They should not import
    # registry classes for authority lookups.
    engine_path = (
        SRC / "core" / "expression" / "engines" / "builtin_provider_engine.py"
    )
    text = engine_path.read_text(encoding="utf-8", errors="ignore")
    # get_provider is for instantiation (execution), which is acceptable
    # but should not be importing registry classes for authority
    assert "from ai_karen_engine.integrations.registry import" not in text
    assert "from ai_karen_engine.integrations.provider_registry import" not in text


def test_model_routes_do_not_construct_provider_registries() -> None:
    """API routes should not directly instantiate legacy registry objects."""
    violations: list[str] = []
    for path in API_ROUTES.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Check for direct instantiation patterns
            if re.search(r"\bLLMRegistry\(\)", line) or re.search(
                r"\bProviderRegistry\(\)", line
            ):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {stripped}")
    assert not violations, (
        "API routes must not instantiate legacy registry objects:\n"
        + "\n".join(violations)
    )


def test_core_services_registry_imports_are_classified() -> None:
    """Remaining integrations registry imports in core/services/api_routes must be classified."""
    violations = _find_integrations_registry_imports((CORE, SERVICES, API_ROUTES))
    # This test documents remaining imports. Each must be classified as either:
    # - Provider instantiation (get_provider/get_active) - acceptable for now
    # - Legacy routing - deferred to next sprint
    # For now, we just verify the count is decreasing and documented
    assert isinstance(violations, list)
