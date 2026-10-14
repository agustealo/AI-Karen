"""Runtime article DI must use existing configured authority, without fake storage."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from ai_karen_engine.services.database.repositories import repository_factory


def test_article_service_disabled_without_storage(monkeypatch):
    platform = SimpleNamespace(storage=None)
    monkeypatch.setattr(
        "ai_karen_engine.integrations.supabase_client.get_supabase_platform",
        lambda: platform,
    )
    db = MagicMock()
    monkeypatch.setattr(
        "ai_karen_engine.database.factory.get_database_client", db
    )
    assert repository_factory.get_runtime_search_article_service() is None
    db.assert_not_called()


def test_article_service_uses_canonical_repository_factory(monkeypatch):
    platform = SimpleNamespace(storage=object())
    db = SimpleNamespace(get_async_session=lambda: None)
    monkeypatch.setattr(
        "ai_karen_engine.integrations.supabase_client.get_supabase_platform",
        lambda: platform,
    )
    monkeypatch.setattr(
        "ai_karen_engine.database.factory.get_database_client", lambda: db
    )
    artifact = object()
    constructor = MagicMock(return_value=SimpleNamespace(create_artifact_store=lambda: artifact))
    monkeypatch.setattr(repository_factory, "RepositoryFactory", constructor)
    result = repository_factory.get_runtime_search_article_service()
    assert result._artifacts is artifact
    assert constructor.call_args.kwargs["storage_client"] is platform
    assert constructor.call_args.kwargs["session_factory"] == db.get_async_session
