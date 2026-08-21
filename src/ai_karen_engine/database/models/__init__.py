# mypy: ignore-errors
"""SQLAlchemy models for multi-tenant AI-Karen platform."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict

from sqlalchemy import (
    JSON,
    UUID,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import expression, func

from ai_karen_engine.automation_manager.encryption_utils import (
    decrypt_data,
    encrypt_data,
)

Base = declarative_base()


class Tenant(Base):
    """Tenant model for multi-tenant isolation."""

    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    subscription_tier = Column(String(50), nullable=False, default="basic")
    settings = Column(JSON, default={})
    is_active = Column(Boolean, default=True, server_default=expression.true())
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    users = relationship(
        "AuthUser", back_populates="tenant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_tenant_slug", "slug"),
        Index("idx_tenant_active", "is_active"),
    )

    def __repr__(self):
        return f"<Tenant(id={self.id}, name='{self.name}', slug='{self.slug}')>"


class AuthUser(Base):
    """Application user account"""

    __tablename__ = "auth_users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(255), unique=True, index=True)
    full_name = Column(String(255))
    password_hash = Column(String(255))
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    roles = Column(JSONB, nullable=False, default=list)
    preferences = Column(JSONB, default=dict)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    two_factor_secret = Column(String(32))
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login = Column(DateTime)
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime)

    tenant = relationship(
        "Tenant",
        back_populates="users",
    )
    sessions = relationship(
        "AuthSession", back_populates="user", cascade="all, delete-orphan"
    )
    chat_memories = relationship(
        "ChatMemory", back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_auth_user_email_active", "email", "is_active"),
        Index("idx_auth_user_tenant", "tenant_id"),
        Index("idx_auth_user_created", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<AuthUser(user_id={self.user_id}, email={self.email})>"


class TenantConversation(Base):
    """Base model for tenant-specific conversations."""

    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    title = Column(String(255))
    conversation_metadata = Column(JSON, default={})
    is_active = Column(Boolean, default=True, server_default=expression.true())
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Web UI integration fields
    session_id = Column(String(255), index=True)  # Session tracking for web UI
    ui_context = Column(JSON, default={})  # Web UI specific context data
    ai_insights = Column(JSON, default={})  # AI-generated insights and metadata
    user_settings = Column(
        JSON, default={}
    )  # User settings snapshot for this conversation
    summary = Column(Text)  # Conversation summary
    tags = Column(ARRAY(String), default=[])  # Conversation tags for organization
    last_ai_response_id = Column(String(255))  # Track last AI response for continuity

    __table_args__ = (
        Index("idx_conversation_user", "user_id"),
        Index("idx_conversation_created", "created_at"),
        Index("idx_conversation_active", "is_active"),
        Index("idx_conversation_session", "session_id"),
        Index("idx_conversation_tags", "tags"),
        Index("idx_conversation_user_session", "user_id", "session_id"),
    )

    def __repr__(self):
        return f"<TenantConversation(id={self.id}, user_id={self.user_id}, title='{self.title}')>"

    def add_tag(self, tag: str):
        """Add a tag to the conversation."""
        if self.tags is None:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str):
        """Remove a tag from the conversation."""
        if self.tags and tag in self.tags:
            self.tags.remove(tag)

    def update_ui_context(self, context_data: dict):
        """Update UI context with new data."""
        if self.ui_context is None:
            self.ui_context = {}
        self.ui_context.update(context_data)

    def update_ai_insights(self, insights_data: dict):
        """Update AI insights with new data."""
        if self.ai_insights is None:
            self.ai_insights = {}
        self.ai_insights.update(insights_data)


class TenantMemoryItem(Base):
    """Base model for tenant-specific memory items."""

    __tablename__ = "memory_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(255), nullable=False)
    kind = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(ARRAY(Float), nullable=True)
    item_metadata = Column("metadata", JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_memory_items_scope_kind", "scope", "kind"),)

    def __repr__(self):
        return f"<TenantMemoryItem(id={self.id}, scope='{self.scope}', kind='{self.kind}')>"


# Backwards compatibility alias
TenantMemoryEntry = TenantMemoryItem


class TenantMessage(Base):
    """Individual message within a conversation."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    message_metadata = Column(JSON, default={})
    function_call = Column(JSON)
    function_response = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_message_conversation_time", "conversation_id", "created_at"),
    )

    def __repr__(self):
        return f"<TenantMessage(id={self.id}, conversation_id={self.conversation_id}, role='{self.role}')>"


