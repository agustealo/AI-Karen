"""
UI Installer Service for Karen Plugin System

This service handles the complete frontend UI lifecycle including installation,
removal, restoration, and validation of GUI packages for plugins.

Requirements: 3.1, 3.2, 3.3, 3.4, 22, 23, 24, 34, 35
"""

import os
import shutil
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime

from .plugin_registry import get_registry
from .canonical_validator import get_validator
from .manifest_enforcer import get_enforcer


logger = logging.getLogger(__name__)


class UIInstallationState(Enum):
    """States of UI installation lifecycle."""

    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    INSTALLED = "installed"
    REGISTERED = "registered"
    MOUNTED = "mounted"
    ERROR = "error"
    RESTORING = "restoring"
    REMOVING = "removing"


class UIInstallationStatus(Enum):
    """Status codes for UI operations."""

    SUCCESS = "success"
    PENDING = "pending"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


@dataclass
class UIInstallationResult:
    """Result of a UI installation operation."""

    plugin_id: str
    status: UIInstallationStatus
    state: UIInstallationState
    message: str
    details: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None


@dataclass
class UIPackageInfo:
    """Information about a UI package."""

    plugin_id: str
    source_path: Path
    target_path: Path
    manifest_path: Path
    entry_file: Path
    checksum: str
    size_bytes: int
    installed_at: Optional[datetime] = None
    last_validated: Optional[datetime] = None


