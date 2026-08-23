"""
SUPABASE-PLATFORM-1 Phase B smoke test.

Verifies end-to-end wiring of Supabase platform capabilities
into the KAREN runtime without requiring actual Supabase credentials.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import List

logging.basicConfig(level=logging.WARNING)


def test_id_types() -> None:
    from ai_karen_engine.database.id_types import (
        TenantId,
        UserId,
        coerce_user_id,
        coerce_tenant_id,
    )
    test_uuid = uuid.uuid4()
    assert coerce_user_id(test_uuid) is test_uuid
    assert coerce_user_id("admin") == uuid.uuid5(uuid.NAMESPACE_URL, "ai-karen:user:admin")
    assert coerce_user_id(None) == uuid.UUID("00000000-0000-0000-0000-000000000000")
    print("[OK] ID types")


def test_migrations() -> None:
    from ai_karen_engine.database.migration_manager import SCHEMA_MIGRATIONS
    assert "012_embedding_provenance.sql" in SCHEMA_MIGRATIONS
    assert "013_rls_expansion.sql" in SCHEMA_MIGRATIONS
    assert len(SCHEMA_MIGRATIONS) == 12
    print("[OK] Migrations")


def test_platform_bootstrap() -> None:
    from ai_karen_engine.integrations.supabase_client import get_supabase_platform
    platform = get_supabase_platform()
    assert platform._initialized
    assert platform.storage is None  # not configured
    assert platform.publisher is None  # not configured
    assert platform.queue is not None  # noop always available
    print("[OK] Platform bootstrap")


def test_realtime_contract() -> None:
    from ai_karen_engine.services.database.repositories.realtime_publisher import (
        RealtimePublisher,
        RealtimeEvent,
    )
    from ai_karen_engine.services.database.repositories.realtime_topic_factory import (
        RealtimeTopicFactory,
    )
    from ai_karen_engine.services.database.repositories.realtime_event_registry import (
        realtime_events,
    )
    from ai_karen_engine.services.database.repositories.realtime_accessor import (
        get_realtime_publisher,
        is_realtime_available,
        publish,
        publish_conversation_event,
        publish_user_event,
    )
    assert RealtimeTopicFactory.user_topic("t1", "u1") == "tenant:t1:user:u1"
    assert RealtimeTopicFactory.is_private("tenant:t1:user:u1") is True
    assert realtime_events.get("conversation.message.created") is not None
    assert get_realtime_publisher() is None
    assert is_realtime_available() is False
    print("[OK] Realtime contract")


def test_queue_contract() -> None:
    from ai_karen_engine.services.database.repositories.queue_client import (
        QueueClient,
        QueueItem,
    )
    from ai_karen_engine.services.database.repositories.noop_queue_client import (
        NoopQueueClient,
    )
    from ai_karen_engine.services.database.repositories.queue_accessor import (
        get_queue_client,
        is_queue_available,
        enqueue,
    )
    client = NoopQueueClient()
    assert client is not None
    assert is_queue_available() is True
    print("[OK] Queue contract")


def test_artifact_lifecycle() -> None:
    from ai_karen_engine.services.database.repositories.artifact_store import (
        ArtifactStore,
        Artifact,
        ArtifactUploadRequest,
    )
    from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
        SupabaseArtifactStore,
    )
    assert hasattr(ArtifactStore, "archive")
    assert hasattr(ArtifactStore, "restore")
    assert hasattr(ArtifactStore, "list_archived")
    assert hasattr(ArtifactStore, "purge")
    artifact = Artifact(id="1", tenant_id="t", user_id="u")
    assert artifact.deleted_at is None
    print("[OK] Artifact lifecycle")


def test_canonical_repositories() -> None:
    from ai_karen_engine.database.factory import DatabaseServiceFactory
    factory = DatabaseServiceFactory()
    factory.create_canonical_repositories()
    assert factory.get_service("memory_repository") is not None
    assert factory.get_service("conversation_repository") is not None
    assert factory.get_service("artifact_store") is not None
    print("[OK] Canonical repositories")


def test_api_routes() -> None:
    from ai_karen_engine.api_routes.artifacts import router
    routes = [route.path for route in router.routes]
    assert "/artifacts/upload" in routes
    assert "/artifacts/{artifact_id}" in routes
    assert "/artifacts/{artifact_id}/archive" in routes
    assert "/artifacts/{artifact_id}/restore" in routes
    assert "/artifacts/archived" in routes
    assert "/artifacts/{artifact_id}/purge" in routes
    print("[OK] API routes")


async def test_async_operations() -> None:
    from ai_karen_engine.services.database.repositories.noop_queue_client import (
        NoopQueueClient,
    )
    from ai_karen_engine.services.database.repositories.queue_accessor import enqueue
    from ai_karen_engine.services.database.repositories.queue_client import QueueItem

    client = NoopQueueClient()
    result = await client.enqueue(QueueItem(id="test", queue="test", payload={}))
    assert result.success
    assert result.data == "test"

    item_id = await enqueue("test", {"key": "value"})
    assert item_id is not None
    print("[OK] Async operations")


def main() -> None:
    test_id_types()
    test_migrations()
    test_platform_bootstrap()
    test_realtime_contract()
    test_queue_contract()
    test_artifact_lifecycle()
    test_canonical_repositories()
    test_api_routes()
    asyncio.run(test_async_operations())
    print("\nSUPABASE-PLATFORM-1 Phase B smoke test: ALL PASSED")


if __name__ == "__main__":
    main()