class TenantMessageTool(Base):
    """Tool execution associated with a message."""

    __tablename__ = "message_tools"

    id = Column(
        "message_tool_id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name = Column(String(255), nullable=False)
    arguments = Column(JSON, default={})
    result = Column(JSON)
    latency_ms = Column(Integer)
    status = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_message_tool_message", "message_id"),)

    def __repr__(self):
        return f"<TenantMessageTool(id={self.id}, message_id={self.message_id}, tool='{self.tool_name}')>"

    def add_tag(self, tag: str):
        """Add a tag to the memory entry."""
        if self.tags is None:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str):
        """Remove a tag from the memory entry."""
        if self.tags and tag in self.tags:
            self.tags.remove(tag)

    def increment_access_count(self):
        """Increment the access count and update last accessed time."""
        self.access_count = (self.access_count or 0) + 1
        self.last_accessed = datetime.utcnow()

    def set_importance(self, score: int):
        """Set the importance score (1-10)."""
        if 1 <= score <= 10:
            self.importance_score = score
        else:
            raise ValueError("Importance score must be between 1 and 10")

    def update_metadata(self, metadata_data: dict):
        """Update memory metadata with new data."""
        if self.memory_metadata is None:
            self.memory_metadata = {}
        self.memory_metadata.update(metadata_data)


class TenantPluginExecution(Base):
    """Base model for tenant-specific plugin executions."""

    __tablename__ = "plugin_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    plugin_name = Column(String(255), nullable=False)
    execution_data = Column(JSON, default={})
    result = Column(JSON)
    status = Column(
        String(50), default="pending"
    )  # pending, running, completed, failed
    error_message = Column(Text)
    execution_time_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_plugin_user", "user_id"),
        Index("idx_plugin_name", "plugin_name"),
        Index("idx_plugin_status", "status"),
        Index("idx_plugin_created", "created_at"),
    )

    def __repr__(self):
        return f"<TenantPluginExecution(id={self.id}, plugin_name='{self.plugin_name}', status='{self.status}')>"


class AuditLog(Base):
    """Audit logging records for tenant and user activity."""

    __tablename__ = "audit_log"

    event_id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String)
    user_id = Column(String)
    actor_type = Column(String)
    action = Column(String, nullable=False)
    resource_type = Column(String)
    resource_id = Column(String)
    ip_address = Column(String)
    user_agent = Column(Text)
    details = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_audit_tenant_time", "tenant_id", desc("created_at")),)

    def __repr__(self):
        return f"<AuditLog(event_id={self.event_id}, action='{self.action}', tenant_id={self.tenant_id})>"


class Extension(Base):
    """Registered extension metadata."""

    __tablename__ = "extensions"

    name = Column(String, primary_key=True)
    version = Column(String, nullable=False)
    category = Column(String)
    capabilities = Column(JSONB)
    directory = Column(String)
    status = Column(String, nullable=False)
    error_msg = Column(Text)
    loaded_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow)

    usage = relationship("ExtensionUsage", back_populates="extension")

    def __repr__(self):
        return f"<Extension(name={self.name}, status='{self.status}')>"


