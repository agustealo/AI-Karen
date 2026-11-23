"""
Manifest Standards Enforcer for Karen Plugin System

This module enforces the manifest standards defined in the authority model.
It ensures that all plugins follow the standardized manifest formats and locations.

Requirements: 2.4, 5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 38, 39
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
from pydantic import BaseModel, validator, ValidationError, StrictBool, StrictStr


class ManifestType(Enum):
    """Types of manifest files."""
    ROOT = "root"
    GUI = "gui"


class ManifestValidationSeverity(Enum):
    """Severity levels for manifest validation."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ManifestValidationResult:
    """Result of a manifest validation."""
    manifest_type: ManifestType
    severity: ManifestValidationSeverity
    field: str
    message: str
    suggestion: Optional[str] = None
    value: Optional[Any] = None


class RootManifestModel(BaseModel):
    """Model for root manifest validation."""
    id: str
    name: str
    version: str
    category: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    api_version: str = "1.0"
    kari_min_version: str = "0.4.0"
    extension_type: str = "tool_plugin"
    source_type: str = "local"
    entrypoint: str
    hook_points: List[str] = []
    prompt_files: Dict[str, Optional[str]] = {}
    permissions: Dict[str, Union[bool, List[str]]] = {}
    rbac: Dict[str, Any] = {}
    dependencies: Dict[str, List[str]] = {}
    capabilities: Dict[str, bool] = {}
    purpose: Optional[str] = None
    invocation_guidance: Optional[Dict[str, Any]] = None
    actions: Optional[List[Dict[str, Any]]] = None
    ui: Optional[Dict[str, Any]] = None
    tags: List[str] = []
    status: Dict[str, str] = {}

    @validator('category')
    def validate_category(cls, v):
        from .canonical_validator import CanonicalStructureValidator
        validator = CanonicalStructureValidator()
        if not validator.validate_plugin_category(v):
            raise ValueError(f"Invalid category: {v}")
        return v

    @validator('entrypoint')
    def validate_entrypoint(cls, v):
        if ':' not in v:
            raise ValueError("Entrypoint must be in format 'module:function'")
        return v


class GUIEntryModel(BaseModel):
    """Typed GUI entry metadata; never a Python execution declaration."""

    id: StrictStr
    default: StrictBool = False
    entry_file: StrictStr

    @validator("id")
    def validate_id(cls, value):
        if not value.strip():
            raise ValueError("GUI entry id must be non-empty")
        return value

    @validator("entry_file")
    def validate_entry_file(cls, value):
        path = Path(value)
        if (
            not value
            or value != value.strip()
            or "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or path.suffix not in {".tsx", ".jsx", ".ts", ".js"}
        ):
            raise ValueError("GUI entry_file must be a relative frontend module path")
        return value

    class Config:
        extra = "forbid"


class GUIManifestModel(BaseModel):
    """Model for GUI manifest validation."""
    id: str
    plugin_id: str
    category: str
    gui_manifest_version: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    entry: GUIEntryModel
    contributions: Dict[str, List[Dict[str, Any]]] = {}
    assets: Dict[str, List[str]] = {}
    rbac: Dict[str, Any] = {}
    install: Dict[str, Any] = {}
    validation: Dict[str, Any] = {}

    @validator('category')
    def validate_category(cls, v):
        from .canonical_validator import CanonicalStructureValidator
        validator = CanonicalStructureValidator()
        if not validator.validate_plugin_category(v):
            raise ValueError(f"Invalid category: {v}")
        return v


