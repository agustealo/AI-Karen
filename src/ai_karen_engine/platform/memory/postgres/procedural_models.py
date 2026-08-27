"""SQLAlchemy model for canonical durable procedural-memory projection."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from .ledger_models import Base


class MemoryProcedure(Base):
    """Durable reusable procedure derived from governed memory events."""

    __tablename__ = "memory_procedure"

    procedure_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(255), nullable=False)
    trigger_patterns = Column(JSONB, default=lambda: [], nullable=False)
    tool_sequence = Column(JSONB, default=lambda: [], nullable=False)
    success_count = Column(BigInteger, default=0, nullable=False)
    failure_count = Column(BigInteger, default=0, nullable=False)
    confidence = Column(Float, default=0.0, nullable=False)
    lifecycle_state = Column(String(50), default="active", nullable=False)
    valid_from = Column(DateTime, default=datetime.utcnow, nullable=False)
    valid_to = Column(DateTime, nullable=True)
    metadata_payload = Column(JSONB, default=lambda: {}, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_memory_procedure_tenant_user",
            "tenant_id",
            "user_id",
            "lifecycle_state",
            "updated_at",
        ),
        Index("idx_memory_procedure_source_event", "source_event_id"),
        Index("idx_memory_procedure_validity", "valid_from", "valid_to"),
    )


__all__ = ["MemoryProcedure"]
