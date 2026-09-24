from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "src/ai_karen_engine/api_routes/models/model_orchestrator.py"
SERVER_ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"


def test_model_orchestrator_route_has_no_duplicate_state_or_dead_security_authority():
    source = ROUTE.read_text(encoding="utf-8")

    forbidden = (
        "_active_jobs",
        "BackgroundTasks",
        "get_security_manager",
        "ModelSecurityManager",
        "_handle_model_download",
        "_handle_migration",
        "_handle_ensure_models",
        "_handle_garbage_collection",
        "_emit_job_update",
        "orchestrator_registry.json",
        "ModelOrchestratorService(config)",
        "ModelOrchestratorService({",
        '@router.get("/jobs',
        '@router.post("/jobs',
        '@router.post("/migrate")',
        '@router.post("/ensure")',
        '@router.post("/gc")',
        '@router.post("/security/',
        '@router.get("/security/',
        '@router.post("/license/',
        '@router.get("/license/',
        '@router.get("/registry")',
        '@router.get("/compatibility/',
    )
    for token in forbidden:
        assert token not in source


def test_model_orchestrator_route_keeps_only_canonical_job_control_surface():
    source = ROUTE.read_text(encoding="utf-8")

    assert "get_model_download_control_service" in source
    assert '@router.get("/download/jobs"' in source
    assert '@router.get("/download/jobs/{job_id}"' in source
    assert '@router.post("/download/jobs/{job_id}/cancel"' in source
    assert '@router.post("/download/jobs/{job_id}/pause"' in source
    assert '@router.post("/download/jobs/{job_id}/resume"' in source
    assert '@router.post("/download"' in source
    assert '@router.delete("/remove/{model_id:path}"' in source


def test_model_orchestrator_route_reuses_control_service_orchestrator_and_audits_removal():
    source = ROUTE.read_text(encoding="utf-8")

    assert "return _control_service()._orchestrator" in source
    assert "get_audit_logger().log_audit_event" in source
    assert '"message": "model_remove"' in source
    assert '"outcome": outcome' in source


def test_model_orchestrator_router_is_admin_scoped_at_application_boundary():
    source = SERVER_ROUTERS.read_text(encoding="utf-8")

    assert "async def require_runtime_admin" in source
    assert "model_orchestrator_router" in source
    assert "dependencies=(Depends(require_runtime_admin),)" in source
    assert "app.dependency_overrides[model_orchestrator_current_user] = require_runtime_admin" in source
