"""Supabase key config tests."""

from __future__ import annotations

import os
import pytest

from ai_karen_engine.core.config.supabase.keys import (
    SupabaseKeyConfig,
    load_supabase_key_config,
)


def test_supabase_key_config_requires_project_url():
    with pytest.raises(ValueError):
        SupabaseKeyConfig(project_url="")


def test_supabase_key_config_requires_publishable_key():
    with pytest.raises(ValueError):
        SupabaseKeyConfig(project_url="https://example.supabase.co", publishable_key="")


def test_supabase_key_config_requires_secret_key():
    with pytest.raises(ValueError):
        SupabaseKeyConfig(
            project_url="https://example.supabase.co",
            publishable_key="anon",
            secret_key="",
        )


def test_load_supabase_key_config_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_PROJECT_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "secret-key")
    config = load_supabase_key_config()
    assert config.project_url == "https://example.supabase.co"
    assert config.publishable_key == "anon-key"
    assert config.secret_key == "secret-key"


def test_load_supabase_key_config_legacy_aliases(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "secret-key")
    config = load_supabase_key_config()
    assert config.project_url == "https://example.supabase.co"
    assert config.publishable_key == "anon-key"
    assert config.secret_key == "secret-key"
    assert config.has_legacy_keys is True
