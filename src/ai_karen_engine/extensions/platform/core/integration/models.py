"""Extension Integration Database Models - Database models for extension tracking and management.

This module provides SQLAlchemy models for:
- Extension metadata and configuration
- Extension lifecycle state tracking
- Extension permissions and access control
- Extension metrics and performance data
- Extension dependencies and relationships
- Extension versioning and updates
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func

Base = declarative_base()


class ExtensionState(Enum):
    """Extension lifecycle states."""

    UNKNOWN = "unknown"
    REGISTERED = "registered"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    UPDATING = "updating"
    DISABLED = "disabled"


class ExtensionType(Enum):
    """Extension types."""

    CORE = "core"
    PLUGIN = "plugin"
    THEME = "theme"
    INTEGRATION = "integration"
    UTILITY = "utility"
    SECURITY = "security"
    MONITORING = "monitoring"


class ExtensionModel(Base):
    """Extension model for storing extension metadata and configuration."""

    __tablename__ = "extensions"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False, index=True)
    display_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    version = Column(String(50), nullable=False)
    author = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    homepage = Column(String(500), nullable=True)
    license = Column(String(100), nullable=True)
    extension_type = Column(String(50), nullable=False, default=ExtensionType.PLUGIN.value)
    category = Column(String(100), nullable=True)
    tags = Column(JSON, nullable=True)
    state = Column(String(50), nullable=False, default=ExtensionState.UNKNOWN.value)
    enabled = Column(Boolean, nullable=False, default=True)
    auto_start = Column(Boolean, nullable=False, default=True)
    priority = Column(Integer, nullable=False, default=50)
    path = Column(String(500), nullable=False, unique=True)
    entry_point = Column(String(500), nullable=True)
    manifest_path = Column(String(500), nullable=True)
    dependencies = Column(JSON, nullable=True)
    python_dependencies = Column(JSON, nullable=True)
    system_dependencies = Column(JSON, nullable=True)
    configuration = Column(JSON, nullable=True)
    default_configuration = Column(JSON, nullable=True)
    configuration_schema = Column(JSON, nullable=True)
    permissions = Column(JSON, nullable=True)
    security_level = Column(String(50), nullable=True)
    sandbox_enabled = Column(Boolean, nullable=False, default=True)
    memory_limit = Column(Integer, nullable=True)
    cpu_limit = Column(Float, nullable=True)
    disk_limit = Column(Integer, nullable=True)
    network_limit = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    installed_at = Column(DateTime(timezone=True), nullable=True)
    last_started = Column(DateTime(timezone=True), nullable=True)
    last_stopped = Column(DateTime(timezone=True), nullable=True)

    versions = relationship("ExtensionVersionModel", back_populates="extension", cascade="all, delete-orphan")
    metrics = relationship("ExtensionMetricModel", back_populates="extension", cascade="all, delete-orphan")
    dependencies_rel = relationship("ExtensionDependencyModel", back_populates="extension", cascade="all, delete-orphan")
    permissions_rel = relationship("ExtensionPermissionModel", back_populates="extension", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_extension_name', 'name'),
        Index('idx_extension_type', 'extension_type'),
        Index('idx_extension_state', 'state'),
        Index('idx_extension_enabled', 'enabled'),
        UniqueConstraint('name', 'version', name='uq_extension_name_version'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "email": self.email,
            "homepage": self.homepage,
            "license": self.license,
            "extension_type": self.extension_type,
            "category": self.category,
            "tags": self.tags,
            "state": self.state,
            "enabled": self.enabled,
            "auto_start": self.auto_start,
            "priority": self.priority,
            "path": self.path,
            "entry_point": self.entry_point,
            "manifest_path": self.manifest_path,
            "dependencies": self.dependencies,
            "python_dependencies": self.python_dependencies,
            "system_dependencies": self.system_dependencies,
            "configuration": self.configuration,
            "default_configuration": self.default_configuration,
            "configuration_schema": self.configuration_schema,
            "permissions": self.permissions,
            "security_level": self.security_level,
            "sandbox_enabled": self.sandbox_enabled,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "disk_limit": self.disk_limit,
            "network_limit": self.network_limit,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
            "last_started": self.last_started.isoformat() if self.last_started else None,
            "last_stopped": self.last_stopped.isoformat() if self.last_stopped else None,
        }


class ExtensionVersionModel(Base):
    """Extension version model for tracking extension versions and updates."""

    __tablename__ = "extension_versions"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    version = Column(String(50), nullable=False)
    version_code = Column(Integer, nullable=False)
    release_notes = Column(Text, nullable=True)
    changelog = Column(Text, nullable=True)
    update_channel = Column(String(50), nullable=False, default="stable")
    is_prerelease = Column(Boolean, nullable=False, default=False)
    is_latest = Column(Boolean, nullable=False, default=False)
    download_url = Column(String(500), nullable=True)
    download_size = Column(Integer, nullable=True)
    checksum = Column(String(255), nullable=True)
    signature = Column(Text, nullable=True)
    min_core_version = Column(String(50), nullable=True)
    max_core_version = Column(String(50), nullable=True)
    compatible_extensions = Column(JSON, nullable=True)
    security_scan_result = Column(JSON, nullable=True)
    vulnerability_score = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    installed_at = Column(DateTime(timezone=True), nullable=True)

    extension = relationship("ExtensionModel", back_populates="versions")

    __table_args__ = (
        Index('idx_extension_version_extension', 'extension_id'),
        Index('idx_extension_version_version', 'version'),
        Index('idx_extension_version_channel', 'update_channel'),
        Index('idx_extension_version_latest', 'is_latest'),
        UniqueConstraint('extension_id', 'version', name='uq_extension_version'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "version": self.version,
            "version_code": self.version_code,
            "release_notes": self.release_notes,
            "changelog": self.changelog,
            "update_channel": self.update_channel,
            "is_prerelease": self.is_prerelease,
            "is_latest": self.is_latest,
            "download_url": self.download_url,
            "download_size": self.download_size,
            "checksum": self.checksum,
            "signature": self.signature,
            "min_core_version": self.min_core_version,
            "max_core_version": self.max_core_version,
            "compatible_extensions": self.compatible_extensions,
            "security_scan_result": self.security_scan_result,
            "vulnerability_score": self.vulnerability_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
        }


class ExtensionMetricModel(Base):
    """Extension metrics model for storing performance and usage metrics."""

    __tablename__ = "extension_metrics"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    metric_name = Column(String(255), nullable=False)
    metric_type = Column(String(50), nullable=False)
    metric_unit = Column(String(50), nullable=True)
    value = Column(Float, nullable=False)
    tags = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    extension = relationship("ExtensionModel", back_populates="metrics")

    __table_args__ = (
        Index('idx_extension_metric_extension', 'extension_id'),
        Index('idx_extension_metric_name', 'metric_name'),
        Index('idx_extension_metric_timestamp', 'timestamp'),
        Index('idx_extension_metric_type', 'metric_type'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "metric_name": self.metric_name,
            "metric_type": self.metric_type,
            "metric_unit": self.metric_unit,
            "value": self.value,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class ExtensionDependencyModel(Base):
    """Extension dependency model for tracking extension dependencies."""

    __tablename__ = "extension_dependencies"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    dependency_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    dependency_type = Column(String(50), nullable=False)
    version_constraint = Column(String(100), nullable=True)
    auto_install = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    extension = relationship("ExtensionModel", foreign_keys=[extension_id], back_populates="dependencies_rel")
    dependency = relationship("ExtensionModel", foreign_keys=[dependency_id])

    __table_args__ = (
        Index('idx_extension_dependency_extension', 'extension_id'),
        Index('idx_extension_dependency_dependency', 'dependency_id'),
        Index('idx_extension_dependency_type', 'dependency_type'),
        UniqueConstraint('extension_id', 'dependency_id', name='uq_extension_dependency'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "dependency_id": self.dependency_id,
            "dependency_type": self.dependency_type,
            "version_constraint": self.version_constraint,
            "auto_install": self.auto_install,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExtensionPermissionModel(Base):
    """Extension permission model for tracking extension permissions and access control."""

    __tablename__ = "extension_permissions"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    permission_name = Column(String(255), nullable=False)
    permission_type = Column(String(50), nullable=False)
    permission_scope = Column(String(50), nullable=False)
    access_level = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    resource_limits = Column(JSON, nullable=True)
    granted_to = Column(JSON, nullable=True)
    denied_to = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    extension = relationship("ExtensionModel", back_populates="permissions_rel")

    __table_args__ = (
        Index('idx_extension_permission_extension', 'extension_id'),
        Index('idx_extension_permission_name', 'permission_name'),
        Index('idx_extension_permission_type', 'permission_type'),
        Index('idx_extension_permission_scope', 'permission_scope'),
        Index('idx_extension_permission_level', 'access_level'),
        Index('idx_extension_permission_active', 'is_active'),
        UniqueConstraint('extension_id', 'permission_name', name='uq_extension_permission'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "permission_name": self.permission_name,
            "permission_type": self.permission_type,
            "permission_scope": self.permission_scope,
            "access_level": self.access_level,
            "description": self.description,
            "resource_limits": self.resource_limits,
            "granted_to": self.granted_to,
            "denied_to": self.denied_to,
            "is_active": self.is_active,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ExtensionEventModel(Base):
    """Extension event model for tracking extension lifecycle events."""

    __tablename__ = "extension_events"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    event_level = Column(String(20), nullable=False)
    message = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    user_id = Column(String(255), nullable=True)
    session_id = Column(String(255), nullable=True)
    request_id = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    extension = relationship("ExtensionModel")

    __table_args__ = (
        Index('idx_extension_event_extension', 'extension_id'),
        Index('idx_extension_event_type', 'event_type'),
        Index('idx_extension_event_level', 'event_level'),
        Index('idx_extension_event_timestamp', 'timestamp'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "event_type": self.event_type,
            "event_level": self.event_level,
            "message": self.message,
            "details": self.details,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class ExtensionConfigModel(Base):
    """Extension configuration model for storing extension configuration."""

    __tablename__ = "extension_configs"

    id = Column(String(255), primary_key=True)
    extension_id = Column(String(255), ForeignKey("extensions.id"), nullable=False)
    config_key = Column(String(255), nullable=False)
    config_value = Column(JSON, nullable=False)
    config_type = Column(String(50), nullable=False)
    is_sensitive = Column(Boolean, nullable=False, default=False)
    is_valid = Column(Boolean, nullable=True)
    validation_error = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    default_value = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    extension = relationship("ExtensionModel")

    __table_args__ = (
        Index('idx_extension_config_extension', 'extension_id'),
        Index('idx_extension_config_key', 'config_key'),
        Index('idx_extension_config_type', 'config_type'),
        Index('idx_extension_config_sensitive', 'is_sensitive'),
        UniqueConstraint('extension_id', 'config_key', name='uq_extension_config'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "extension_id": self.extension_id,
            "config_key": self.config_key,
            "config_value": self.config_value,
            "config_type": self.config_type,
            "is_sensitive": self.is_sensitive,
            "is_valid": self.is_valid,
            "validation_error": self.validation_error,
            "description": self.description,
            "default_value": self.default_value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Query utility functions
def get_extension_by_id(session: Session, extension_id: str) -> Optional[ExtensionModel]:
    """Get extension by ID."""
    return session.query(ExtensionModel).filter(ExtensionModel.id == extension_id).first()


def get_extension_by_name(session: Session, name: str) -> Optional[ExtensionModel]:
    """Get extension by name."""
    return session.query(ExtensionModel).filter(ExtensionModel.name == extension_id).first()


def get_extensions_by_state(session: Session, state: ExtensionState) -> List[ExtensionModel]:
    """Get extensions by state."""
    return session.query(ExtensionModel).filter(ExtensionModel.state == state.value).all()


def get_extensions_by_type(session: Session, extension_type: ExtensionType) -> List[ExtensionModel]:
    """Get extensions by type."""
    return session.query(ExtensionModel).filter(ExtensionModel.extension_type == extension_type.value).all()


def get_enabled_extensions(session: Session) -> List[ExtensionModel]:
    """Get all enabled extensions."""
    return session.query(ExtensionModel).filter(ExtensionModel.enabled == True).all()


def get_extension_metrics(
    session: Session,
    extension_id: str,
    metric_name: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> List[ExtensionMetricModel]:
    """Get extension metrics with optional filtering."""
    query = session.query(ExtensionMetricModel).filter(ExtensionMetricModel.extension_id == extension_id)

    if metric_name:
        query = query.filter(ExtensionMetricModel.metric_name == metric_name)

    if start_time:
        query = query.filter(ExtensionMetricModel.timestamp >= start_time)

    if end_time:
        query = query.filter(ExtensionMetricModel.timestamp <= end_time)

    return query.order_by(ExtensionMetricModel.timestamp.desc()).all()


def get_extension_events(
    session: Session,
    extension_id: str,
    event_type: Optional[str] = None,
    event_level: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> List[ExtensionEventModel]:
    """Get extension events with optional filtering."""
    query = session.query(ExtensionEventModel).filter(ExtensionEventModel.extension_id == extension_id)

    if event_type:
        query = query.filter(ExtensionEventModel.event_type == event_type)

    if event_level:
        query = query.filter(ExtensionEventModel.event_level == event_level)

    if start_time:
        query = query.filter(ExtensionEventModel.timestamp >= start_time)

    if end_time:
        query = query.filter(ExtensionEventModel.timestamp <= end_time)

    return query.order_by(ExtensionEventModel.timestamp.desc()).all()


__all__ = [
    "Base",
    "ExtensionModel",
    "ExtensionVersionModel",
    "ExtensionMetricModel",
    "ExtensionDependencyModel",
    "ExtensionPermissionModel",
    "ExtensionEventModel",
    "ExtensionConfigModel",
    "ExtensionState",
    "ExtensionType",
    "get_extension_by_id",
    "get_extension_by_name",
    "get_extensions_by_state",
    "get_extensions_by_type",
    "get_enabled_extensions",
    "get_extension_metrics",
    "get_extension_events",
]
