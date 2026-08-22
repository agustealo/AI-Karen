"""
Unified Extension Registry

Consolidates the best features from both platform/core and runtime registry systems.
Provides a single source of truth for extension management with database persistence,
discovery, validation, and state management.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import uuid
from enum import Enum

from ..database_models import ExtensionModel, ExtensionState
from ...platform.core.manifest import ExtensionManifest
from ...platform.core.registry.database_service import ExtensionDatabaseService
from ...platform.core.registry.discovery import ExtensionDiscoveryService
from ...platform.core.registry.manifest_enforcer import ManifestStandardsEnforcer

logger = logging.getLogger(__name__)


class ExtensionRegistry:
    """Unified extension registry with database persistence and discovery."""

    def __init__(self, database_service: Optional[ExtensionDatabaseService] = None):
        self.database_service = database_service or ExtensionDatabaseService()
        self.discovery = ExtensionDiscoveryService()
        self.manifest_enforcer = ManifestStandardsEnforcer()
        self._cache: Dict[str, ExtensionModel] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize the registry with database connection and discovery."""
        await self.database_service.initialize()
        await self.discovery.initialize()
        await self.manifest_enforcer.initialize()

        # Load existing extensions from database
        await self._load_from_database()

    async def register_extension(
        self,
        manifest: ExtensionManifest,
        extension_path: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtensionModel:
        """Register a new extension with validation and persistence."""
        async with self._lock:
            # Validate manifest
            validation_result = await self.manifest_enforcer.validate_manifest(manifest)
            if not validation_result.valid:
                raise ValueError(f"Invalid manifest: {validation_result.errors}")

            # Check for conflicts
            existing = await self.get_extension_by_name(manifest.name)
            if existing and existing.state != ExtensionState.UNINSTALLED:
                raise ValueError(f"Extension {manifest.name} already exists")

            # Create extension model
            extension = ExtensionModel(
                id=str(uuid.uuid4()),
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                author=manifest.author,
                extension_path=extension_path,
                manifest=manifest.to_dict(),
                metadata=metadata or {},
                state=ExtensionState.INSTALLED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

            # Save to database
            await self.database_service.save_extension(extension)

            # Update cache
            self._cache[extension.id] = extension

            # Trigger discovery
            await self.discovery.discover_extension(extension)

            logger.info(f"Registered extension: {manifest.name} v{manifest.version}")
            return extension

    async def get_extension(self, extension_id: str) -> Optional[ExtensionModel]:
        """Get extension by ID with cache lookup."""
        # Check cache first
        if extension_id in self._cache:
            return self._cache[extension_id]

        # Load from database
        extension = await self.database_service.get_extension(extension_id)
        if extension:
            self._cache[extension_id] = extension
            return extension

        return None

    async def get_extension_by_name(self, name: str) -> Optional[ExtensionModel]:
        """Get extension by name."""
        # Check cache first
        for extension in self._cache.values():
            if extension.name == name:
                return extension

        # Load from database
        return await self.database_service.get_extension_by_name(name)

    async def list_extensions(
        self, state: Optional[ExtensionState] = None, author: Optional[str] = None
    ) -> List[ExtensionModel]:
        """List extensions with optional filtering."""
        extensions = await self.database_service.list_extensions(state, author)

        # Update cache
        for extension in extensions:
            self._cache[extension.id] = extension

        return extensions

    async def update_extension(
        self, extension_id: str, updates: Dict[str, Any]
    ) -> ExtensionModel:
        """Update extension metadata or state."""
        async with self._lock:
            extension = await self.get_extension(extension_id)
            if not extension:
                raise ValueError(f"Extension {extension_id} not found")

            # Apply updates
            for key, value in updates.items():
                if hasattr(extension, key):
                    setattr(extension, key, value)

            extension.updated_at = datetime.now(timezone.utc)

            # Save to database
            await self.database_service.save_extension(extension)

            # Update cache
            self._cache[extension_id] = extension

            logger.info(f"Updated extension: {extension.name}")
            return extension

    async def uninstall_extension(self, extension_id: str) -> ExtensionModel:
        """Uninstall an extension."""
        async with self._lock:
            extension = await self.get_extension(extension_id)
            if not extension:
                raise ValueError(f"Extension {extension_id} not found")

            extension.state = ExtensionState.UNINSTALLED
            extension.updated_at = datetime.now(timezone.utc)

            # Save to database
            await self.database_service.save_extension(extension)

            # Update cache
            self._cache[extension_id] = extension

            # Remove from discovery
            await self.discovery.remove_extension(extension)

            logger.info(f"Uninstalled extension: {extension.name}")
            return extension

    async def enable_extension(self, extension_id: str) -> ExtensionModel:
        """Enable an extension."""
        async with self._lock:
            extension = await self.get_extension(extension_id)
            if not extension:
                raise ValueError(f"Extension {extension_id} not found")

            extension.state = ExtensionState.ENABLED
            extension.updated_at = datetime.now(timezone.utc)

            # Save to database
            await self.database_service.save_extension(extension)

            # Update cache
            self._cache[extension_id] = extension

            # Trigger discovery
            await self.discovery.discover_extension(extension)

            logger.info(f"Enabled extension: {extension.name}")
            return extension

    async def disable_extension(self, extension_id: str) -> ExtensionModel:
        """Disable an extension."""
        async with self._lock:
            extension = await self.get_extension(extension_id)
            if not extension:
                raise ValueError(f"Extension {extension_id} not found")

            extension.state = ExtensionState.DISABLED
            extension.updated_at = datetime.now(timezone.utc)

            # Save to database
            await self.database_service.save_extension(extension)

            # Update cache
            self._cache[extension_id] = extension

            # Remove from discovery
            await self.discovery.remove_extension(extension)

            logger.info(f"Disabled extension: {extension.name}")
            return extension

    async def get_extension_dependencies(
        self, extension_id: str
    ) -> List[ExtensionModel]:
        """Get dependencies for an extension."""
        extension = await self.get_extension(extension_id)
        if not extension:
            return []

        dependencies = []
        for dep_name in extension.manifest.get("dependencies", []):
            dep = await self.get_extension_by_name(dep_name)
            if dep:
                dependencies.append(dep)

        return dependencies

    async def get_extension_dependents(self, extension_id: str) -> List[ExtensionModel]:
        """Get extensions that depend on this extension."""
        all_extensions = await self.list_extensions()
        dependents = []

        for extension in all_extensions:
            if extension.state in [ExtensionState.ENABLED, ExtensionState.INSTALLED]:
                dependencies = extension.manifest.get("dependencies", [])
                if extension_id in dependencies:
                    dependents.append(extension)

        return dependents

    async def can_uninstall_extension(self, extension_id: str) -> bool:
        """Check if extension can be safely uninstalled."""
        dependents = await self.get_extension_dependents(extension_id)
        return len(dependents) == 0

    async def validate_extension_compatibility(
        self, extension_id: str
    ) -> Dict[str, Any]:
        """Validate extension compatibility with system and other extensions."""
        extension = await self.get_extension(extension_id)
        if not extension:
            return {"valid": False, "errors": ["Extension not found"]}

        errors = []

        # Check manifest compatibility
        manifest_errors = await self.manifest_enforcer.validate_manifest(
            ExtensionManifest.from_dict(extension.manifest)
        )
        if not manifest_errors.valid:
            errors.extend(manifest_errors.errors)

        # Check dependency compatibility
        for dep_name in extension.manifest.get("dependencies", []):
            dep = await self.get_extension_by_name(dep_name)
            if not dep:
                errors.append(f"Missing dependency: {dep_name}")
            elif dep.state != ExtensionState.ENABLED:
                errors.append(f"Dependency {dep_name} is not enabled")

        # Check system requirements
        system_reqs = extension.manifest.get("system_requirements", {})
        if not await self._check_system_requirements(system_reqs):
            errors.append("System requirements not met")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": await self._get_compatibility_warnings(extension_id),
        }

    async def _load_from_database(self) -> None:
        """Load all extensions from database into cache."""
        extensions = await self.database_service.list_extensions()
        for extension in extensions:
            self._cache[extension.id] = extension

        logger.info(f"Loaded {len(extensions)} extensions from database")

    async def _check_system_requirements(self, requirements: Dict[str, Any]) -> bool:
        """Check if system meets extension requirements."""
        # This should be implemented with actual system checks
        # For now, return True as a placeholder
        return True

    async def _get_compatibility_warnings(self, extension_id: str) -> List[str]:
        """Get compatibility warnings for an extension."""
        # This should be implemented with actual compatibility checks
        # For now, return empty list as a placeholder
        return []