class ExtensionUsage(Base):
    """Sampled resource usage metrics for extensions."""

    __tablename__ = "extension_usage"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, ForeignKey("extensions.name", ondelete="CASCADE"))
    memory_mb = Column(Float)
    cpu_percent = Column(Float)
    disk_mb = Column(Float)
    network_sent = Column(BigInteger)
    network_recv = Column(BigInteger)
    uptime_seconds = Column(BigInteger)
    sampled_at = Column(DateTime, default=datetime.utcnow)

    extension = relationship("Extension", back_populates="usage")

    __table_args__ = (Index("idx_ext_usage_name_time", "name", desc("sampled_at")),)

    def __repr__(self):
        return f"<ExtensionUsage(name={self.name}, sampled_at={self.sampled_at})>"


class MarketplaceExtension(Base):
    """Metadata for extensions available in the marketplace."""

    __tablename__ = "marketplace_extensions"

    extension_id = Column(String, primary_key=True)
    latest_version = Column(String)
    title = Column(String)
    author = Column(String)
    summary = Column(Text)
    extension_metadata = Column("metadata", JSONB)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    installs = relationship("InstalledExtension", back_populates="extension")

    def __repr__(self):
        return f"<MarketplaceExtension(id={self.extension_id}, version={self.latest_version})>"


class InstalledExtension(Base):
    """Records of installed extensions per instance."""

    __tablename__ = "installed_extensions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    extension_id = Column(
        String, ForeignKey("marketplace_extensions.extension_id", ondelete="SET NULL")
    )
    version = Column(String)
    installed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    installed_at = Column(DateTime, default=datetime.utcnow)
    source = Column(String)
    directory = Column(String)

    extension = relationship("MarketplaceExtension", back_populates="installs")
    installer = relationship("AuthUser")

    def __repr__(self):
        return f"<InstalledExtension(extension_id={self.extension_id}, version={self.version})>"


class Hook(Base):
    """Registered hook metadata."""

    __tablename__ = "hooks"

    hook_id = Column(String, primary_key=True)
    hook_type = Column(String, nullable=False)
    source_type = Column(String, nullable=False)
    source_name = Column(String)
    priority = Column(Integer, default=50)
    enabled = Column(Boolean, default=True)
    conditions = Column(JSON, default={})
    registered_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_hooks_type", "hook_type"),
        Index("idx_hooks_enabled", "enabled"),
    )

    def __repr__(self):
        return f"<Hook(hook_id={self.hook_id}, hook_type='{self.hook_type}')>"


class HookExecutionStat(Base):
    """Aggregated hook execution metrics."""

    __tablename__ = "hook_exec_stats"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    hook_type = Column(String)
    source_name = Column(String)
    executions = Column(BigInteger, default=0)
    successes = Column(BigInteger, default=0)
    errors = Column(BigInteger, default=0)
    timeouts = Column(BigInteger, default=0)
    avg_duration_ms = Column(Integer, default=0)
    window_start = Column(DateTime)
    window_end = Column(DateTime)

    __table_args__ = (
        Index("idx_hook_exec_stats_type_window", "hook_type", "window_start"),
    )

    def __repr__(self):
        return f"<HookExecutionStat(id={self.id}, hook_type='{self.hook_type}')>"


