"""The container must install the real Supabase SDK rather than import the repo namespace."""

from pathlib import Path


def test_supabase_sdk_dependency_is_pinned_for_api_image():
    root = Path(__file__).resolve().parents[2]
    requirements = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "supabase==2.32.0" in requirements


def test_supabase_preflight_checks_factory_not_just_module_presence():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/api_dependency_preflight.py").read_text(encoding="utf-8")
    assert 'dependency("supabase", "supabase")' in script
    assert "callable(create_client)" in script
    assert '"supabase_sdk_ready"' in script