class ManifestStandardsEnforcer:
    """Enforces manifest standards across all plugins."""

    def __init__(self, extensions_root: str = "src/ai_karen_engine/extensions/plugins"):
        self.extensions_root = Path(extensions_root)
        self.validation_results: Dict[str, List[ManifestValidationResult]] = {}

    def validate_root_manifest(self, manifest_path: Path) -> List[ManifestValidationResult]:
        """Validate a root manifest file."""
        results = []
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.ROOT,
                severity=ManifestValidationSeverity.ERROR,
                field="file",
                message=f"Cannot read manifest file: {e}",
                suggestion="Ensure manifest file exists and contains valid JSON"
            ))
            return results

        try:
            # Validate using Pydantic model
            RootManifestModel(**manifest_data)
        except ValidationError as e:
            for error in e.errors():
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.ROOT,
                    severity=ManifestValidationSeverity.ERROR,
                    field=error["loc"][0] if error["loc"] else "unknown",
                    message=error["msg"],
                    suggestion=self._get_suggestion_for_error(error)
                ))

        # Additional validation checks
        results.extend(self._validate_root_manifest_specific(manifest_data, manifest_path))

        return results

    def validate_gui_manifest(self, manifest_path: Path) -> List[ManifestValidationResult]:
        """Validate a GUI manifest file."""
        results = []
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.GUI,
                severity=ManifestValidationSeverity.ERROR,
                field="file",
                message=f"Cannot read GUI manifest file: {e}",
                suggestion="Ensure GUI manifest file exists and contains valid JSON"
            ))
            return results

        try:
            # Validate using Pydantic model
            GUIManifestModel(**manifest_data)
        except ValidationError as e:
            for error in e.errors():
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.GUI,
                    severity=ManifestValidationSeverity.ERROR,
                    field=error["loc"][0] if error["loc"] else "unknown",
                    message=error["msg"],
                    suggestion=self._get_suggestion_for_error(error)
                ))

        if not isinstance(manifest_data, dict):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.GUI,
                severity=ManifestValidationSeverity.ERROR,
                field="file",
                message="GUI manifest must be a JSON object",
            ))
            return results

        # Additional validation checks
        results.extend(self._validate_gui_manifest_specific(manifest_data, manifest_path))

        return results

    def _validate_root_manifest_specific(self, manifest_data: Dict[str, Any], manifest_path: Path) -> List[ManifestValidationResult]:
        """Root manifest specific validation."""
        results = []
        
        # Check for required UI fields if plugin provides UI
        if manifest_data.get("capabilities", {}).get("provides_ui", False):
            ui_section = manifest_data.get("ui", {})
            if not ui_section.get("has_component"):
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.ROOT,
                    severity=ManifestValidationSeverity.WARNING,
                    field="ui.has_component",
                    message="Plugin declares provides_ui but has_component is not set",
                    suggestion="Set ui.has_component to true when provides_ui is true"
                ))
            
            if not ui_section.get("component_id"):
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.ROOT,
                    severity=ManifestValidationSeverity.WARNING,
                    field="ui.component_id",
                    message="Plugin provides UI but component_id is not specified",
                    suggestion="Add ui.component_id to identify the UI component"
                ))

        # Check prompt files
        prompt_files = manifest_data.get("prompt_files", {})
        if not prompt_files.get("primary"):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.ROOT,
                severity=ManifestValidationSeverity.INFO,
                field="prompt_files.primary",
                message="No primary prompt file specified",
                suggestion="Add prompt_files.primary to specify the main prompt file"
            ))

        # Check for consistency between id and name
        if manifest_data.get("id") != manifest_data.get("name"):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.ROOT,
                severity=ManifestValidationSeverity.WARNING,
                field="consistency",
                message="id and name fields should be the same",
                suggestion="Make id and name consistent to avoid confusion"
            ))

        return results

    def _validate_gui_manifest_specific(self, manifest_data: Dict[str, Any], manifest_path: Path) -> List[ManifestValidationResult]:
        """GUI manifest specific validation."""
        results = []
        
        # Validate entry section
        entry = manifest_data.get("entry")
        if not isinstance(entry, dict):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.GUI,
                severity=ManifestValidationSeverity.ERROR,
                field="entry",
                message="GUI entry must be a structured object",
            ))
            return results
        if not entry.get("id"):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.GUI,
                severity=ManifestValidationSeverity.ERROR,
                field="entry.id",
                message="Entry ID is required",
                suggestion="Add entry.id to identify the main entry point"
            ))

        if not entry.get("default") and not entry.get("entry_file"):
            results.append(ManifestValidationResult(
                manifest_type=ManifestType.GUI,
                severity=ManifestValidationSeverity.WARNING,
                field="entry.default",
                message="No default entry specified",
                suggestion="Add entry.default: true or specify entry_file"
            ))

        # Validate contributions
        contributions = manifest_data.get("contributions", {})
        for contribution_type, contribution_list in contributions.items():
            if not isinstance(contribution_list, list):
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.GUI,
                    severity=ManifestValidationSeverity.ERROR,
                    field=f"contributions.{contribution_type}",
                    message=f"Contributions must be a list, got {type(contribution_list)}",
                    suggestion="Fix contributions structure to be an array of objects"
                ))
                continue

            for i, contribution in enumerate(contribution_list):
                if not isinstance(contribution, dict):
                    results.append(ManifestValidationResult(
                        manifest_type=ManifestType.GUI,
                        severity=ManifestValidationSeverity.ERROR,
                        field=f"contributions.{contribution_type}[{i}]",
                        message=f"Contribution must be an object, got {type(contribution)}",
                        suggestion="Fix contribution structure to be an object"
                    ))
                    continue

                # Validate required fields for different contribution types
                if contribution_type == "pages":
                    if not contribution.get("id"):
                        results.append(ManifestValidationResult(
                            manifest_type=ManifestType.GUI,
                            severity=ManifestValidationSeverity.ERROR,
                            field=f"contributions.{contribution_type}[{i}].id",
                            message="Page contribution requires id field",
                            suggestion="Add id field to page contribution"
                        ))
                    if not contribution.get("zone"):
                        results.append(ManifestValidationResult(
                            manifest_type=ManifestType.GUI,
                            severity=ManifestValidationSeverity.ERROR,
                            field=f"contributions.{contribution_type}[{i}].zone",
                            message="Page contribution requires zone field",
                            suggestion="Add zone field to specify where page should appear"
                        ))

                elif contribution_type == "menu":
                    if not contribution.get("placement"):
                        results.append(ManifestValidationResult(
                            manifest_type=ManifestType.GUI,
                            severity=ManifestValidationSeverity.ERROR,
                            field=f"contributions.{contribution_type}[{i}].placement",
                            message="Menu contribution requires placement field",
                            suggestion="Add placement field to specify menu location"
                        ))

        # Validate install section
        install = manifest_data.get("install", {})
        if install.get("frontend_installable"):
            if not install.get("copy_source_root"):
                results.append(ManifestValidationResult(
                    manifest_type=ManifestType.GUI,
                    severity=ManifestValidationSeverity.WARNING,
                    field="install.copy_source_root",
                    message="Plugin is frontend installable but copy_source_root is not specified",
                    suggestion="Add install.copy_source_root to specify source directory"
                ))

        return results

    def _get_suggestion_for_error(self, error: Dict[str, Any]) -> Optional[str]:
        """Get a suggestion for a validation error."""
        field = error.get("loc", [])[0] if error.get("loc") else "unknown"
        
        suggestions = {
            "id": "Use a unique identifier for the plugin",
            "name": "Use a descriptive name for the plugin",
            "version": "Use semantic versioning (e.g., 1.0.0)",
            "category": "Use one of: analytics, automation, communication, development, experimental, integration, productivity, security, plugins, sys_extensions, channels",
            "entrypoint": "Format as 'module:function_name'",
            "capabilities.provides_ui": "Set to true if plugin provides UI components",
            "ui.has_component": "Set to true if plugin has UI components",
            "ui.component_id": "Specify the component identifier for UI",
        }
        
        return suggestions.get(field, "Check the field value and format")

    def validate_plugin_manifests(self, category: str, plugin_name: str) -> Dict[ManifestType, List[ManifestValidationResult]]:
        """Validate both root and GUI manifests for a plugin."""
        results = {
            ManifestType.ROOT: [],
            ManifestType.GUI: []
        }

        # Validate root manifest
        root_manifest_path = self.extensions_root / category / plugin_name / "plugin_manifest.json"
        if root_manifest_path.exists():
            results[ManifestType.ROOT] = self.validate_root_manifest(root_manifest_path)

        # Validate GUI manifest if it exists
        gui_manifest_path = self.extensions_root / category / plugin_name / "manifest.json"
        if gui_manifest_path.exists():
            results[ManifestType.GUI] = self.validate_gui_manifest(gui_manifest_path)

        # Store results
        key = f"{category}.{plugin_name}"
        self.validation_results[key] = []
        for manifest_type, manifest_results in results.items():
            self.validation_results[key].extend([
                ManifestValidationResult(
                    manifest_type=manifest_type,
                    severity=result.severity,
                    field=result.field,
                    message=result.message,
                    suggestion=result.suggestion,
                    value=result.value
                )
                for result in manifest_results
            ])

        return results

    def get_validation_summary(self) -> Dict[str, Any]:
        """Get a summary of all validation results."""
        total_errors = sum(
            1 for results in self.validation_results.values() 
            for result in results 
            if result.severity == ManifestValidationSeverity.ERROR
        )
        
        total_warnings = sum(
            1 for results in self.validation_results.values() 
            for result in results 
            if result.severity == ManifestValidationSeverity.WARNING
        )
        
        total_infos = sum(
            1 for results in self.validation_results.values() 
            for result in results 
            if result.severity == ManifestValidationSeverity.INFO
        )

        return {
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "total_infos": total_infos,
            "validated_plugins": len(self.validation_results),
            "validation_results": self.validation_results
        }


# Global enforcer instance
_enforcer: Optional[ManifestStandardsEnforcer] = None


def get_enforcer() -> ManifestStandardsEnforcer:
    """Get the global manifest standards enforcer instance."""
    global _enforcer
    if _enforcer is None:
        _enforcer = ManifestStandardsEnforcer()
    return _enforcer


def validate_plugin_manifests(category: str, plugin_name: str) -> Dict[ManifestType, List[ManifestValidationResult]]:
    """Validate manifests for a plugin."""
    enforcer = get_enforcer()
    return enforcer.validate_plugin_manifests(category, plugin_name)


def get_manifest_validation_summary() -> Dict[str, Any]:
    """Get manifest validation summary."""
    enforcer = get_enforcer()
    return enforcer.get_validation_summary()
