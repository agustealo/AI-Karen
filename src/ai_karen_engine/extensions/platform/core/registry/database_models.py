"""
SQLAlchemy database models for the extension registry system.
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
    Enum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import expression

from .manifest import ExtensionStatus

Base = declarative_base()


class ExtensionDBModel(Base):
    """
    Database model for storing extension manifests and metadata.
    This replaces the in-memory storage in PluginRegistry.
    """

    __tablename__ = "extension_registry"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic metadata (indexed for fast lookups)
    name = Column(String(100), nullable=False, unique=True, index=True)
    version = Column(String(50), nullable=False, index=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text)
    author = Column(String(100))
    license = Column(String(50))
    category = Column(String(50), index=True)
    tags = Column(ARRAY(String))

    # API compatibility
    api_version = Column(String(20), default="1.0")
    kari_min_version = Column(String(20), default="0.4.0")

    # Capabilities as JSONB for flexible storage
    capabilities = Column(JSONB, default=dict)
    dependencies = Column(JSONB, default=dict)
    permissions = Column(JSONB, default=dict)
    resources = Column(JSONB, default=dict)

    # UI and API configuration
    ui_config = Column(JSONB, default=dict)
    api_config = Column(JSONB, default=dict)
    background_tasks = Column(JSONB, default=list)

    # Marketplace metadata
    marketplace_info = Column(JSONB, default=dict)

    # Runtime state
    status = Column(String(50), default="inactive", index=True)
    lifecycle_state = Column(String(32), default="available", nullable=False, index=True)
    enabled = Column(Boolean, default=False, nullable=False, index=True)
    installed_at = Column(DateTime(timezone=True))
    install_path = Column(String(500))
    directory_path = Column(String(500))
    is_validated = Column(Boolean, default=False)
    validation_errors = Column(JSON, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    loaded_at = Column(DateTime(timezone=True))
    last_error_at = Column(DateTime(timezone=True))

    # Error tracking
    error_message = Column(Text)
    error_stack_trace = Column(Text)
    error_count = Column(Integer, default=0)

    # Performance metrics
    load_time_ms = Column(Integer)
    memory_usage_mb = Column(Integer)
    cpu_usage_percent = Column(Integer)

    # Relationships
    installation_history = relationship(
        "ExtensionInstallationHistory",
        back_populates="extension",
        cascade="all, delete-orphan",
    )
    hook_assignments = relationship(
        "ExtensionHookAssignment",
        back_populates="extension",
        cascade="all, delete-orphan",
    )

    # Indexes for common query patterns
    __table_args__ = (
        Index("idx_extension_name_version", "name", "version"),
        Index("idx_extension_category_status", "category", "status"),
        Index("idx_extension_status_created", "status", "created_at"),
        Index("idx_extension_lifecycle_enabled", "lifecycle_state", "enabled"),
        Index("idx_extension_author", "author"),
    )

    def to_manifest(self) -> Dict[str, Any]:
        """Convert database record to ExtensionManifest format."""
        return {
            "name": self.name,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "category": self.category,
            "tags": self.tags or [],
            "api_version": self.api_version,
            "kari_min_version": self.kari_min_version,
            "capabilities": self.capabilities or {},
            "dependencies": self.dependencies or {},
            "permissions": self.permissions or {},
            "resources": self.resources or {},
            "ui": self.ui_config or {},
            "api": self.api_config or {},
            "background_tasks": self.background_tasks or [],
            "marketplace": self.marketplace_info or {},
        }

    def to_record_dict(self) -> Dict[str, Any]:
        """Convert database record to ExtensionRecord format."""
        return {
            "id": str(self.id),
            "name": self.name,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "status": getattr(self.status, "value", self.status),
            "lifecycle_state": self.lifecycle_state,
            "enabled": self.enabled,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
            "install_path": self.install_path,
            "is_validated": self.is_validated,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "loaded_at": self.loaded_at.isoformat() if self.loaded_at else None,
            "last_error_at": self.last_error_at.isoformat()
            if self.last_error_at
            else None,
            "error_message": self.error_message,
            "error_count": self.error_count,
            "directory_path": self.directory_path,
            "capabilities": self.capabilities,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "resources": self.resources,
            "performance": {
                "load_time_ms": self.load_time_ms,
                "memory_usage_mb": self.memory_usage_mb,
                "cpu_usage_percent": self.cpu_usage_percent,
            },
        }


class ExtensionInstallationHistory(Base):
    """
    Track installation, updates, and uninstallation history for extensions.
    """

    __tablename__ = "extension_installation_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extension_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )

    # Action types
    ACTION_INSTALL = "install"
    ACTION_UPDATE = "update"
    ACTION_UNINSTALL = "uninstall"
    ACTION_ROLLBACK = "rollback"
    ACTION_ENABLE = "enable"
    ACTION_DISABLE = "disable"

    action = Column(String(20), nullable=False)
    version_from = Column(String(50))
    version_to = Column(String(50), nullable=False)

    # Metadata
    performed_by = Column(String(100))  # Could be user ID or system
    reason = Column(Text)  # Reason for the action
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    # Timestamps
    performed_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    # Relationships
    extension = relationship("ExtensionDBModel", back_populates="installation_history")

    __table_args__ = (
        Index("idx_history_extension_action", "extension_id", "action"),
        Index("idx_history_performed_at", "performed_at"),
    )


class ExtensionHookAssignment(Base):
    """
    Track which extensions are assigned to which hook points.
    """

    __tablename__ = "extension_hook_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extension_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )

    # Hook point information
    hook_point = Column(String(100), nullable=False, index=True)
    hook_priority = Column(Integer, default=0)  # Higher numbers = higher priority
    is_active = Column(Boolean, default=True, index=True)

    # Assignment metadata
    assigned_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    assigned_by = Column(String(100))  # Could be user ID or system

    # Performance tracking
    execution_count = Column(Integer, default=0)
    average_execution_time_ms = Column(Integer)
    last_execution_at = Column(DateTime(timezone=True))

    # Relationships
    extension = relationship("ExtensionDBModel", back_populates="hook_assignments")

    __table_args__ = (
        Index("idx_assignment_extension_hook", "extension_id", "hook_point"),
        Index("idx_assignment_hook_priority", "hook_point", "hook_priority"),
        Index("idx_assignment_active_hook", "is_active", "hook_point"),
    )


class ExtensionDependencyGraph(Base):
    """
    Track dependency relationships between extensions for topological sorting.
    """

    __tablename__ = "extension_dependency_graph"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Extension and its dependency
    extension_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )
    dependency_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )

    # Dependency type
    DEPENDENCY_TYPE_PLUGIN = "plugin"
    DEPENDENCY_TYPE_EXTENSION = "extension"
    DEPENDENCY_TYPE_SERVICE = "service"

    dependency_type = Column(String(20), nullable=False)
    is_optional = Column(Boolean, default=False)

    # Metadata
    declared_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    # Relationships
    extension = relationship("ExtensionDBModel", foreign_keys=[extension_id])
    dependency = relationship("ExtensionDBModel", foreign_keys=[dependency_id])

    __table_args__ = (
        Index("idx_dependency_extension", "extension_id"),
        Index("idx_dependency_target", "dependency_id"),
        Index("idx_dependency_type", "dependency_type"),
        Index(
            "idx_dependency_extension_target",
            "extension_id",
            "dependency_id",
            unique=True,
        ),
    )


class ExtensionValidationLog(Base):
    """
    Track validation results and history for extensions.
    """

    __tablename__ = "extension_validation_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extension_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )

    # Validation types
    VALIDATION_TYPE_SYNTAX = "syntax"
    VALIDATION_TYPE_VARIABLES = "variables"
    VALIDATION_TYPE_SECURITY = "security"
    VALIDATION_TYPE_BEST_PRACTICES = "best_practices"
    VALIDATION_TYPE_COMPLEXITY = "complexity"

    validation_type = Column(String(50), nullable=False)
    validation_result = Column(Boolean, nullable=False)

    # Validation details
    validator_name = Column(String(100), nullable=False)
    validation_message = Column(Text)
    validation_details = Column(JSON)
    severity = Column(String(20), default="info")  # info, warning, error, critical

    # Timestamps
    validated_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    # Relationships
    extension = relationship("ExtensionDBModel")

    __table_args__ = (
        Index("idx_validation_extension_type", "extension_id", "validation_type"),
        Index("idx_validation_result", "validation_result"),
        Index("idx_validation_severity", "severity"),
    )


class ExtensionUsageMetrics(Base):
    """
    Track usage metrics for extensions.
    """

    __tablename__ = "extension_usage_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    extension_id = Column(
        UUID(as_uuid=True), ForeignKey("extension_registry.id"), nullable=False
    )

    # Usage metrics
    usage_count = Column(Integer, default=0)
    unique_users = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    # Performance metrics
    total_execution_time_ms = Column(Integer, default=0)
    average_execution_time_ms = Column(Integer)

    # Time period (could be daily, weekly, monthly)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)

    # Relationships
    extension = relationship("ExtensionDBModel")

    __table_args__ = (
        Index(
            "idx_usage_extension_period", "extension_id", "period_start", "period_end"
        ),
        Index("idx_usage_period", "period_start", "period_end"),
    )
