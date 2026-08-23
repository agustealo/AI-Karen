"""Supabase / persistence config tests."""

from __future__ import annotations

import pytest

from ai_karen_engine.config.database import (
    SupabaseSettings,
    PostgresSettings,
    PoolSettings,
    DatabaseSettings,
    get_database_settings,
    refresh_database_settings,
)


def test_supabase_settings_accepts_explicit_values():
    s = SupabaseSettings(
        project_url="https://example.supabase.co",
        publishable_key="pub",
        secret_key="sec",
    )
    assert s.project_url == "https://example.supabase.co"
    assert s.publishable_key == "pub"
    assert s.secret_key == "sec"
    assert s.public_api_url == "https://example.supabase.co/rest/v1"


def test_supabase_settings_hides_secrets_in_repr():
    s = SupabaseSettings(
        project_url="https://example.supabase.co",
        publishable_key="mypubkey",
        secret_key="mysecretkey",
    )
    r = repr(s)
    # Secret values must not appear
    assert "mypubkey" not in r
    assert "mysecretkey" not in r
    # Values should be masked
    assert "='***'" in r
    # Project url should be visible
    assert "example.supabase.co" in r


def test_load_supabase_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_PROJECT_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    s = SupabaseSettings()
    assert s.project_url == "https://example.supabase.co"
    assert s.publishable_key == "anon-key"
    assert s.secret_key == "secret-key"
    assert s.has_legacy_keys is False


def test_load_supabase_from_legacy_env_aliases(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-key")
    s = SupabaseSettings()
    assert s.project_url == "https://example.supabase.co"
    assert s.publishable_key == "anon-key"
    assert s.secret_key == "secret-key"


def test_postgres_settings_builds_url():
    p = PostgresSettings(
        host="db.example.com",
        port=5432,
        user="karen",
        password="p@ss",
        database="karen_db",
    )
    url = p.build_database_url()
    assert url.startswith("postgresql://karen:p%40ss@db.example.com:5432/karen_db")


def test_postgres_settings_builds_async_url():
    p = PostgresSettings(database_url="postgresql://u:p@h:5432/d")
    assert p.build_async_database_url() == "postgresql+asyncpg://u:p@h:5432/d"


def test_postgres_settings_validation():
    p = PostgresSettings(host="h", user="u", database="d")
    assert p.is_valid() is True
    p2 = PostgresSettings(host="", user="u", database="d")
    assert p2.is_valid() is False
    p3 = PostgresSettings(host="h", user="u", database="not valid!")
    assert p3.is_valid() is False


def test_postgres_settings_sanitized_output():
    p = PostgresSettings(user="u", password="secret", database="d")
    s = p.get_sanitized()
    assert "secret" not in s["url"]
    assert s["user"] == "u"


def test_pool_settings_defaults():
    p = PoolSettings()
    assert p.pool_size == 10
    assert p.max_overflow == 20
    assert p.pool_recycle == 3600
    assert p.pool_pre_ping is True


def test_database_settings_defaults():
    db = DatabaseSettings()
    assert db.supabase_auth_enabled is False
    assert db.supabase_realtime_enabled is True
    assert db.supabase_storage_enabled is True
    assert db.migrations_authority == "local"
    assert db.rls_enforced is True


def test_database_settings_migrations_authority_validation():
    with pytest.raises(ValueError):
        DatabaseSettings(migrations_authority="invalid")


def test_get_database_settings_singleton():
    a = get_database_settings()
    b = get_database_settings()
    assert a is b
    c = refresh_database_settings()
    assert c is not a
