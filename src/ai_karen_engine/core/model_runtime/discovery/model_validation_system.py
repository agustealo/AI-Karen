from __future__ import annotations

"""Compatibility wrapper for the retired validation system."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.model_runtime.model_validation import (
    ModelValidationResult,
    validate_model_record,
)
from ai_karen_engine.core.model_runtime.discovery.model_discovery_engine import (
    ModelInfo,
    ModelStatus,
    ModelType,
    ResourceRequirements,
)


class ValidationLevel(Enum):
    BASIC = "basic"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"
    PERFORMANCE = "performance"


class ValidationResult(Enum):
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"
    UNKNOWN = "unknown"


@dataclass
class ValidationIssue:
    severity: str
    category: str
    message: str
    suggestion: Optional[str] = None
    technical_details: Optional[str] = None


@dataclass
class ValidationReport:
    model_id: str
    model_path: str
    validation_level: ValidationLevel
    overall_result: ValidationResult
    status: ModelStatus
    issues: List[ValidationIssue]
    performance_metrics: Optional[Dict[str, Any]] = None
    compatibility_info: Optional[Dict[str, Any]] = None
    validation_time: float = 0.0
    timestamp: float = 0.0


class ModelValidationSystem:
    """Legacy-compatible validation adapter."""

    def __init__(self, cache_dir: str = "models/.validation_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.validation_cache: Dict[str, ValidationReport] = {}

    def validate_model(self, model_info: ModelInfo, level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationReport:
        validation = self.validate_model_metadata(
            {
                "model_id": model_info.id,
                "model_format": model_info.type.value,
                "tokenizer_present": True,
                "weights_present": True,
                "adapter_only": False,
                "security_flags": [],
            },
            level=level,
        )
        return ValidationReport(
            model_id=model_info.id,
            model_path=model_info.path,
            validation_level=level,
            overall_result=ValidationResult.VALID if validation.valid else ValidationResult.INVALID,
            status=model_info.status,
            issues=[
                ValidationIssue(
                    severity="warning" if warning else "error",
                    category="compatibility",
                    message=warning,
                )
                for warning in validation.warnings
            ],
            compatibility_info={
                "security_flags": list(validation.security_flags),
                "errors": list(validation.errors),
            },
        )

    def validate_model_metadata(
        self,
        record: Dict[str, Any],
        level: ValidationLevel = ValidationLevel.STANDARD,
    ) -> ModelValidationResult:
        return validate_model_record(record, {})

    def validate_model_path(self, model_path: str, level: ValidationLevel = ValidationLevel.BASIC) -> ValidationReport:
        path = Path(model_path)
        record = {
            "model_id": path.name,
            "model_format": "gguf" if path.suffix.lower() == ".gguf" else "transformers",
            "tokenizer_present": True,
            "weights_present": path.exists(),
            "adapter_only": False,
            "security_flags": [],
        }
        result = validate_model_record(record, {})
        return ValidationReport(
            model_id=path.name,
            model_path=model_path,
            validation_level=level,
            overall_result=ValidationResult.VALID if result.valid else ValidationResult.INVALID,
            status=ModelStatus.AVAILABLE if result.valid else ModelStatus.INCOMPATIBLE,
            issues=[
                ValidationIssue(
                    severity="warning" if warning else "error",
                    category="compatibility",
                    message=warning,
                )
                for warning in result.warnings
            ],
            compatibility_info={
                "security_flags": list(result.security_flags),
                "errors": list(result.errors),
            },
        )


def get_model_validation_system() -> ModelValidationSystem:
    return ModelValidationSystem()


__all__ = [
    "ModelValidationSystem",
    "ValidationIssue",
    "ValidationLevel",
    "ValidationReport",
    "ValidationResult",
    "get_model_validation_system",
]
