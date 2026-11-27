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

def test_private_storage_tls_policy_rejects_incomplete_and_foreign_origin(monkeypatch):
    import certifi
    import pytest
    from ai_karen_engine.config.artifact_storage import StorageTLSPolicy

    origin = "https://storage.example.test:8443"
    monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_ORIGIN", origin)
    monkeypatch.delenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", raising=False)
    with pytest.raises(ValueError, match="origin and CA"):
        StorageTLSPolicy.from_environment(origin)
    monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", certifi.where())
    with pytest.raises(ValueError, match="does not match"):
        StorageTLSPolicy.from_environment("https://other.example.test:8443")
    policy = StorageTLSPolicy.from_environment(origin)
    assert policy is not None
    for foreign in ("http://storage.example.test:8443", "https://storage.example.test:8444",
                    "https://other.example.test:8443", "https://user@storage.example.test:8443"):
        with pytest.raises(ValueError):
            policy.require_destination(foreign)
    policy.require_destination(origin + "/storage/v1/object/sign/artifacts/content")


def test_private_storage_tls_real_sdk_uses_origin_bound_http_client(monkeypatch):
    import ssl
    import certifi
    import httpx
    import pytest
    import supabase  # Load the pinned SDK before instrumenting its HTTP transport.
    from ai_karen_engine.integrations import supabase_client as module

    assert callable(supabase.create_client)
    origin = "https://storage.example.test:8443"
    monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_ORIGIN", origin)
    monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", certifi.where())
    requests = []
    created = []
    real_client = httpx.Client

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"signedURL": "/object/sign/artifacts/content?token=fixture"})

    def instrument(*args, **kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        assert kwargs["verify"].verify_mode == ssl.CERT_REQUIRED
        assert kwargs["verify"].check_hostname
        client = real_client(*args, transport=httpx.MockTransport(respond), **kwargs)
        created.append((client, kwargs["verify"]))
        return client

    monkeypatch.setattr(module.httpx, "Client", instrument)
    platform = module.SupabasePlatformClient()
    try:
        platform.initialize(origin, "fixture-key")
        assert platform.storage is not None
        assert platform.storage_tls_policy is not None
        assert platform.storage_tls_policy.verify_for_origin(origin) is created[0][1]
        signed = platform.storage.from_("artifacts").create_signed_url("content", 60)
        assert signed["signedURL"] == origin + "/storage/v1/object/sign/artifacts/content?token=fixture"
        assert len(requests) == 1
        assert requests[0].headers["apikey"] == "fixture-key"
        assert requests[0].method == "POST"
        with pytest.raises(ValueError, match="destination"):
            created[0][0].get("https://foreign.example.test")
        assert len(requests) == 1
    finally:
        platform.reset()
    assert created[0][0].is_closed
