"""Guard the Supabase Storage import dependency and preflight contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_supabase_client_sdk_is_a_pinned_runtime_dependency():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "supabase==2.32.0" in requirements


def test_preflight_checks_sdk_factory_not_only_namespace():
    source = (ROOT / "scripts/api_dependency_preflight.py").read_text(encoding="utf-8")
    assert 'dependency("supabase", "supabase")' in source
    assert "from supabase import create_client" in source
    assert '"create_client_available"' in source
    assert "and supabase_ok and rbac_ok" in source
