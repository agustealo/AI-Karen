from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAIN_QUALITY_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/main-quality-gate.yml"
PRESENTATION_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/presentation-contract.yml"
AUTOMATION_STATS_ROUTE = (
    REPOSITORY_ROOT / "src/ai_karen_engine/api_routes/automation/stats.py"
)
CANONICAL_VERIFIER_COMMAND = (
    "python scripts/ci/verify_presentation_assets.py --require-assets"
)
AUTOMATION_STATS_PATH = "src/ai_karen_engine/api_routes/automation/stats.py"


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


def test_presentation_gate_tracks_backend_stats_truth_owner() -> None:
    presentation = PRESENTATION_WORKFLOW.read_text(encoding="utf-8")

    assert presentation.count(AUTOMATION_STATS_PATH) == 2


def test_automation_stats_do_not_present_global_agents_as_tenant_truth() -> None:
    source = AUTOMATION_STATS_ROUTE.read_text(encoding="utf-8")

    assert "get_agent_integration_service" not in source
    assert "get_all_agents" not in source
    assert '"activeAgents": "Unavailable"' in source
    assert '"scope": "tenant"' in source
    assert '"reason": "canonical_tenant_agent_inventory_unavailable"' in source
    assert "get_tasks_summary(tenant_id)" in source
    assert "get_cron_summary(tenant_id)" in source
    assert "job_service.list_jobs(user)" in source
