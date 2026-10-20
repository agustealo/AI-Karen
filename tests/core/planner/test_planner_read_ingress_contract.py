"""Planner ingress is read-only and derives security scope from auth."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUTE = ROOT / "src/ai_karen_engine/api_routes/planner.py"


def test_planner_ingress_never_accepts_untrusted_tenant_scope():
    source = ROUTE.read_text()
    assert "Depends(get_current_user)" in source
    assert "UUID(str(user.tenant_id))" in source
    assert "UUID(str(user.user_id))" in source
    assert "PlannerNotFoundError" in source
    assert '@router.get("/commitments/{commitment_id}"' in source
    assert "@router.post(" not in source
    assert "@router.patch(" not in source
    assert "@router.delete(" not in source