class UIInstallerService:
    """Service for managing frontend UI package lifecycle."""

    def __init__(
        self,
        plugins_repo_root: str = "src/ui_launchers/Karen-AI-Theme/src/plugin_repo",
        backup_dir: str = "src/ui_launchers/Karen-AI-Theme/src/plugin_repo_backups",
    ):
        self.plugins_repo_root = Path(plugins_repo_root)
        self.backup_dir = Path(backup_dir)
        self.registry = get_registry()
        self.validator = get_validator()
        self.manifest_enforcer = get_enforcer()

        # Ensure directories exist
        self.plugins_repo_root.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Track installations
        self.installations: Dict[str, UIPackageInfo] = {}
        self._load_installations()

    def _load_installations(self) -> None:
        """Load existing installations from plugin_repo."""
        if not self.plugins_repo_root.exists():
            return

        for plugin_dir in self.plugins_repo_root.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.is_symlink():
                plugin_id = plugin_dir.name
                if not plugin_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in plugin_id):
                    logger.warning("Skipping unsafe plugin package identifier")
                    continue
                manifest_path = plugin_dir / "manifest.json"
                
                if manifest_path.is_file() and not manifest_path.is_symlink():
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                        
                        # Check for entry file
                        entry = manifest.get("entry", {})
                        entry_file_rel = None
                        if isinstance(entry, dict) and entry.get("entry_file"):
                            entry_file_rel = entry.get("entry_file")
                        elif manifest.get("entry_file"):
                            entry_file_rel = manifest.get("entry_file")
                        else:
                            entry_file_rel = f"{plugin_id}.tsx"
                        
                        # A manifest must not escape its own plugin directory.
                        if not isinstance(entry_file_rel, str) or not entry_file_rel:
                            continue
                        entry_file = plugin_dir / entry_file_rel
                        if (
                            Path(entry_file_rel).is_absolute()
                            or ".." in Path(entry_file_rel).parts
                            or entry_file.resolve().is_relative_to(plugin_dir.resolve()) is False
                            or entry_file.is_symlink()
                        ):
                            logger.warning("Skipping plugin with unsafe UI entry path: %s", plugin_id)
                            continue

                        if entry_file.is_file():
                            package_info = UIPackageInfo(
                                plugin_id=plugin_id,
                                source_path=Path("src/ai_karen_engine/extensions/plugins")
                                / plugin_id,
                                target_path=plugin_dir,
                                manifest_path=manifest_path,
                                entry_file=entry_file,
                                # Restart discovery is not an integrity attestation.
                                # The original install checksum is not durable yet.
                                checksum="",
                                size_bytes=self._get_directory_size(plugin_dir),
                                installed_at=datetime.fromtimestamp(
                                    manifest_path.stat().st_mtime
                                ),
                                last_validated=datetime.now(),
                            )

                            self.installations[plugin_id] = package_info
                            logger.info(f"Loaded existing UI installation: {plugin_id}")
                        else:
                            logger.warning(f"Skipping {plugin_id}: missing entry file {entry_file}")

                    except Exception as e:
                        logger.error(f"Failed to load UI installation {plugin_id}: {e}")

    def _calculate_checksum(self, path: Path) -> str:
        """Calculate checksum of a directory."""
        hash_sha256 = hashlib.sha256()
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = Path(root) / file
                try:
                    with open(file_path, "rb") as f:
                        hash_sha256.update(f.read())
                except (IOError, OSError):
                    continue
        return hash_sha256.hexdigest()

    def _get_directory_size(self, path: Path) -> int:
        """Get size of directory in bytes."""
        total_size = 0
        for root, dirs, files in os.walk(path):
            for file in files:
                file_path = Path(root) / file
                try:
                    total_size += file_path.stat().st_size
                except (IOError, OSError):
                    continue
        return total_size

    def _backup_package(self, plugin_id: str) -> Optional[Path]:
        """Create a backup of existing UI package."""
        package_path = self.plugins_repo_root / plugin_id
        if not package_path.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"{plugin_id}_{timestamp}"

        try:
            shutil.copytree(package_path, backup_path)
            logger.info(f"Created backup for {plugin_id}: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to create backup for {plugin_id}: {e}")
            return None

    def install_ui(self, plugin_id: str, category: str) -> UIInstallationResult:
        """Install UI for a plugin from canonical source to plugin_repo."""
        try:
            # Treat plugin IDs as identifiers, never filesystem paths.
            if (
                not plugin_id
                or plugin_id in {".", ".."}
                or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in plugin_id)
            ):
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.VALIDATION_FAILED,
                    state=UIInstallationState.ERROR,
                    message="Invalid plugin identifier",
                    error_code="INVALID_PLUGIN_ID",
                )
            source_path = Path("src/ai_karen_engine/extensions/plugins") / plugin_id
            if not source_path.exists():
                alt_underscore_path = Path("src/ai_karen_engine/extensions/plugins") / plugin_id.replace('-', '_')
                if alt_underscore_path.exists():
                    source_path = alt_underscore_path
                else:
                    return UIInstallationResult(
                        plugin_id=plugin_id,
                        status=UIInstallationStatus.NOT_FOUND,
                        state=UIInstallationState.ERROR,
                        message=f"Plugin not found in canonical location: {source_path}",
                        error_code="PLUGIN_NOT_FOUND",
                    )

            # A package source must stay inside the trusted plugin tree.
            # Refuse links rather than following them into unrelated files.
            if source_path.is_symlink() or any(
                item.is_symlink() for item in source_path.rglob("*")
            ):
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.VALIDATION_FAILED,
                    state=UIInstallationState.ERROR,
                    message="Linked plugin source files are not allowed",
                    error_code="UNSAFE_SOURCE",
                )

            target_path = self.plugins_repo_root / plugin_id
            if target_path.is_symlink():
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.VALIDATION_FAILED,
                    state=UIInstallationState.ERROR,
                    message="Linked plugin installation paths are not allowed",
                    error_code="UNSAFE_TARGET",
                )

            # Repeated installation requests are idempotent when the current
            # package still validates. Never label an installed UI as broken.
            if plugin_id in self.installations:
                existing = self.validate_ui_package(plugin_id)
                if existing.status == UIInstallationStatus.SUCCESS:
                    return UIInstallationResult(
                        plugin_id=plugin_id,
                        status=UIInstallationStatus.SUCCESS,
                        state=UIInstallationState.INSTALLED,
                        message=f"UI already installed for plugin: {plugin_id}",
                    )
                return existing

            # Do not overwrite an untracked package. This is not a repair
            # operation and must not silently destroy an unknown installation.
            if target_path.exists():
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.CONFLICT,
                    state=UIInstallationState.ERROR,
                    message="Existing UI package is not registered; repair required",
                    error_code="UNTRACKED_INSTALLATION",
                )
            backup_path = None

            # Validate source structure
            validation_report = self.validator.validate_plugin_structure(
                category, plugin_id
            )
            if not validation_report.is_valid:
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.VALIDATION_FAILED,
                    state=UIInstallationState.ERROR,
                    message=f"Plugin validation failed: {validation_report.errors[0].message}",
                    error_code="VALIDATION_FAILED",
                )

            # Validate manifests
            manifest_results = self.manifest_enforcer.validate_plugin_manifests(
                category, plugin_id
            )
            for manifest_type, results in manifest_results.items():
                for result in results:
                    if result.severity.value == "error":
                        return UIInstallationResult(
                            plugin_id=plugin_id,
                            status=UIInstallationStatus.VALIDATION_FAILED,
                            state=UIInstallationState.ERROR,
                            message=f"Manifest validation failed: {result.message}",
                            error_code="MANIFEST_VALIDATION_FAILED",
                        )

            # Copy UI package to plugin_repo
            target_path = self.plugins_repo_root / plugin_id
            ui_source = source_path / "ui"
            try:
                # Ensure target directory exists
                target_path.mkdir(parents=True, exist_ok=True)

                if ui_source.exists() and ui_source.is_dir():
                    # Copy contents of ui directory
                    for item in ui_source.iterdir():
                        if item.is_dir():
                            shutil.copytree(item, target_path / item.name, dirs_exist_ok=True)
                        else:
                            shutil.copy2(item, target_path / item.name)
                    
                    # Also copy manifest.json from root if it exists
                    manifest_source = source_path / "manifest.json"
                    if manifest_source.exists():
                        shutil.copy2(manifest_source, target_path / "manifest.json")
                    
                    logger.info(f"Copied UI artifacts from {ui_source} to {target_path}")
                else:
                    # Fallback to copying entire source if no ui directory
                    shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                    logger.info(f"Copied entire plugin source from {source_path} to {target_path}")
            except Exception as e:
                # No valid package existed before this call. Delete only the
                # partial directory created by this installation attempt.
                if target_path.is_dir() and not target_path.is_symlink():
                    shutil.rmtree(target_path, ignore_errors=True)
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.FAILED,
                    state=UIInstallationState.ERROR,
                    message=f"Failed to copy UI package: {e}",
                    error_code="COPY_FAILED",
                )

            # Create package info
            manifest_path = target_path / "manifest.json"
            entry_file = target_path / f"{plugin_id}.tsx"

            package_info = UIPackageInfo(
                plugin_id=plugin_id,
                source_path=source_path,
                target_path=target_path,
                manifest_path=manifest_path,
                entry_file=entry_file,
                checksum=self._calculate_checksum(target_path),
                size_bytes=self._get_directory_size(target_path),
                installed_at=datetime.now(),
                last_validated=datetime.now(),
            )

            # Register installation
            self.installations[plugin_id] = package_info

            # Update registry to reflect UI installation
            try:
                # This would call the backend API to mark plugin as UI-installed
                # For now, we'll simulate it
                logger.info(f"Registered UI installation for {plugin_id}")
            except Exception as e:
                logger.error(f"Failed to register UI installation: {e}")
                # Rollback
                shutil.rmtree(target_path, ignore_errors=True)
                if plugin_id in self.installations:
                    del self.installations[plugin_id]
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.FAILED,
                    state=UIInstallationState.ERROR,
                    message=f"Failed to register UI installation: {e}",
                    error_code="REGISTRATION_FAILED",
                )

            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.SUCCESS,
                state=UIInstallationState.INSTALLED,
                message="UI package installed successfully",
                details={
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "checksum": package_info.checksum,
                    "size_bytes": package_info.size_bytes,
                },
            )

        except Exception as e:
            logger.error(f"Failed to install UI for {plugin_id}: {e}")
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.FAILED,
                state=UIInstallationState.ERROR,
                message=f"Installation failed: {e}",
                error_code="INSTALLATION_FAILED",
            )

    def remove_ui(self, plugin_id: str) -> UIInstallationResult:
        """Remove UI package from plugin_repo."""
        try:
            # Check if installed
            if plugin_id not in self.installations:
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.NOT_FOUND,
                    state=UIInstallationState.NOT_INSTALLED,
                    message=f"UI not installed for plugin: {plugin_id}",
                    error_code="NOT_INSTALLED",
                )

            package_info = self.installations[plugin_id]
            expected = self.plugins_repo_root / plugin_id
            # Persisted inventory entries are untrusted until their delete
            # target is proven to belong to this exact plugin directory.
            if (
                not plugin_id
                or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in plugin_id)
                or package_info.target_path.absolute() != expected.absolute()
                or package_info.target_path.is_symlink()
                or self.plugins_repo_root.is_symlink()
                or not expected.is_dir()
            ):
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.VALIDATION_FAILED,
                    state=UIInstallationState.ERROR,
                    message="Plugin removal target does not match the registered package",
                    error_code="UNSAFE_REMOVAL_TARGET",
                )

            backup_path = self._backup_package(plugin_id)

            # Remove package
            try:
                shutil.rmtree(package_info.target_path)
                logger.info(f"Removed UI package: {package_info.target_path}")
            except Exception as e:
                if backup_path:
                    shutil.move(backup_path, package_info.target_path)
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.FAILED,
                    state=UIInstallationState.ERROR,
                    message=f"Failed to remove UI package: {e}",
                    error_code="REMOVAL_FAILED",
                )

            # Unregister installation
            del self.installations[plugin_id]

            # Update registry to reflect UI removal
            try:
                # This would call the backend API to mark plugin as UI-removed
                # For now, we'll simulate it
                logger.info(f"Unregistered UI installation for {plugin_id}")
            except Exception as e:
                logger.error(f"Failed to unregister UI installation: {e}")
                # Try to restore
                if backup_path:
                    shutil.copytree(backup_path, package_info.target_path)
                    self.installations[plugin_id] = package_info
                return UIInstallationResult(
                    plugin_id=plugin_id,
                    status=UIInstallationStatus.FAILED,
                    state=UIInstallationState.ERROR,
                    message=f"Failed to unregister UI installation: {e}",
                    error_code="UNREGISTRATION_FAILED",
                )

            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.SUCCESS,
                state=UIInstallationState.NOT_INSTALLED,
                message="UI package removed successfully",
                details={
                    "removed_path": str(package_info.target_path),
                    "backup_path": str(backup_path) if backup_path else None,
                },
            )

        except Exception as e:
            logger.error(f"Failed to remove UI for {plugin_id}: {e}")
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.FAILED,
                state=UIInstallationState.ERROR,
                message=f"Removal failed: {e}",
                error_code="REMOVAL_FAILED",
            )

    def restore_ui(self, plugin_id: str, category: str) -> UIInstallationResult:
        """Safely install a missing UI; never destroy an installed package to repair it.

        Replacement requires a staged, verified, transactional lifecycle owner.
        Refusing unsafe replacement is preferable to data loss or false recovery.
        """
        if plugin_id in self.installations:
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.CONFLICT,
                state=UIInstallationState.INSTALLED,
                message="In-place repair requires a verified transactional replacement",
                error_code="REPAIR_REQUIRES_TRANSACTION",
            )
        result = self.install_ui(plugin_id, category)
        if result.status != UIInstallationStatus.SUCCESS:
            return result
        return UIInstallationResult(
            plugin_id=plugin_id,
            status=UIInstallationStatus.SUCCESS,
            state=UIInstallationState.INSTALLED,
            message="UI package restored from canonical source",
            details=result.details,
        )

    def get_ui_state(self, plugin_id: str) -> Dict[str, Any]:
        """Get current state of UI installation."""
        if plugin_id not in self.installations:
            return {
                "state": UIInstallationState.NOT_INSTALLED.value,
                "status": UIInstallationStatus.NOT_FOUND.value,
                "message": "UI not installed",
            }

        package_info = self.installations[plugin_id]

        # Check if files still exist
        files_exist = (
            package_info.manifest_path.exists()
            and package_info.entry_file.exists()
            and package_info.target_path.exists()
        )

        if not files_exist:
            # Clean up invalid installation
            del self.installations[plugin_id]
            return {
                "state": UIInstallationState.NOT_INSTALLED.value,
                "status": UIInstallationStatus.NOT_FOUND.value,
                "message": "UI files missing",
            }

        # Unknown baselines are *not* valid checksums. Never silently trust
        # modified or unverified files just because they survived a restart.
        current_checksum = self._calculate_checksum(package_info.target_path)
        checksum_valid = bool(package_info.checksum) and current_checksum == package_info.checksum

        return {
            "state": UIInstallationState.INSTALLED.value,
            "status": UIInstallationStatus.SUCCESS.value
            if checksum_valid
            else UIInstallationStatus.VALIDATION_FAILED.value,
            "message": "UI installed" if checksum_valid else "UI files corrupted",
            "details": {
                "source_path": str(package_info.source_path),
                "target_path": str(package_info.target_path),
                "installed_at": package_info.installed_at.isoformat()
                if package_info.installed_at
                else None,
                "last_validated": package_info.last_validated.isoformat()
                if package_info.last_validated
                else None,
                "checksum_valid": checksum_valid,
                "size_bytes": package_info.size_bytes,
            },
        }

    def list_installed_ui(self) -> List[Dict[str, Any]]:
        """List all installed UI packages."""
        installations = []
        for plugin_id, package_info in self.installations.items():
            installations.append(
                {"plugin_id": plugin_id, **self.get_ui_state(plugin_id)}
            )
        return installations

    def validate_ui_package(self, plugin_id: str) -> UIInstallationResult:
        """Validate an installed UI package."""
        if plugin_id not in self.installations:
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.NOT_FOUND,
                state=UIInstallationState.ERROR,
                message=f"UI not installed for plugin: {plugin_id}",
                error_code="NOT_INSTALLED",
            )

        package_info = self.installations[plugin_id]

        # Check if files exist
        if not (
            package_info.manifest_path.exists() and package_info.entry_file.exists()
        ):
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.VALIDATION_FAILED,
                state=UIInstallationState.ERROR,
                message="Required UI files missing",
                error_code="FILES_MISSING",
            )

        # Files rediscovered after restart lack a durable trusted baseline.
        if not package_info.checksum:
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.VALIDATION_FAILED,
                state=UIInstallationState.ERROR,
                message="UI package integrity cannot be verified after restart",
                error_code="INTEGRITY_BASELINE_UNAVAILABLE",
            )

        current_checksum = self._calculate_checksum(package_info.target_path)
        if current_checksum != package_info.checksum:
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.VALIDATION_FAILED,
                state=UIInstallationState.ERROR,
                message="UI files corrupted (checksum mismatch)",
                error_code="CHECKSUM_MISMATCH",
            )

        # Validate manifests
        try:
            with open(package_info.manifest_path, "r") as f:
                manifest = json.load(f)

            category = manifest.get("category", "integration")
            manifest_results = self.manifest_enforcer.validate_plugin_manifests(
                category, plugin_id
            )

            for manifest_type, results in manifest_results.items():
                for result in results:
                    if result.severity.value == "error":
                        return UIInstallationResult(
                            plugin_id=plugin_id,
                            status=UIInstallationStatus.VALIDATION_FAILED,
                            state=UIInstallationState.ERROR,
                            message=f"Manifest validation failed: {result.message}",
                            error_code="MANIFEST_VALIDATION_FAILED",
                        )

        except Exception as e:
            return UIInstallationResult(
                plugin_id=plugin_id,
                status=UIInstallationStatus.VALIDATION_FAILED,
                state=UIInstallationState.ERROR,
                message=f"Manifest validation error: {e}",
                error_code="MANIFEST_ERROR",
            )

        # Update validation timestamp
        package_info.last_validated = datetime.now()
        self.installations[plugin_id] = package_info

        return UIInstallationResult(
            plugin_id=plugin_id,
            status=UIInstallationStatus.SUCCESS,
            state=UIInstallationState.INSTALLED,
            message="UI package validation successful",
            details={
                "checksum": current_checksum,
                "validated_at": package_info.last_validated.isoformat(),
            },
        )


