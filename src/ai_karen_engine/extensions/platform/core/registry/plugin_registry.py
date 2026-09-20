"""Catalog registry for discovered extension metadata.

This registry owns filesystem discovery and optional catalog persistence only.
It deliberately stores no live plugin instances and performs no runtime
selection or execution. ``PluginKernel`` projects valid catalog entries into
the canonical typed runtime registry.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..manifest import ExtensionStatus
from .database_models import ExtensionDBModel, ExtensionHookAssignment
from .discovery import ExtensionDiscoveryService, ExtensionMetadata
from .validator import ExtensionValidator

logger = logging.getLogger("kari.plugin_registry")


class PluginRegistry:
    """Filesystem/catalog discovery authority for extensions and plugins."""

    def __init__(
        self,
        extensions_dir: str = "src/ai_karen_engine/extensions/plugins",
        db_session: Optional[AsyncSession] = None,
    ) -> None:
        self.validator = ExtensionValidator()
        self.discovery = ExtensionDiscoveryService(
            extensions_dir,
            validator=self.validator,
        )
        self.db_session = db_session
        self._discovery_metadata: Dict[str, ExtensionMetadata] = {}

    async def initialize(self) -> None:
        """Initialize catalog discovery without constructing runtime instances."""
        try:
            await self.refresh()
        except Exception:
            logger.exception("Failed to initialize extension catalog registry")
            raise

    async def refresh(self) -> None:
        """Re-scan extension manifests and synchronize catalog persistence."""
        self._discovery_metadata = await self.discovery.discover_extensions(
            force_refresh=True
        )
        await self._sync_with_database()
        logger.info(
            "Catalog registry refreshed: %d discovered extensions",
            len(self._discovery_metadata),
        )

    async def _sync_with_database(self) -> None:
        """Persist discovered catalog metadata when a DB session is available."""
        if not self.db_session:
            logger.debug("No database session available; skipping catalog DB sync")
            return

        for name, metadata in self._discovery_metadata.items():
            try:
                result = await self.db_session.execute(
                    select(ExtensionDBModel).where(
                        and_(
                            ExtensionDBModel.name == name,
                            ExtensionDBModel.version == metadata.version,
                        )
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is not None:
                    continue

                self.db_session.add(
                    ExtensionDBModel(
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
                )
                await self.db_session.flush()
                logger.debug("Added catalog record: %s v%s", name, metadata.version)
            except Exception:
                logger.exception("Failed to sync catalog extension %s", name)
                raise

    def get_metadata(self, extension_id: str) -> Optional[ExtensionMetadata]:
        """Return discovery metadata for one catalog entry."""
        return self._discovery_metadata.get(extension_id)

    def list_discovered(self) -> List[str]:
        """Return discovered catalog identifiers."""
        return list(self._discovery_metadata)

    async def get_extension_by_name(self, name: str) -> Optional[ExtensionDBModel]:
        """Return a persisted catalog record by name."""
        if not self.db_session:
            return None
        result = await self.db_session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.name == name)
        )
        return result.scalar_one_or_none()

    async def get_extension_by_id(
        self,
        extension_id: uuid.UUID,
    ) -> Optional[ExtensionDBModel]:
        """Return a persisted catalog record by UUID."""
        if not self.db_session:
            return None
        result = await self.db_session.execute(
            select(ExtensionDBModel).where(ExtensionDBModel.id == str(extension_id))
        )
        return result.scalar_one_or_none()

    async def list_all_extensions(
        self,
        status: Optional[ExtensionStatus] = None,
    ) -> List[ExtensionDBModel]:
        """List persisted catalog records, optionally filtered by status."""
        if not self.db_session:
            return []
        query = select(ExtensionDBModel)
        if status is not None:
            query = query.where(ExtensionDBModel.status == status)
        result = await self.db_session.execute(query)
        return list(result.scalars().all())

    async def update_extension_status(
        self,
        extension_id: uuid.UUID,
        status: ExtensionStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Update persisted catalog status without mutating runtime state."""
        if not self.db_session:
            return

        update_data: Dict[str, Any] = {
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

    async def assign_hook(
        self,
        extension_id: uuid.UUID,
        hook_point: str,
        priority: int = 0,
    ) -> None:
        """Persist hook-assignment metadata; this does not execute the hook."""
        if not self.db_session:
            return

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
            await self.db_session.execute(
                update(ExtensionHookAssignment)
                .where(ExtensionHookAssignment.id == existing.id)
                .values(hook_priority=priority, is_active=True)
            )
        else:
            self.db_session.add(
                ExtensionHookAssignment(
                    extension_id=extension_id,
                    hook_point=hook_point,
                    hook_priority=priority,
                )
            )
        await self.db_session.flush()

    async def unassign_hook(self, extension_id: uuid.UUID, hook_point: str) -> None:
        """Remove persisted hook-assignment metadata."""
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
        """Serialize catalog truth without inventing runtime activation state."""
        return {
            "authority": "catalog",
            "runtime_authority": "PluginKernel",
            "total_discovered": len(self._discovery_metadata),
            "total_valid": sum(
                1 for metadata in self._discovery_metadata.values() if metadata.is_valid
            ),
            "extensions": {
                name: {
                    "version": metadata.version,
                    "category": metadata.category,
                    "is_valid": metadata.is_valid,
                    "validation_errors": list(metadata.validation_errors),
                }
                for name, metadata in self._discovery_metadata.items()
            },
        }


_registry_instance: Optional[PluginRegistry] = None


def get_registry() -> PluginRegistry:
    """Return the singleton catalog registry, never a runtime registry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = PluginRegistry()
    return _registry_instance


PluginStatus = ExtensionStatus
