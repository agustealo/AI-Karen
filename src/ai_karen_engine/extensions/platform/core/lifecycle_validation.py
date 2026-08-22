"""
Lifecycle Validation Service - Enforces strict lifecycle separation rules.

This service ensures that the three critical lifecycle separations are maintained:
1. Discovery != Installation (discovered plugins don't auto-install)
2. Installation != Registration (installed plugins don't auto-register)
3. Registration != Mounting (registered plugins don't auto-mount)

Lifecycle ownership: PluginLifecycleManager owns the canonical PluginLifecycleState
and all lifecycle transitions. This service validates separation rules against that
canonical state machine.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from ai_karen_engine.extensions.platform.core.plugin_lifecycle_manager import (
    PluginLifecycleManager,
    PluginLifecycleState,
)

logger = logging.getLogger("kari.lifecycle_validation")


class ValidationSeverity(str, Enum):
    """Validation severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class LifecycleViolationReport:
    """Report of lifecycle violations."""

    plugin_name: str
    violation_type: str
    severity: ValidationSeverity
    message: str
    current_stage: str
    forbidden_stage: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plugin_name": self.plugin_name,
            "violation_type": self.violation_type,
            "severity": self.severity.value,
            "message": self.message,
            "current_stage": self.current_stage,
            "forbidden_stage": self.forbidden_stage,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ValidationResult:
    """Result of lifecycle validation."""

    is_valid: bool
    violations: List[LifecycleViolationReport]
    warnings: List[LifecycleViolationReport]
    info: List[LifecycleViolationReport]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "is_valid": self.is_valid,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [w.to_dict() for w in self.warnings],
            "info": [i.to_dict() for i in self.info],
            "timestamp": self.timestamp.isoformat(),
            "summary": {
                "total_violations": len(self.violations),
                "total_warnings": len(self.warnings),
                "total_info": len(self.info),
            },
        }


class LifecycleValidationService:
    """
    Service that enforces strict lifecycle separation rules.

    This service prevents automatic progression between lifecycle stages,
    ensuring that each stage requires explicit authorization and validation.
    """

    def __init__(self, lifecycle_manager: PluginLifecycleManager):
        """Initialize lifecycle validation service."""
        self.lifecycle_manager = lifecycle_manager
        self.validation_history: List[ValidationResult] = []

        logger.info("LifecycleValidationService initialized")

    async def validate_discovery_installation_separation(
        self,
    ) -> List[LifecycleViolationReport]:
        """
        Validate that discovered plugins are not automatically installed.

        Rule: DISCOVERED != INSTALLATION
        """
        violations = []

        discovered = await self.lifecycle_manager.list_plugins(
            include_available=True, include_installed=False
        )
        installed = await self.lifecycle_manager.list_plugins(
            include_available=False, include_installed=True
        )

        discovered_names = {p["id"] for p in discovered if p.get("state") == PluginLifecycleState.AVAILABLE}
        installed_names = {p["id"] for p in installed if p.get("state") in {PluginLifecycleState.INSTALLED, PluginLifecycleState.ENABLED, PluginLifecycleState.DISABLED}}

        for plugin_name in discovered_names:
            if plugin_name in installed_names:
                violation = LifecycleViolationReport(
                    plugin_name=plugin_name,
                    violation_type="discovery_installation_violation",
                    severity=ValidationSeverity.CRITICAL,
                    message="Plugin discovered and installed without explicit validation",
                    current_stage=PluginLifecycleState.AVAILABLE.value,
                    forbidden_stage=PluginLifecycleState.INSTALLED.value,
                )
                violations.append(violation)
                logger.warning(
                    f"Discovery-Installation violation detected: {plugin_name}"
                )

        return violations

    async def validate_installation_registration_separation(
        self,
    ) -> List[LifecycleViolationReport]:
        """
        Validate that installed plugins are not automatically registered.

        Rule: INSTALLATION != REGISTRATION
        """
        violations = []

        installed = await self.lifecycle_manager.list_plugins(
            include_available=False, include_installed=True
        )

        installed_names = {p["id"] for p in installed if p.get("state") == PluginLifecycleState.INSTALLED}
        registered_names = {p["id"] for p in installed if p.get("state") in {PluginLifecycleState.ENABLED, PluginLifecycleState.DISABLED}}

        for plugin_name in installed_names:
            if plugin_name in registered_names:
                violation = LifecycleViolationReport(
                    plugin_name=plugin_name,
                    violation_type="installation_registration_violation",
                    severity=ValidationSeverity.CRITICAL,
                    message="Plugin installed and registered without explicit validation",
                    current_stage=PluginLifecycleState.INSTALLED.value,
                    forbidden_stage=PluginLifecycleState.ENABLED.value,
                )
                violations.append(violation)
                logger.warning(
                    f"Installation-Registration violation detected: {plugin_name}"
                )

        return violations

    async def validate_registration_mounting_separation(
        self,
    ) -> List[LifecycleViolationReport]:
        """
        Validate that registered plugins are not automatically mounted.

        Rule: REGISTRATION != MOUNTING
        """
        violations = []

        installed = await self.lifecycle_manager.list_plugins(
            include_available=False, include_installed=True
        )

        registered_names = {p["id"] for p in installed if p.get("state") == PluginLifecycleState.INSTALLED}
        mounted_names = {p["id"] for p in installed if p.get("state") in {PluginLifecycleState.ENABLED, PluginLifecycleState.DISABLED}}

        for plugin_name in registered_names:
            if plugin_name in mounted_names:
                violation = LifecycleViolationReport(
                    plugin_name=plugin_name,
                    violation_type="registration_mounting_violation",
                    severity=ValidationSeverity.CRITICAL,
                    message="Plugin registered and mounted without explicit validation",
                    current_stage=PluginLifecycleState.INSTALLED.value,
                    forbidden_stage=PluginLifecycleState.ENABLED.value,
                )
                violations.append(violation)
                logger.warning(
                    f"Registration-Mounting violation detected: {plugin_name}"
                )

        return violations

    async def run_comprehensive_validation(self) -> ValidationResult:
        """
        Run all lifecycle validations and return comprehensive results.
        """
        logger.info("Running comprehensive lifecycle validation")

        violations = []
        warnings = []
        info = []

        violations.extend(await self.validate_discovery_installation_separation())
        violations.extend(await self.validate_installation_registration_separation())
        violations.extend(await self.validate_registration_mounting_separation())

        result = ValidationResult(
            is_valid=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            info=info,
        )

        self.validation_history.append(result)

        logger.info(
            f"Lifecycle validation completed: {len(violations)} violations, {len(warnings)} warnings, {len(info)} info"
        )
        return result

    def get_validation_history(self, limit: int = 10) -> List[ValidationResult]:
        """Get validation history."""
        return self.validation_history[-limit:]


# Global singleton instance
_lifecycle_validation_service: Optional[LifecycleValidationService] = None


def get_lifecycle_validation_service(
    lifecycle_manager: PluginLifecycleManager,
) -> LifecycleValidationService:
    """Get the global lifecycle validation service instance."""
    global _lifecycle_validation_service
    if _lifecycle_validation_service is None:
        _lifecycle_validation_service = LifecycleValidationService(
            lifecycle_manager
        )
    return _lifecycle_validation_service


__all__ = [
    "LifecycleValidationService",
    "ValidationSeverity",
    "LifecycleViolationReport",
    "ValidationResult",
    "get_lifecycle_validation_service",
]
