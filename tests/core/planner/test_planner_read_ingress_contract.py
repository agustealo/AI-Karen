"""Planner ingress is read-only and derives security scope from auth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUTE = ROOT / "src/ai_karen_engine/api_routes/planner.py"


def test_planner_ingress_never_accepts_untrusted_tenant_scope():
    source = ROUTE.read_text()
    assert "Depends(get_current_user)" in source
    assert "PersonalPlannerService().get(user=user, commitment_id=commitment_id)" in source
    assert "PlannerNotFoundError" in source
    assert '@router.get("/commitments/{commitment_id}"' in source
    assert "@router.post(" not in source
    assert "@router.patch(" not in source
    assert "@router.delete(" not in source



def test_canonical_router_gate_defaults_off():
    settings = (ROOT / "src/ai_karen_engine/server/config.py").read_text()
    registry = (ROOT / "src/ai_karen_engine/server/routers.py").read_text()
    assert 'enable_personal_planner_read_api: bool = Field(default=False' in settings
    assert 'validation_alias="KAREN_ENABLE_PERSONAL_PLANNER_READ_API"' in settings
    assert "if settings.enable_personal_planner_read_api:" in registry
    assert "app.include_router(personal_planner_router)" in registry
    assert "RouterSpec(personal_planner_router" not in registry
