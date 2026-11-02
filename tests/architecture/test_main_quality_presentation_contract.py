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


def test_web_dashboard_health_proxy_uses_canonical_backend_readiness_authority() -> None:
    """Monitoring HTTP 200 cannot establish consumer readiness without PostgreSQL."""
    route = WEB_HEALTH_ROUTE.read_text(encoding="utf-8")

    assert "proxyToBackend(" in route
    assert "proxyToBackend(nextRequest, '/ready'" in route
    assert "readiness.ready !== true" in route
    assert "readiness.status !== 'ready'" in route
    assert "configuration !== 'ready'" in route
    assert "database !== 'ready'" in route
    assert "'cache-control': 'no-store'" in route
    assert "status: 503" in route
    assert "followRedirects: false" in route
    assert "proxyToBackend(nextRequest, '/api/health'" not in route


def test_main_quality_backend_fetches_full_history_for_provenance() -> None:
    workflow = MAIN_QUALITY_WORKFLOW.read_text(encoding="utf-8")
    backend = workflow.split("  backend-quality:", 1)[1].split("  frontend-quality:", 1)[0]

    assert "uses: actions/checkout@v4" in backend
    assert "fetch-depth: 0" in backend
