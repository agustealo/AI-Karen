"""SQLAlchemy model for tenant-scoped memory entity aliases."""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .ledger_models import Base


class MemoryEntityAlias(Base):
    __tablename__ = "memory_entity_alias"

    alias_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_entity.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    alias_text = Column(Text, nullable=False)
    normalized_alias = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    source_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "normalized_alias",
            "entity_id",
            name="uq_memory_entity_alias",
        ),
        Index("idx_memory_entity_alias_scope", "tenant_id", "user_id", "entity_id"),
    )


__all__ = ["MemoryEntityAlias"]
