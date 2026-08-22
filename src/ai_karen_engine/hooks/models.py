"""
Data models for the unified hook system.
"""
# mypy: ignore-errors

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class HookPriority(Enum):
    """Standard hook priorities."""

    HIGHEST = 10
    HIGH = 25
    NORMAL = 50
    LOW = 75
    LOWEST = 90


@dataclass
class HookRegistration:
    """Registration record for a hook."""

    id: str
    hook_type: str
    handler: Callable
    priority: int
    conditions: Dict[str, Any]
    source_type: str
    source_name: Optional[str] = None
    registered_at: datetime = field(default_factory=datetime.utcnow)
    enabled: bool = True
    trust_level: str = "observational"
    criticality: str = "best_effort"
    sequence: int = 0

    def __post_init__(self):
        """Validate hook registration data."""
        if not callable(self.handler):
            raise ValueError("Handler must be callable")
        if not isinstance(self.priority, int) or self.priority < 0:
            raise ValueError("Priority must be a non-negative integer")
        valid_trust = {"observational", "transformational", "side_effecting"}
        if self.trust_level not in valid_trust:
            raise ValueError(f"trust_level must be one of {valid_trust}")
        valid_criticality = {"best_effort", "important", "critical"}
        if self.criticality not in valid_criticality:
            raise ValueError(f"criticality must be one of {valid_criticality}")


@dataclass
class HookContext:
    """Context passed to hook handlers."""

    hook_type: str
    data: Dict[str, Any]
    user_context: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def get(self, key: str, default: Any = None) -> Any:
        """Get data value with fallback."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set data value."""
        self.data[key] = value


@dataclass
class HookResult:
    """Result from hook execution."""

    hook_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success_result(
        cls, hook_id: str, result: Any, execution_time_ms: float = 0.0
    ) -> HookResult:
        """Create a successful hook result."""
        return cls(
            hook_id=hook_id,
            success=True,
            result=result,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def error_result(
        cls, hook_id: str, error: str, execution_time_ms: float = 0.0
    ) -> HookResult:
        """Create an error hook result."""
        return cls(
            hook_id=hook_id,
            success=False,
            error=error,
            execution_time_ms=execution_time_ms,
        )


@dataclass
class HookExecutionSummary:
    """Summary of hook execution batch."""

    hook_type: str
    total_hooks: int
    successful_hooks: int
    failed_hooks: int
    total_execution_time_ms: float
    results: List[HookResult]

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_hooks == 0:
            return 0.0
        return (self.successful_hooks / self.total_hooks) * 100.0