class LLMProvider(Base):
    """Registered LLM provider with encrypted configuration."""

    __tablename__ = "llm_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    provider_type = Column(String(50), nullable=False)
    _config = Column("encrypted_config", LargeBinary, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requests = relationship("LLMRequest", back_populates="provider")

    @property
    def config(self) -> Dict[str, Any]:
        data = decrypt_data(self._config)
        return json.loads(data) if data else {}

    @config.setter
    def config(self, value: Dict[str, Any]) -> None:
        self._config = encrypt_data(json.dumps(value))

    def __repr__(self) -> str:
        return f"<LLMProvider(name={self.name}, type={self.provider_type})>"


class LLMRequest(Base):
    """LLM invocation metrics for cost tracking."""

    __tablename__ = "llm_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(UUID(as_uuid=True), ForeignKey("llm_providers.id"))
    provider_name = Column(String(100), nullable=False)
    model = Column(String(100))
    tenant_id = Column(String, index=True)
    user_id = Column(String, index=True)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)
    cost = Column(Numeric(10, 4))
    latency_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    provider = relationship("LLMProvider", back_populates="requests")

    __table_args__ = (
        Index("idx_llm_requests_provider_time", "provider_name", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LLMRequest(provider={self.provider_name}, model={self.model}, cost={self.cost})>"


class File(Base):
    """Stored file metadata and location."""

    __tablename__ = "files"

    file_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, index=True)
    owner_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    name = Column(String)
    mime_type = Column(String)
    bytes = Column(BigInteger)
    storage_uri = Column(String)
    sha256 = Column(String, nullable=False)
    file_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("AuthUser")

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<File(file_id={self.file_id}, name={self.name})>"


class Webhook(Base):
    """Registered webhook endpoints for event notifications."""

    __tablename__ = "webhooks"

    webhook_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, index=True)
    url = Column(String, nullable=False)
    _secret = Column("secret", String)
    events = Column(JSONB, nullable=False, default=list)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def secret(self) -> str | None:
        return self._secret

    @secret.setter
    def secret(self, value: str | None) -> None:
        if value is None:
            self._secret = None
        else:
            self._secret = hashlib.sha256(value.encode()).hexdigest()

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<Webhook(webhook_id={self.webhook_id}, url='{self.url}')>"


class UsageCounter(Base):
    """Rolling window usage counters for metrics."""

    __tablename__ = "usage_counters"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String)
    user_id = Column(String)
    metric = Column(String, nullable=False)
    value = Column(BigInteger, nullable=False, default=0)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_usage_counter_metric_window", "metric", "window_start"),
    )

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<UsageCounter(metric={self.metric}, value={self.value})>"


class RateLimit(Base):
    """Rate limit definitions and current usage."""

    __tablename__ = "rate_limits"

    key = Column(String, primary_key=True)
    limit_name = Column(String)
    window_sec = Column(Integer)
    max_count = Column(Integer)
    current_count = Column(Integer, default=0)
    window_reset = Column(DateTime)

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<RateLimit(key={self.key}, limit={self.limit_name})>"


