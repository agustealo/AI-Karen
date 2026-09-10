"""
SQLAlchemy models for the production chat system.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import (
    UUID,
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    JSON,
    ForeignKey,
    Column,
    Index,
    BigInteger,
    CheckConstraint,
    func,
    LargeBinary,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import expression

Base = declarative_base()


class BaseChatModel:
    """Base class for chat models that maps kwarg 'metadata' to 'metadata_' attribute."""
    def __init__(self, **kwargs):
        if "metadata" in kwargs and "metadata_" not in kwargs:
            kwargs["metadata_"] = kwargs.pop("metadata")
        super().__init__(**kwargs)


class ChatConversation(BaseChatModel, Base):
    """Chat conversation model for the production chat system."""
    
    __tablename__ = "chat_conversations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth_users.user_id"), nullable=False)
    title = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    provider_id = Column(String(50))
    model_used = Column(String(100))
    message_count = Column(Integer, default=0)
    metadata_ = Column("metadata", JSONB, default=dict)
    is_archived = Column(Boolean, default=False)
    
    # Security fields
    is_encrypted = Column(Boolean, default=False)
    security_level = Column(String(20), default="medium")
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime(timezone=True))
    created_by_ip = Column(String(45))
    last_modified_by = Column(String(255))
    
    # Relationships
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at"
    )
    sessions = relationship(
        "ChatSession",
        back_populates="conversation",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("idx_chat_conversations_user_id_updated_at", "user_id", text("updated_at DESC")),
        Index("idx_chat_conversations_provider_id", "provider_id"),
        Index("idx_chat_conversations_is_archived", "is_archived"),
        Index("idx_chat_conversations_security_level", "security_level"),
        Index("idx_chat_conversations_last_accessed", "last_accessed_at"),
    )
    
    def __repr__(self) -> str:
        return f"<ChatConversation(id={self.id}, user_id={self.user_id}, title='{self.title}')>"


class ChatMessage(BaseChatModel, Base):
    """Chat message model for the production chat system."""
    
    __tablename__ = "chat_messages"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    provider_id = Column(String(50))
    model_used = Column(String(100))
    token_count = Column(Integer)
    processing_time_ms = Column(Integer)
    metadata_ = Column("metadata", JSONB, default=dict)
    parent_message_id = Column(UUID(as_uuid=True), ForeignKey("chat_messages.id"))
    is_streaming = Column(Boolean, default=False)
    streaming_completed_at = Column(DateTime(timezone=True))
    
    # Security fields
    is_encrypted = Column(Boolean, default=False)
    is_sanitized = Column(Boolean, default=False)
    threat_level = Column(String(20), default="low")
    content_hash = Column(String(64))  # For content integrity verification
    moderation_status = Column(String(20), default="pending")  # pending, approved, rejected
    moderation_flags = Column(JSONB, default=dict)  # Detailed moderation results
    created_by_ip = Column(String(45))
    user_agent = Column(String(500))
    
    # Relationships
    conversation = relationship("ChatConversation", back_populates="messages")
    parent_message = relationship("ChatMessage", remote_side=[id])
    child_messages = relationship("ChatMessage", remote_side=[parent_message_id])
    attachments = relationship(
        "MessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        Index("idx_chat_messages_conversation_id_created_at", "conversation_id", text("created_at ASC")),
        Index("idx_chat_messages_role_created_at", "role", text("created_at DESC")),
        Index("idx_chat_messages_parent_message_id", "parent_message_id"),
        Index("idx_chat_messages_provider_id", "provider_id"),
        Index("idx_chat_messages_is_streaming", "is_streaming"),
        Index("idx_chat_messages_moderation_status", "moderation_status"),
        Index("idx_chat_messages_threat_level", "threat_level"),
        Index("idx_chat_messages_created_by_ip", "created_by_ip"),
    )
    
    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, conversation_id={self.conversation_id}, role='{self.role}')>"


class ChatProviderConfiguration(Base):
    """Chat provider configuration model for the production chat system."""
    
    __tablename__ = "chat_provider_configurations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth_users.user_id"), nullable=False)
    provider_id = Column(String(50), nullable=False)
    provider_name = Column(String(100), nullable=False)
    config = Column(JSONB, nullable=False)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Security fields
    is_encrypted = Column(Boolean, default=False)  # Config should be encrypted
    security_level = Column(String(20), default="medium")  # Security level for this config
    access_count = Column(Integer, default=0)  # How many times this config has been accessed
    last_accessed_at = Column(DateTime(timezone=True))
    created_by_ip = Column(String(45))
    last_modified_by = Column(String(255))
    approval_status = Column(String(20), default="pending")  # pending, approved, rejected
    approval_notes = Column(Text)
    
    # Relationships
    user = relationship("AuthUser")
    
    __table_args__ = (
        Index("idx_chat_provider_configurations_user_active", "user_id", "is_active"),
        Index("idx_chat_provider_configurations_priority", "priority"),
        Index("idx_chat_provider_configurations_provider_id", "provider_id"),
        Index("idx_chat_provider_configurations_security_level", "security_level"),
        Index("idx_chat_provider_configurations_approval_status", "approval_status"),
    )
    
    def __repr__(self) -> str:
        return f"<ChatProviderConfiguration(id={self.id}, provider_id='{self.provider_id}', user_id={self.user_id})>"


class ChatSession(BaseChatModel, Base):
    """Chat session model for tracking active chat sessions."""
    
    __tablename__ = "chat_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("auth_users.user_id"), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True))
    last_activity_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    metadata_ = Column("metadata", JSONB, default=dict)
    
    # Security fields
    is_encrypted = Column(Boolean, default=False)
    security_level = Column(String(20), default="medium")
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime(timezone=True))
    created_by_ip = Column(String(45))
    user_agent = Column(String(500))
    session_fingerprint = Column(String(64))  # Browser/device fingerprint
    is_suspicious = Column(Boolean, default=False)
    threat_score = Column(Integer, default=0)  # 0-100, higher is more suspicious
    termination_reason = Column(String(100))  # Why session was terminated
    
    # Relationships
    conversation = relationship("ChatConversation", back_populates="sessions")
    user = relationship("AuthUser")
    
    __table_args__ = (
        Index("idx_chat_sessions_token", "session_token"),
        Index("idx_chat_sessions_user_activity", "user_id", text("last_activity_at DESC")),
        Index("idx_chat_sessions_conversation_id", "conversation_id"),
        Index("idx_chat_sessions_security_level", "security_level"),
        Index("idx_chat_sessions_is_suspicious", "is_suspicious"),
        Index("idx_chat_sessions_fingerprint", "session_fingerprint"),
    )
    
    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, user_id={self.user_id}, session_token='{self.session_token}')>"


class MessageAttachment(BaseChatModel, Base):
    """Message attachment model for file attachments in chat messages."""
    
    __tablename__ = "message_attachments"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("chat_messages.id", ondelete="CASCADE"), 
        nullable=False
    )
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100))
    file_size = Column(BigInteger)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    metadata_ = Column("metadata", JSONB, default=dict)
    
    # Relationships
    message = relationship("ChatMessage", back_populates="attachments")
    
    __table_args__ = (
        Index("idx_message_attachments_message_id", "message_id"),
        Index("idx_message_attachments_created_at", "created_at"),
    )
    
    def __repr__(self) -> str:
        return f"<MessageAttachment(id={self.id}, message_id={self.message_id}, filename='{self.filename}')>"