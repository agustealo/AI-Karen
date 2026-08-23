"""Tests for Row Level Security and tenant scoping in canonical repositories."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest

from ai_karen_engine.services.database.repositories import (
    ArtifactUploadRequest,
    ConversationQuery,
    MemoryItem,
    MemoryQuery,
    PostgresConversationRepository,
    PostgresMemoryRepository,
    RepositoryFactory,
)
from ai_karen_engine.services.database.repositories.conversation_repository import Conversation, Message
from ai_karen_engine.services.database.repositories.base import RepositoryResult


def _tenant_id() -> str:
    return str(uuid.uuid4())


def _user_id() -> str:
    return str(uuid.uuid4())


class TestPostgresMemoryRepositoryTenantScoping:
    """Validate tenant isolation for MemoryRepository."""

    @pytest.fixture
    def repo(self, async_session_factory):
        return PostgresMemoryRepository(session_factory=async_session_factory)

    @pytest.mark.asyncio
    async def test_store_and_get_memory_tenant_scoped(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()
        user_a = _user_id()

        item = MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=user_a,
            content="tenant-a-secret",
            memory_type="episodic",
        )
        result = await repo.store_memory(item)
        assert result.success is True

        fetched = await repo.get_memory(item.id, tenant_a)
        assert fetched.success is True
        assert fetched.data is not None
        assert fetched.data.content == "tenant-a-secret"

        wrong_tenant = await repo.get_memory(item.id, tenant_b)
        assert wrong_tenant.success is True
        assert wrong_tenant.data is None

    @pytest.mark.asyncio
    async def test_search_does_not_leak_across_tenants(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()

        item_a = MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=_user_id(),
            content="alpha",
            embedding=[0.1, 0.2, 0.3],
        )
        item_b = MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_b,
            user_id=_user_id(),
            content="beta",
            embedding=[0.4, 0.5, 0.6],
        )
        await repo.store_memory(item_a)
        await repo.store_memory(item_b)

        query = MemoryQuery(tenant_id=tenant_a, text="alpha", top_k=10)
        results = await repo.search_keyword(query)
        assert results.success is True
        contents = [r.item.content for r in results.data]
        assert "alpha" in contents
        assert "beta" not in contents

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other_tenant(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()

        item_a = MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=_user_id(),
            content="to-delete",
        )
        item_b = MemoryItem(
            id=str(uuid.uuid4()),
            tenant_id=tenant_b,
            user_id=_user_id(),
            content="keep-me",
        )
        await repo.store_memory(item_a)
        await repo.store_memory(item_b)

        delete_result = await repo.delete_memory(item_a.id, tenant_a)
        assert delete_result.success is True

        still_exists = await repo.get_memory(item_a.id, tenant_a)
        assert still_exists.data is None

        other_tenant_item = await repo.get_memory(item_b.id, tenant_b)
        assert other_tenant_item.data is not None


class TestPostgresConversationRepositoryTenantScoping:
    """Validate tenant isolation for ConversationRepository."""

    @pytest.fixture
    def repo(self, async_session_factory):
        return PostgresConversationRepository(session_factory=async_session_factory)

    @pytest.mark.asyncio
    async def test_create_and_get_conversation_tenant_scoped(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()

        conv = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=_user_id(),
            title="tenant-a-chat",
        )
        result = await repo.create_conversation(conv)
        assert result.success is True

        fetched = await repo.get_conversation(conv.id, tenant_a)
        assert fetched.success is True
        assert fetched.data is not None
        assert fetched.data.title == "tenant-a-chat"

        wrong_tenant = await repo.get_conversation(conv.id, tenant_b)
        assert wrong_tenant.success is True
        assert wrong_tenant.data is None

    @pytest.mark.asyncio
    async def test_messages_scoped_to_conversation_tenant(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()

        conv = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=_user_id(),
            title="scoped-chat",
        )
        await repo.create_conversation(conv)

        msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            tenant_id=tenant_a,
            role="user",
            content="hello",
        )
        await repo.add_message(msg)

        messages = await repo.get_messages(conv.id, tenant_a)
        assert messages.success is True
        assert len(messages.data) == 1

        wrong_tenant_messages = await repo.get_messages(conv.id, tenant_b)
        assert wrong_tenant_messages.success is True
        assert len(wrong_tenant_messages.data) == 0

    @pytest.mark.asyncio
    async def test_delete_conversation_tenant_scoped(self, repo):
        tenant_a = _tenant_id()
        tenant_b = _tenant_id()

        conv_a = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a,
            user_id=_user_id(),
            title="delete-me",
        )
        conv_b = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant_b,
            user_id=_user_id(),
            title="keep-me",
        )
        await repo.create_conversation(conv_a)
        await repo.create_conversation(conv_b)

        result = await repo.delete_conversation(conv_a.id, tenant_a)
        assert result.success is True

        assert (await repo.get_conversation(conv_a.id, tenant_a)).data is None
        assert (await repo.get_conversation(conv_b.id, tenant_b)).data is not None


class TestRepositoryFactory:
    """Validate repository factory wiring."""

    def test_create_memory_repository(self):
        factory = RepositoryFactory(session_factory=lambda: None)
        repo = factory.create_memory_repository()
        assert isinstance(repo, PostgresMemoryRepository)

    def test_create_conversation_repository(self):
        factory = RepositoryFactory(session_factory=lambda: None)
        repo = factory.create_conversation_repository()
        assert isinstance(repo, PostgresConversationRepository)
