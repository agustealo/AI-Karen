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


def test_supabase_health_reports_credential_source_without_key_material(monkeypatch):
    monkeypatch.setenv("SUPABASE_PROJECT_URL", "https://current.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_sensitive_test")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_public_test")
    client = SupabasePlatformClient()
    client.initialize()
    health = client.health_metadata()
    assert health["credential_source"] == "SUPABASE_SECRET_KEY"
    assert "sb_secret_sensitive_test" not in str(health)
    assert "sb_publishable_public_test" not in str(health)
    client.reset()
    assert client.health_metadata()["credential_source"] is None


def test_supabase_legacy_warning_tracks_effective_selection_only(monkeypatch, caplog):
    monkeypatch.setenv("SUPABASE_PROJECT_URL", "https://current.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_modern")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "old_anon_secret_value")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    client = SupabasePlatformClient()
    with caplog.at_level("WARNING"):
        client.initialize()
    assert client.health_metadata()["credential_source"] == "SUPABASE_PUBLISHABLE_KEY"
    assert "legacy key source" not in caplog.text
    assert "old_anon_secret_value" not in caplog.text

    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY")
    with caplog.at_level("WARNING"):
        client.initialize()
    assert client.health_metadata()["credential_source"] == "SUPABASE_ANON_KEY"
    assert "legacy key source: SUPABASE_ANON_KEY" in caplog.text
    assert "old_anon_secret_value" not in caplog.text
