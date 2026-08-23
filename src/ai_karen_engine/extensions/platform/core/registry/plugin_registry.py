import logging
import asyncio
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..manifest import (
    ExtensionManifest,
    ExtensionRecord,
    ExtensionStatus,
    HookPoint,
)
from .discovery import ExtensionDiscoveryService, ExtensionMetadata
from .validator import ExtensionValidator
from .database_models import (
    ExtensionDBModel,
    ExtensionHookAssignment,
    ExtensionInstallationHistory,
    Base,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_

logger = logging.getLogger("kari.plugin_registry")


class PluginRegistry:
    """
    Unified registry for all Extensions/Plugins in Karen AI.
    Uses database persistence instead of in-memory storage.
    Delegates to DiscoveryService for scanning and Validator for governance.
    """

    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
        db_session: Optional[AsyncSession] = None,
    ):
        self.validator = ExtensionValidator()
        self.discovery = ExtensionDiscoveryService(
            extensions_dir, validator=self.validator
        )
        self.db_session = db_session
        self._discovery_metadata: Dict[str, ExtensionMetadata] = {}
        self._loaded_extensions: Dict[str, ExtensionRecord] = {}

    async def initialize(self):
        """Initialize registry and perform initial discovery scan."""
        try:
            # Table creation is owned by migrations; skip runtime DDL in production.
            if False and self.db_session:
                await self._create_tables()
            else:
                logger.info("Skipping runtime table creation; using migrations")

            # Perform initial discovery and sync with database
            await self.refresh()
        except Exception as e:
            logger.error(f"Failed to initialize registry: {e}")
            # Continue without database functionality

    async def _create_tables(self):
        """Create database tables if they don't exist."""
        if not self.db_session:
            return

        try:
            from sqlalchemy import text

            # Create tables and indexes one by one to avoid prepared statement limitations
            statements = [
                """
                CREATE TABLE IF NOT EXISTS extension_registry (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(100) NOT NULL UNIQUE,
                    version VARCHAR(50) NOT NULL,
                    display_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    author VARCHAR(100),
                    license VARCHAR(50),
                    category VARCHAR(50),
                    tags TEXT[],
                    api_version VARCHAR(20) DEFAULT '1.0',
                    kari_min_version VARCHAR(20) DEFAULT '0.4.0',
                    capabilities JSONB DEFAULT '{}',
                    dependencies JSONB DEFAULT '{}',
                    permissions JSONB DEFAULT '{}',
                    resources JSONB DEFAULT '{}',
                    ui_config JSONB DEFAULT '{}',
                    api_config JSONB DEFAULT '{}',
                    background_tasks JSONB DEFAULT '[]',
                    marketplace_info JSONB DEFAULT '{}',
                    status VARCHAR(50) DEFAULT 'inactive',
                    directory_path VARCHAR(500),
                    is_validated BOOLEAN DEFAULT FALSE,
                    validation_errors JSONB DEFAULT '[]',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    loaded_at TIMESTAMPTZ,
                    last_error_at TIMESTAMPTZ,
                    error_message TEXT,
                    error_stack_trace TEXT,
                    error_count INTEGER DEFAULT 0,
                    load_time_ms INTEGER,
                    memory_usage_mb INTEGER,
                    cpu_usage_percent INTEGER
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_extension_name ON extension_registry(name)",
                "CREATE INDEX IF NOT EXISTS idx_extension_version ON extension_registry(version)",
                "CREATE INDEX IF NOT EXISTS idx_extension_category ON extension_registry(category)",
                "CREATE INDEX IF NOT EXISTS idx_extension_status ON extension_registry(status)",
                "CREATE INDEX IF NOT EXISTS idx_extension_created_at ON extension_registry(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_extension_name_version ON extension_registry(name, version)",
            ]

            async with self.db_session.begin():
                for stmt in statements:
                    await self.db_session.execute(text(stmt))

            logger.info("Database tables created/verified for extension registry")

        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise

    async def refresh(self):
        """Re-scan the extensions directory and sync with database."""
        # Discover extensions on disk
        self._discovery_metadata = await self.discovery.discover_extensions(
            force_refresh=True
        )

        # Drop any loaded extensions that no longer exist on disk.
        # This keeps the catalog from surfacing dead plugins after uninstall.
        stale_loaded = [
            name
            for name in list(self._loaded_extensions.keys())
            if name not in self._discovery_metadata
        ]
        for name in stale_loaded:
            logger.info("Pruning stale loaded extension from registry: %s", name)
            self._loaded_extensions.pop(name, None)

        # Sync discovered extensions with database
        await self._sync_with_database()

        logger.info(
            f"Registry refreshed. Discovered {len(self._discovery_metadata)} potential extensions."
        )

    async def _sync_with_database(self):
        """Sync discovered extensions with database records."""
        if not self.db_session:
            logger.info("No database session available, skipping database sync")
            return

        try:
            for name, metadata in self._discovery_metadata.items():
                try:
                    # Check if extension already exists in database
                    result = await self.db_session.execute(
                        select(ExtensionDBModel).where(
                            and_(
                                ExtensionDBModel.name == name,
                                ExtensionDBModel.version == metadata.version,
                            )
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if not existing:
                        # Create new database record
                        db_record = ExtensionDBModel(
                            name=name,
                            version=metadata.version,
                            display_name=metadata.display_name,
                            description=metadata.description,
                            author=metadata.author,
                            category=metadata.category,
                            tags=metadata.tags,
                            directory_path=str(metadata.directory),
                            is_validated=metadata.is_valid,
                        )
                        self.db_session.add(db_record)
                        await self.db_session.flush()
                        logger.debug(
                            f"Added new extension to database: {name} v{metadata.version}"
                        )

                except Exception as e:
                    logger.error(f"Failed to sync extension {name} with database: {e}")
        except Exception as e:
            logger.error(f"Failed to sync with database: {e}")

    def get_extension(self, extension_id: str) -> Optional[ExtensionRecord]:
        """Get extension by name (for backward compatibility)."""
        return self._loaded_extensions.get(extension_id)

    def get_all_extensions(self) -> Dict[str, ExtensionRecord]:
        """Get all loaded extensions as a dictionary."""
        return self._loaded_extensions.copy()

    def list_extensions(self) -> List[ExtensionRecord]:
        """List all loaded extensions."""
        return list(self._loaded_extensions.values())

    def get_metadata(self, extension_id: str) -> Optional[ExtensionMetadata]:
        """Get discovery metadata for an extension."""
        return self._discovery_metadata.get(extension_id)

    def list_discovered(self) -> List[str]:
        """List all discovered extension names."""
        return list(self._discovery_metadata.keys())

    async def get_extension_by_name(self, name: str) -> Optional[ExtensionDBModel]:
        """Get extension database record by name."""
        if not self.db_session:
            return None

        result = await self.db_session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.name == name)
        )
        return result.scalar_one_or_none()

    async def get_extension_by_id(
        self, extension_id: uuid.UUID
    ) -> Optional[ExtensionDBModel]:
        """Get extension database record by UUID."""
        if not self.db_session:
            return None

        result = await self.db_session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.id == str(extension_id))
        )
        return result.scalar_one_or_none()

    async def list_all_extensions(
        self, status: Optional[ExtensionStatus] = None
    ) -> List[ExtensionDBModel]:
        """List all extensions from database, optionally filtered by status."""
        if not self.db_session:
            return []

        query = select(ExtensionDBModel)
        if status:
            query = query.where(ExtensionDBModel.status == status)

        result = await self.db_session.execute(query)
        return list(result.scalars().all())

    async def update_extension_status(
        self,
        extension_id: uuid.UUID,
        status: ExtensionStatus,
        error_message: Optional[str] = None,
    ):
        """Update extension status in database."""
        if not self.db_session:
            return

        update_data = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }

        if error_message:
            update_data.update(
                {
                    "error_message": error_message,
                    "error_count": ExtensionDBModel.error_count + 1,
                    "last_error_at": datetime.utcnow(),
                }
            )
        elif status == ExtensionStatus.ACTIVE:
            update_data["loaded_at"] = datetime.utcnow()

        await self.db_session.execute(
            update(ExtensionDBModel)
            .where(ExtensionDBModel.id == extension_id)
            .values(**update_data)
        )
        await self.db_session.flush()

    def register_loaded_instance(self, record: ExtensionRecord):
        """Called by the Host after successful loading."""
        self._loaded_extensions[record.manifest.name] = record
        logger.debug(
            f"Registry updated: {record.manifest.name} is now {record.status.value}"
        )

    def unload_extension(self, extension_id: str) -> bool:
        """Remove a loaded extension record from the runtime registry."""
        removed = self._loaded_extensions.pop(extension_id, None)
        if removed:
            logger.debug("Registry unloaded extension: %s", extension_id)
            return True
        return False

    async def get_extensions_for_hook(self, hook_point: Any) -> List[ExtensionDBModel]:
        """Return extensions that are assigned to a specific hook point."""
        if not self.db_session:
            return []

        hook_value = getattr(hook_point, "value", str(hook_point))

        # Get active hook assignments for this hook point
        result = await self.db_session.execute(
            select(ExtensionHookAssignment)
            .where(
                and_(
                    ExtensionHookAssignment.hook_point == hook_value,
                    ExtensionHookAssignment.is_active == True,
                )
            )
            .order_by(ExtensionHookAssignment.hook_priority.desc())
        )

        assignments = list(result.scalars().all())

        # Get the actual extension records
        extensions = []
        for assignment in assignments:
            ext = await self.get_extension_by_id(assignment.extension_id)
            if ext and ext.status == ExtensionStatus.ACTIVE:
                extensions.append(ext)

        return extensions

    async def assign_hook(
        self, extension_id: uuid.UUID, hook_point: str, priority: int = 0
    ):
        """Assign an extension to a hook point."""
        if not self.db_session:
            return

        # Check if assignment already exists
        result = await self.db_session.execute(
            select(ExtensionHookAssignment).where(
                and_(
                    ExtensionHookAssignment.extension_id == extension_id,
                    ExtensionHookAssignment.hook_point == hook_point,
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing assignment
            await self.db_session.execute(
                update(ExtensionHookAssignment)
                .where(ExtensionHookAssignment.id == existing.id)
                .values(hook_priority=priority, is_active=True)
            )
        else:
            # Create new assignment
            assignment = ExtensionHookAssignment(
                extension_id=extension_id,
                hook_point=hook_point,
                hook_priority=priority,
            )
            self.db_session.add(assignment)

        await self.db_session.flush()

    async def unassign_hook(self, extension_id: uuid.UUID, hook_point: str):
        """Remove an extension from a hook point."""
        if not self.db_session:
            return

        await self.db_session.execute(
            delete(ExtensionHookAssignment).where(
                and_(
                    ExtensionHookAssignment.extension_id == extension_id,
                    ExtensionHookAssignment.hook_point == hook_point,
                )
            )
        )
        await self.db_session.flush()

    def to_dict(self) -> Dict[str, Any]:
        """Convert registry to dictionary format."""
        return {
            "total_discovered": len(self._discovery_metadata),
            "total_active": len(
                [
                    r
                    for r in self._loaded_extensions.values()
                    if r.status == ExtensionStatus.ACTIVE
                ]
            ),
            "extensions": {
                name: {
                    "version": meta.version,
                    "status": self._loaded_extensions[name].status.value
                    if name in self._loaded_extensions
                    else "discovered",
                    "category": meta.category,
                    "is_valid": meta.is_valid,
                }
                for name, meta in self._discovery_metadata.items()
            },
        }


# Singleton accessor
_registry_instance: Optional[PluginRegistry] = None


def get_registry() -> PluginRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PluginRegistry()
    return _registry_instance


PluginStatus = ExtensionStatus
