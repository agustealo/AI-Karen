from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROUTES = REPO_ROOT / "src" / "ai_karen_engine" / "api_routes" / "models"
ROUTER_REGISTRY = REPO_ROOT / "src" / "ai_karen_engine" / "server" / "routers.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_legacy_llm_control_plane_is_deleted_and_unmounted() -> None:
    """The retired /api/llm compatibility control plane must not return."""
    retired_route = MODEL_ROUTES / "llm.py"
    assert not retired_route.exists(), (
        "The legacy LLM router duplicated provider truth, exposed route-level "
        "provider selection, fabricated fallback profiles, and contained a broken "
        "settings writer. Use the canonical provider/runtime/settings owners instead."
    )

    registry_source = _read(ROUTER_REGISTRY)
    forbidden = (
        "ai_karen_engine.api_routes.models.llm",
        "llm_router",
        '"/api/llm"',
    )
    for token in forbidden:
        assert token not in registry_source, f"Retired LLM router mount returned: {token}"


def test_model_routes_do_not_reintroduce_legacy_provider_selection_or_settings_writer() -> None:
    """Provider choice belongs to runtime/CORTEX, not HTTP ingress."""
    violations: list[str] = []
    forbidden = (
        "auto_select_provider(",
        "save_llm_settings(",
    )

    for route_file in sorted(MODEL_ROUTES.glob("*.py")):
        source = _read(route_file)
        for token in forbidden:
            if token in source:
                violations.append(f"{route_file.relative_to(REPO_ROOT)}: {token}")

    assert not violations, "Legacy LLM control-plane authority returned:\n" + "\n".join(violations)


def test_canonical_provider_and_runtime_catalog_routes_remain_mounted() -> None:
    """Retiring /api/llm must not remove the backend-truth provider surfaces."""
    registry_source = _read(ROUTER_REGISTRY)

    assert 'RouterSpec(provider_router, "/api/providers", ("providers",))' in registry_source
    assert 'RouterSpec(runtime_catalog_router, "/api", ("runtime",))' in registry_source
    assert (
        'RouterSpec(provider_public_router, "/api/public/providers", ("public-providers",))'
        in registry_source
    )
