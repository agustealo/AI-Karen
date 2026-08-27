"""Canonical PostgreSQL memory ledger models for AI Karen Engine."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class MemoryEvent(Base):
    """Canonical system of record for memory mutations."""

    __tablename__ = "memory_event"

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    source_type = Column(String(100), nullable=False)
    source_ref = Column(String(255), nullable=True)
    payload_hash = Column(String(64), nullable=False)
    idempotency_key = Column(String(255), nullable=True)
    confidence = Column(Float, default=1.0)
    scope = Column(String(100), default="user")
    sensitivity_class = Column(String(50), default="normal")
    consent_state = Column(String(50), default="granted")
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_to = Column(DateTime, nullable=True)
    supersedes = Column(UUID(as_uuid=True), nullable=True)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_memory_event_user_tenant", "user_id", "tenant_id"),
        Index("idx_memory_event_created", "created_at"),
        UniqueConstraint("idempotency_key", name="uq_memory_event_idempotency"),
    )


class MemoryAssertion(Base):
    """Durable state representation of an accepted memory assertion."""

    __tablename__ = "memory_assertion"

    assertion_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    scope = Column(String(100), default="user")
    sensitivity_class = Column(String(50), default="normal")
    consent_state = Column(String(50), default="granted")
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_to = Column(DateTime, nullable=True)
    supersedes = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_memory_assertion_user_tenant", "user_id", "tenant_id"),
        Index("idx_memory_assertion_validity", "valid_from", "valid_to"),
    )


class MemoryEpisode(Base):
    """Event and task-specific continuity snapshot."""

    __tablename__ = "memory_episode"

    episode_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    session_id = Column(String(255), nullable=True)
    summary = Column(Text, nullable=False)
    snapshot_data = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_memory_episode_user_tenant", "user_id", "tenant_id"),
    )


class ProfileFact(Base):
    """Stable user and organizational facts."""

    __tablename__ = "profile_fact"

    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    category = Column(String(100), nullable=False)
    attribute = Column(String(255), nullable=False)
    value = Column(JSONB, nullable=False)
    confidence = Column(Float, default=1.0)
    source_type = Column(String(100), nullable=False)
    source_ref = Column(String(255), nullable=True)
    valid_from = Column(DateTime, default=datetime.utcnow)
    valid_to = Column(DateTime, nullable=True)
    supersedes = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_profile_fact_user_category", "user_id", "category"),
    )


class MemoryEntity(Base):
    """Canonical entity identity used by the memory graph projection."""

    __tablename__ = "memory_entity"

    entity_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    canonical_text = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=False)
    entity_type = Column(String(100), nullable=True)
    metadata_payload = Column(JSONB, default=lambda: {}, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_memory_entity_tenant_user_normalized",
            "tenant_id",
            "user_id",
            "normalized_text",
        ),
        Index("idx_memory_entity_tenant_type", "tenant_id", "entity_type"),
    )


class MemoryRelation(Base):
    """Rebuildable temporal/associative relationship projection."""

    __tablename__ = "memory_relation"

    relation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    source_id = Column(UUID(as_uuid=True), nullable=False)
    target_id = Column(UUID(as_uuid=True), nullable=False)
    relation_type = Column(String(100), nullable=False)
    metadata_payload = Column(JSONB, default=lambda: {}, nullable=False)
    valid_from = Column(DateTime, nullable=True)
    valid_to = Column(DateTime, nullable=True)
    observed_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, default=func.now(), nullable=False)
    confidence = Column(Float, default=1.0, nullable=False)
    weight = Column(Float, default=1.0, nullable=False)
    salience = Column(Float, default=0.5, nullable=False)
    lifecycle_state = Column(String(50), default="active", nullable=False)
    source_memory_id = Column(UUID(as_uuid=True), nullable=True)
    source_event_id = Column(UUID(as_uuid=True), nullable=True)
    schema_version = Column(BigInteger, default=1, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_memory_relation_source", "source_id"),
        Index("idx_memory_relation_target", "target_id"),
        Index(
            "idx_memory_relation_tenant_user_source",
            "tenant_id",
            "user_id",
            "source_id",
        ),
        Index(
            "idx_memory_relation_tenant_user_target",
            "tenant_id",
            "user_id",
            "target_id",
        ),
        Index("idx_memory_relation_tenant_type", "tenant_id", "relation_type"),
        Index("idx_memory_relation_validity", "valid_from", "valid_to"),
        Index("idx_memory_relation_source_event", "source_event_id"),
    )


class ReinforcementEvent(Base):
    """Tracks reinforcement evidence and confidence updates."""

    __tablename__ = "reinforcement_event"

    reinforcement_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_assertion_id = Column(UUID(as_uuid=True), nullable=False)
    weight = Column(Float, default=0.1)
    created_at = Column(DateTime, default=func.now(), nullable=False)


class ContradictionEvent(Base):
    """Tracks contradiction evidence and resolution state."""

    __tablename__ = "contradiction_event"

    contradiction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_assertion_id = Column(UUID(as_uuid=True), nullable=False)
    target_assertion_id = Column(UUID(as_uuid=True), nullable=False)
    resolution_status = Column(String(50), default="open")
    created_at = Column(DateTime, default=func.now(), nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class ProjectionStatus(Base):
    """Tracks projection of canonical events to derived/runtime stores."""

    __tablename__ = "projection_status"

    projection_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("memory_event.event_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_store = Column(String(50), nullable=False)
    status = Column(String(50), default="pending")
    retry_count = Column(BigInteger, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index(
            "idx_projection_status_event_store",
            "event_id",
            "target_store",
            unique=True,
        ),
        Index("idx_projection_status_status", "status"),
    )


class ConsentScope(Base):
    """Tracks consent governance scopes for memory items."""

    __tablename__ = "consent_scope"

    scope_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    scope_name = Column(String(100), nullable=False)
    is_granted = Column(Boolean, default=True)
    granted_at = Column(DateTime, default=func.now(), nullable=False)
    revoked_at = Column(DateTime, nullable=True)


class RetentionPolicy(Base):
    """Defines TTL and retention behavior for memory scopes/classes."""

    __tablename__ = "retention_policy"

    policy_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    memory_class = Column(String(50), nullable=False)
    ttl_days = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