class AuthSession(Base):
    """Session tokens tied to a user"""

    __tablename__ = "auth_sessions"

    session_token = Column(
        "session_id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    expires_in = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    last_accessed = Column(DateTime, default=func.now(), nullable=False)
    ip_address = Column(String)
    user_agent = Column(Text)
    device_fingerprint = Column(String)
    geolocation = Column(JSONB)
    risk_score = Column(Numeric(5, 2), default=0)
    security_flags = Column(JSONB, default=list)
    is_active = Column(Boolean, default=True, nullable=False)
    invalidated_at = Column(DateTime)
    invalidation_reason = Column(Text)

    user = relationship("AuthUser", back_populates="sessions")

    __table_args__ = (
        Index("idx_auth_sessions_user_active", "user_id", "is_active"),
        Index("idx_auth_sessions_last_accessed", "last_accessed"),
        Index("idx_auth_sessions_refresh_token", "refresh_token"),
    )

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return (
            f"<AuthSession(session_token={self.session_token}, user_id={self.user_id})>"
        )


class AuthProvider(Base):
    """Authentication provider configuration"""

    __tablename__ = "auth_providers"

    provider_id = Column(String, primary_key=True)
    tenant_id = Column(String)
    type = Column(String, nullable=False)
    config = Column(JSONB, nullable=False)
    provider_metadata = Column("metadata", JSONB, default=dict)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    identities = relationship(
        "UserIdentity", back_populates="provider", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("idx_auth_providers_tenant", "tenant_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuthProvider(provider_id={self.provider_id})>"


class UserIdentity(Base):
    """Links a user to an external auth provider identity"""

    __tablename__ = "user_identities"

    identity_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_id = Column(
        String, ForeignKey("auth_providers.provider_id"), nullable=False
    )
    provider_user = Column(String, nullable=False)
    identity_metadata = Column("metadata", JSONB)
    created_at = Column(DateTime, default=func.now())

    user = relationship("AuthUser")
    provider = relationship("AuthProvider", back_populates="identities")

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "provider_user", name="uq_user_identity_provider"
        ),
        Index("idx_user_identity_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserIdentity(identity_id={self.identity_id}, user_id={self.user_id})>"


class ChatMemory(Base):
    """Chat memory metadata for user isolation"""

    __tablename__ = "chat_memories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False
    )
    chat_id = Column(String(36), nullable=False, index=True)
    short_term_days = Column(Integer, default=1, nullable=False)
    long_term_days = Column(Integer, default=30, nullable=False)
    tail_turns = Column(Integer, default=3, nullable=False)
    summarize_threshold_tokens = Column(Integer, default=3000, nullable=False)
    total_turns = Column(Integer, default=0, nullable=False)
    last_summarized_at = Column(DateTime)
    current_token_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("AuthUser", back_populates="chat_memories")

    __table_args__ = (
        Index("idx_chat_user_chat", "user_id", "chat_id"),
        Index("idx_chat_updated", "updated_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatMemory(id={self.id}, user_id={self.user_id}, chat_id={self.chat_id})>"


class PasswordResetToken(Base):
    """Password reset tokens"""

    __tablename__ = "password_reset_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False
    )
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    used_at = Column(DateTime)

    __table_args__ = (
        Index("idx_reset_token_expires", "token", "expires_at", "is_used"),
        Index("idx_reset_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id})>"


class EmailVerificationToken(Base):
    """Email verification tokens"""

    __tablename__ = "email_verification_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String, ForeignKey("auth_users.user_id", ondelete="CASCADE"), nullable=False
    )
    token = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    used_at = Column(DateTime)

    __table_args__ = (
        Index("idx_verify_token_expires", "token", "expires_at", "is_used"),
        Index("idx_verify_user", "user_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EmailVerificationToken(id={self.id}, user_id={self.user_id})>"


class Role(Base):
    """RBAC role definition."""

    __tablename__ = "roles"

    role_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    permissions = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
    )

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<Role(role_id={self.role_id}, name={self.name}, tenant_id={self.tenant_id})>"


class RolePermission(Base):
    """Mapping of roles to permissions and scopes."""

    __tablename__ = "role_permissions"

    role_id = Column(
        String, ForeignKey("roles.role_id", ondelete="CASCADE"), primary_key=True
    )
    permission = Column(String, primary_key=True)
    scope = Column(String, primary_key=True, default="*")

    role = relationship("Role", back_populates="permissions")

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<RolePermission(role_id={self.role_id}, permission={self.permission}, scope={self.scope})>"


class ApiKey(Base):
    """API keys for programmatic access (hashed)."""

    __tablename__ = "api_keys"

    key_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    hashed_key = Column(String, nullable=False, unique=True)
    name = Column(String)
    scopes = Column(JSONB, nullable=False, default=list)
    last_used_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    expires_at = Column(DateTime)

    user = relationship("AuthUser")

    def __repr__(self) -> str:  # pragma: no cover - simple repr
        return f"<ApiKey(key_id={self.key_id}, tenant_id={self.tenant_id})>"


# Chat Runtime Control Plane Models


class SystemRuntimeState(Base):
    """Current runtime control plane state and readiness summary."""

    __tablename__ = "system_runtime_state"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    current_mode = Column(
        String(50), nullable=False, default="normal"
    )  # normal, degraded, maintenance, emergency_fallback
    normal_ready = Column(Boolean, default=False, nullable=False)
    degraded_ready = Column(Boolean, default=False, nullable=False)
    maintenance_enabled = Column(Boolean, default=False, nullable=False)
    maintenance_reason = Column(Text)
    estimated_completion_time = Column(DateTime)
    last_transition_at = Column(DateTime, default=datetime.utcnow)
    last_transition_reason = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_runtime_state_mode", "current_mode"),
        Index("idx_runtime_state_updated", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<SystemRuntimeState(mode={self.current_mode}, normal_ready={self.normal_ready})>"


class MaintenanceWindow(Base):
    """Planned maintenance entries/history."""

    __tablename__ = "maintenance_windows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enabled = Column(Boolean, default=False, nullable=False)
    message = Column(Text)
    reason = Column(Text)
    estimated_completion_time = Column(DateTime)
    notifications_supported = Column(Boolean, default=True, nullable=False)
    started_at = Column(DateTime)
    ended_at = Column(DateTime)
    auto_end_policy = Column(
        String(100), default="manual"
    )  # manual, after_healthy_check, at_time
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("auth_users.user_id", ondelete="SET NULL")
    )
    updated_by = Column(
        UUID(as_uuid=True), ForeignKey("auth_users.user_id", ondelete="SET NULL")
    )
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    creator = relationship("AuthUser", foreign_keys=[created_by])
    updater = relationship("AuthUser", foreign_keys=[updated_by])

    notification_requests = relationship(
        "MaintenanceNotificationRequest",
        back_populates="maintenance_window",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_maintenance_enabled", "enabled"),
        Index("idx_maintenance_started", "started_at"),
        Index("idx_maintenance_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<MaintenanceWindow(id={self.id}, enabled={self.enabled})>"


class MaintenanceNotificationRequest(Base):
    """User/session notification requests for maintenance completion."""

    __tablename__ = "maintenance_notification_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maintenance_window_id = Column(
        UUID(as_uuid=True),
        ForeignKey("maintenance_windows.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("auth_users.user_id", ondelete="CASCADE")
    )
    session_id = Column(String(255))  # Allow anonymous sessions
    notification_channel = Column(
        String(50), default="in_app"
    )  # in_app, websocket, email
    status = Column(
        String(50), default="active"
    )  # active, pending, completed, cancelled
    requested_at = Column(DateTime, default=datetime.utcnow)
    dispatched_at = Column(DateTime)
    cancelled_at = Column(DateTime)

    # Relationships
    maintenance_window = relationship(
        "MaintenanceWindow", back_populates="notification_requests"
    )
    user = relationship("AuthUser")

    __table_args__ = (
        Index("idx_notification_maintenance", "maintenance_window_id"),
        Index("idx_notification_user", "user_id"),
        Index("idx_notification_session", "session_id"),
        Index("idx_notification_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<MaintenanceNotificationRequest(id={self.id}, status={self.status})>"


class RuntimeDependencyHealth(Base):
    """Health snapshots for dependencies."""

    __tablename__ = "runtime_dependency_health"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dependency_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)  # healthy, unhealthy, unknown
    reason = Column(Text)
    checked_at = Column(DateTime, default=datetime.utcnow)
    consecutive_successes = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)
    last_failure_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_dependency_name", "dependency_name"),
        Index("idx_dependency_status", "status"),
        Index("idx_dependency_checked", "checked_at"),
    )

    def __repr__(self) -> str:
        return f"<RuntimeDependencyHealth(name={self.dependency_name}, status={self.status})>"


class ChatRuntimeEvent(Base):
    """Auditable runtime state transitions and maintenance responses."""

    __tablename__ = "chat_runtime_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(
        String(100), nullable=False
    )  # mode_transition, maintenance_response, etc.
    mode = Column(String(50))  # normal, degraded, maintenance, emergency_fallback
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("auth_users.user_id", ondelete="SET NULL")
    )
    session_id = Column(String(255))
    conversation_id = Column(UUID(as_uuid=True))
    details_json = Column("details", JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("AuthUser")

    __table_args__ = (
        Index("idx_runtime_event_type", "event_type"),
        Index("idx_runtime_event_user", "user_id"),
        Index("idx_runtime_event_session", "session_id"),
        Index("idx_runtime_event_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ChatRuntimeEvent(id={self.id}, type={self.event_type}, mode={self.mode})>"
from ai_karen_engine.core.memory.ledger_models import MemoryEvent, MemoryAssertion, MemoryEpisode, ProfileFact, MemoryRelation, ReinforcementEvent, ContradictionEvent, ProjectionStatus, ConsentScope, RetentionPolicy
