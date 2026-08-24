"""SQLAlchemy-backed repository implementations."""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.persistence.postgres import get_postgres_engine
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

logger = logging.getLogger(__name__)


class SqlConversationRepository:
    """PostgreSQL-backed conversation repository."""

    async def get_conversation(
        self, conversation_id: UUID, tenant_id: UUID
    ) -> Optional[Any]:
        from ai_karen_engine.database.models import TenantConversation

        async with async_transaction_scope(tenant_id) as session:
            stmt = select(TenantConversation).where(
                TenantConversation.id == conversation_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_conversations(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID] = None,
        *,
        limit: int = 50,
        offset: int = 0,
        active_only: bool = True,
    ) -> Sequence[Any]:
        from ai_karen_engine.database.models import TenantConversation

        async with async_transaction_scope(tenant_id) as session:
            stmt = select(TenantConversation)
            if user_id is not None:
                stmt = stmt.where(TenantConversation.user_id == user_id)
            if active_only:
                stmt = stmt.where(TenantConversation.is_active.is_(True))
            stmt = stmt.order_by(TenantConversation.updated_at.desc())
            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            return result.scalars().all()

    async def create_conversation(
        self, tenant_id: UUID, user_id: UUID, **kwargs: Any
    ) -> Any:
        from ai_karen_engine.database.models import TenantConversation

        async with async_transaction_scope(tenant_id) as session:
            conversation = TenantConversation(user_id=user_id, **kwargs)
            session.add(conversation)
            await session.flush()
            await session.refresh(conversation)
            return conversation

    async def add_message(
        self,
        conversation_id: UUID,
        tenant_id: UUID,
        role: str,
        content: str,
        **kwargs: Any,
    ) -> Any:
        from ai_karen_engine.database.models import TenantMessage

        async with async_transaction_scope(tenant_id) as session:
            message = TenantMessage(
                conversation_id=conversation_id,
                role=role,
                content=content,
                **kwargs,
            )
            session.add(message)
            await session.flush()
            await session.refresh(message)
            return message

    async def list_messages(
        self, conversation_id: UUID, tenant_id: UUID
    ) -> Sequence[Any]:
        from ai_karen_engine.database.models import TenantMessage

        async with async_transaction_scope(tenant_id) as session:
            stmt = (
                select(TenantMessage)
                .where(TenantMessage.conversation_id == conversation_id)
                .order_by(TenantMessage.created_at.asc())
            )
            result = await session.execute(stmt)
            return result.scalars().all()


class SqlMemoryRepository:
    """PostgreSQL-backed memory repository."""

    async def store_memory(
        self, tenant_id: UUID, user_id: UUID, **kwargs: Any
    ) -> Any:
        from ai_karen_engine.database.models import TenantMemoryItem

        async with async_transaction_scope(tenant_id) as session:
            item = TenantMemoryItem(
                tenant_id=tenant_id, user_id=user_id, **kwargs
            )
            session.add(item)
            await session.flush()
            await session.refresh(item)
            return item

    async def search_memories(
        self,
        tenant_id: UUID,
        user_id: UUID,
        query: str,
        *,
        limit: int = 10,
    ) -> Sequence[Any]:
        from ai_karen_engine.database.models import TenantMemoryItem

        async with async_transaction_scope(tenant_id) as session:
            stmt = (
                select(TenantMemoryItem)
                .where(
                    TenantMemoryItem.tenant_id == tenant_id,
                    TenantMemoryItem.user_id == user_id,
                    TenantMemoryItem.content.ilike(f"%{query}%"),
                )
                .order_by(TenantMemoryItem.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_memory(
        self, memory_id: UUID, tenant_id: UUID
    ) -> Optional[Any]:
        from ai_karen_engine.database.models import TenantMemoryItem

        async with async_transaction_scope(tenant_id) as session:
            stmt = select(TenantMemoryItem).where(
                TenantMemoryItem.id == memory_id,
                TenantMemoryItem.tenant_id == tenant_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()


class SqlTenantRepository:
    """PostgreSQL-backed tenant repository."""

    async def get_tenant(self, tenant_id: UUID) -> Optional[Any]:
        from ai_karen_engine.database.models import Tenant

        async with async_transaction_scope() as session:
            stmt = select(Tenant).where(Tenant.id == tenant_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_tenant_by_slug(self, slug: str) -> Optional[Any]:
        from ai_karen_engine.database.models import Tenant

        async with async_transaction_scope() as session:
            stmt = select(Tenant).where(Tenant.slug == slug)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def create_tenant(self, **kwargs: Any) -> Any:
        from ai_karen_engine.database.models import Tenant

        async with async_transaction_scope() as session:
            tenant = Tenant(**kwargs)
            session.add(tenant)
            await session.flush()
            await session.refresh(tenant)
            return tenant

    async def list_tenants(
        self, *, limit: int = 50, offset: int = 0
    ) -> Sequence[Any]:
        from ai_karen_engine.database.models import Tenant

        async with async_transaction_scope() as session:
            stmt = (
                select(Tenant)
                .where(Tenant.is_active.is_(True))
                .order_by(Tenant.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await session.execute(stmt)
            return result.scalars().all()


class SqlAuditRepository:
    """PostgreSQL-backed audit log repository."""

    async def record_event(
        self,
        tenant_id: Optional[str],
        action: str,
        *,
        user_id: Optional[str] = None,
        actor_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Any:
        from ai_karen_engine.database.models import AuditLog

        async with async_transaction_scope() as session:
            event = AuditLog(
                tenant_id=tenant_id,
                action=action,
                user_id=user_id,
                actor_type=actor_type,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
            )
            session.add(event)
            await session.flush()
            await session.refresh(event)
            return event

    async def list_events(
        self,
        tenant_id: Optional[str] = None,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Any]:
        from ai_karen_engine.database.models import AuditLog

        async with async_transaction_scope() as session:
            stmt = select(AuditLog)
            if tenant_id is not None:
                stmt = stmt.where(AuditLog.tenant_id == tenant_id)
            stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return result.scalars().all()


__all__ = [
    "SqlConversationRepository",
    "SqlMemoryRepository",
    "SqlTenantRepository",
    "SqlAuditRepository",
]