# Global service instance
_ui_service: Optional[UIInstallerService] = None


def get_ui_service() -> UIInstallerService:
    """Get the global UI installer service instance."""
    global _ui_service
    if _ui_service is None:
        _ui_service = UIInstallerService()
    return _ui_service


def install_ui(plugin_id: str, category: str) -> UIInstallationResult:
    """Install UI for a plugin."""
    service = get_ui_service()
    return service.install_ui(plugin_id, category)


def remove_ui(plugin_id: str) -> UIInstallationResult:
    """Remove UI for a plugin."""
    service = get_ui_service()
    return service.remove_ui(plugin_id)


def restore_ui(plugin_id: str, category: str) -> UIInstallationResult:
    """Restore UI for a plugin."""
    service = get_ui_service()
    return service.restore_ui(plugin_id, category)


def get_ui_state(plugin_id: str) -> Dict[str, Any]:
    """Get UI state for a plugin."""
    service = get_ui_service()
    return service.get_ui_state(plugin_id)


def list_installed_ui() -> List[Dict[str, Any]]:
    """List all installed UI packages."""
    service = get_ui_service()
    return service.list_installed_ui()


def validate_ui_package(plugin_id: str) -> UIInstallationResult:
    """Validate an installed UI package."""
    service = get_ui_service()
    return service.validate_ui_package(plugin_id)
