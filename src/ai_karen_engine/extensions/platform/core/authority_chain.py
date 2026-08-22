"""
Authority Chain Service - Descriptive metadata and provenance registry.

This service no longer performs runtime authorization or owns lifecycle transitions.
It retains useful descriptive functionality:

- canonical source checksum verification
- source provenance tracking
- category validation
- plugin metadata registration

Authorization is owned by RuntimePolicy.
Lifecycle transitions are owned by PluginLifecycleManager.
"""

from __future__ import annotations

import logging
import hashlib
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import PluginLifecycleState

logger = logging.getLogger("kari.authority_chain")


class AuthorityLevel(str, Enum):
    """Authority levels for descriptive metadata and UI labels only.

    This enum is retained for persisted metadata and UI display.
    It is NOT used for runtime authorization decisions.
    RuntimePolicy is the sole authorization authority.
    """

    SYSTEM = "system"
    ADMIN = "admin"
    PLUGIN = "plugin"
    FRONTEND = "frontend"
    USER = "user"
    GUEST = "guest"


LIFECYCLE_STAGE_TO_PLUGIN_LIFECYCLE_STATE = {
    "discovered": PluginLifecycleState.AVAILABLE,
    "downloaded": PluginLifecycleState.INSTALLING,
    "validated": PluginLifecycleState.INSTALLING,
    "installed": PluginLifecycleState.INSTALLED,
    "registered": PluginLifecycleState.INSTALLED,
    "mounted": PluginLifecycleState.ENABLED,
    "enabled": PluginLifecycleState.ENABLED,
    "disabled": PluginLifecycleState.DISABLED,
    "uninstalled": PluginLifecycleState.UNINSTALLED,
}


@dataclass
class CanonicalSource:
    """Represents the canonical source of a plugin/extension."""

    source_type: str
    source_path: str
    checksum: str
    verified: bool = False
    verified_at: Optional[datetime] = None
    authority_level: AuthorityLevel = AuthorityLevel.USER

    def verify_checksum(self, content: bytes) -> bool:
        """Verify the content matches the expected checksum."""
        content_hash = hashlib.sha256(content).hexdigest()
        if content_hash == self.checksum:
            self.verified = True
            self.verified_at = datetime.utcnow()
            return True
        return False


@dataclass
class AuthorityRecord:
    """Descriptive metadata record for a plugin.

    This is observational metadata only. It does not authorize or block execution.
    """

    plugin_name: str
    authority_level: AuthorityLevel = AuthorityLevel.USER
    lifecycle_stage: str = "available"
    canonical_source: Optional[CanonicalSource] = None
    category: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class AuthorityChainService:
    """
    Descriptive metadata service for plugin provenance and category validation.

    This service no longer performs runtime authorization or owns lifecycle transitions.
    Authorization is owned by RuntimePolicy.
    Lifecycle transitions are owned by PluginLifecycleManager.
    """

    VALID_CATEGORIES = {"plugins", "sys_extensions", "channels"}

    def __init__(self, database_service=None):
        """Initialize the authority chain service."""
        self.authority_records: Dict[str, AuthorityRecord] = {}
        self.canonical_sources: Dict[str, CanonicalSource] = {}
        self.database_service = database_service

        logger.info("AuthorityChainService initialized")

    def validate_category(self, category: str) -> bool:
        """Validate that a category is allowed."""
        return category in self.VALID_CATEGORIES

    def create_canonical_source(
        self,
        source_type: str,
        source_path: str,
        content: bytes,
        authority_level: AuthorityLevel = AuthorityLevel.USER,
    ) -> CanonicalSource:
        """Create and verify a canonical source."""
        checksum = hashlib.sha256(content).hexdigest()

        canonical_source = CanonicalSource(
            source_type=source_type,
            source_path=source_path,
            checksum=checksum,
            authority_level=authority_level,
        )

        if canonical_source.verify_checksum(content):
            logger.info(f"Canonical source verified: {source_path}")
        else:
            logger.warning(f"Canonical source verification failed: {source_path}")

        return canonical_source

    def register_plugin(
        self,
        plugin_name: str,
        category: str,
        authority_level: AuthorityLevel = AuthorityLevel.USER,
        canonical_source: Optional[CanonicalSource] = None,
    ) -> AuthorityRecord:
        """Register descriptive metadata for a plugin."""

        if not self.validate_category(category):
            raise ValueError(
                f"Invalid category: {category}. Valid categories: {self.VALID_CATEGORIES}"
            )

        authority_record = AuthorityRecord(
            plugin_name=plugin_name,
            authority_level=authority_level,
            category=category,
            canonical_source=canonical_source,
        )

        self.authority_records[plugin_name] = authority_record

        if canonical_source:
            self.canonical_sources[plugin_name] = canonical_source

        logger.info(
            f"Plugin registered: {plugin_name} with authority metadata {authority_level.value}"
        )
        return authority_record

    def get_plugin_authority(self, plugin_name: str) -> Optional[AuthorityRecord]:
        """Get descriptive authority record for a plugin."""
        return self.authority_records.get(plugin_name)

    def get_plugins_by_authority_level(
        self, authority_level: AuthorityLevel
    ) -> List[str]:
        """Get all plugins with a specific authority level metadata."""
        return [
            name
            for name, record in self.authority_records.items()
            if record.authority_level == authority_level
        ]

    def get_plugins_by_category(self, category: str) -> List[str]:
        """Get all plugins in a specific category."""
        return [
            name
            for name, record in self.authority_records.items()
            if record.category == category
        ]

    def get_authority_chain_report(self) -> Dict[str, Any]:
        """Generate descriptive authority chain report."""

        total_plugins = len(self.authority_records)
        authority_distribution = {}
        category_distribution = {}

        for record in self.authority_records.values():
            auth_level = record.authority_level.value
            authority_distribution[auth_level] = (
                authority_distribution.get(auth_level, 0) + 1
            )

            if record.category:
                category_distribution[record.category] = (
                    category_distribution.get(record.category, 0) + 1
                )

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_plugins": total_plugins,
            "authority_distribution": authority_distribution,
            "category_distribution": category_distribution,
            "valid_categories": list(self.VALID_CATEGORIES),
            "health_status": "healthy",
        }


# Global singleton instance
_authority_chain_service: Optional[AuthorityChainService] = None


def get_authority_chain_service(database_service=None) -> AuthorityChainService:
    """Get the global authority chain service instance."""
    global _authority_chain_service
    if _authority_chain_service is None:
        _authority_chain_service = AuthorityChainService(
            database_service=database_service
        )
    return _authority_chain_service


class AuthorityViolation(Exception):
    """Raised when authority boundaries are violated."""

    pass


class LifecycleViolation(Exception):
    """Raised when lifecycle rules are violated."""

    pass


__all__ = [
    "AuthorityChainService",
    "AuthorityLevel",
    "AuthorityViolation",
    "LifecycleViolation",
    "CanonicalSource",
    "AuthorityRecord",
    "LIFECYCLE_STAGE_TO_PLUGIN_LIFECYCLE_STATE",
    "get_authority_chain_service",
]
