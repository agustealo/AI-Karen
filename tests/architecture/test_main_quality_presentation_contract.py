from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAIN_QUALITY_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/main-quality-gate.yml"
PRESENTATION_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/presentation-contract.yml"
WEB_HEALTH_ROUTE = (
    REPOSITORY_ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/api/health/route.ts"
)
CANONICAL_VERIFIER_COMMAND = (
    "python scripts/ci/verify_presentation_assets.py --require-assets"
)


def test_main_quality_delegates_to_canonical_presentation_verifier() -> None:
    workflow = MAIN_QUALITY_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(CANONICAL_VERIFIER_COMMAND) == 1
    assert workflow.index(CANONICAL_VERIFIER_COMMAND) < workflow.index(
        "Install quality and runtime contract dependencies"
    )


def test_dedicated_and_aggregate_presentation_gates_share_one_authority() -> None:
    main_quality = MAIN_QUALITY_WORKFLOW.read_text(encoding="utf-8")
    presentation = PRESENTATION_WORKFLOW.read_text(encoding="utf-8")

    assert CANONICAL_VERIFIER_COMMAND in main_quality
    assert CANONICAL_VERIFIER_COMMAND in presentation


def test_web_dashboard_health_proxy_uses_canonical_backend_monitoring_route() -> None:
    route = WEB_HEALTH_ROUTE.read_text(encoding="utf-8")

    assert "proxyToBackend(" in route
    assert "'/api/health'" in route
    assert "proxyToBackend(\n      nextRequest,\n      '/health'" not in route
