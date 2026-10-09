"""Supabase platform picks current env keys without exposing privileged credentials."""
from ai_karen_engine.integrations.supabase_client import SupabasePlatformClient


def test_current_supabase_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("SUPABASE_PROJECT_URL", "https://current.supabase.co")
    monkeypatch.setenv("SUPABASE_URL", "https://legacy.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "old_anon_test")
    client = SupabasePlatformClient()
    client.initialize()
    assert client.url == "https://current.supabase.co"
    assert client.key == "sb_secret_test"
    assert "sb_secret_test" not in str(client.health_metadata())


def test_legacy_configuration_is_still_accepted_during_migration(monkeypatch):
    for name in ("SUPABASE_PROJECT_URL", "SUPABASE_SECRET_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPABASE_URL", "https://legacy.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "old_anon_test")
    client = SupabasePlatformClient()
    client.initialize()
    assert client.url == "https://legacy.supabase.co"
    assert client.key == "old_anon_test"
