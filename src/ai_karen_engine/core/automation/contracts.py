"""Automation contracts and flow types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class FlowType(str, Enum):
    """Flow type classifications."""

    CHAT = "chat"
    DECIDE_ACTION = "decide_action"
    AUTOMATION = "automation"
    REASONING = "reasoning"


@dataclass
class FlowInput:
    """Input contract for workflow execution."""

    flow_type: FlowType = FlowType.CHAT
    user_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowOutput:
    """Output contract for workflow execution."""

    flow_type: FlowType = FlowType.CHAT
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class DecideActionInput:
    """Input contract for action decision."""

    action: str = ""
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecideActionOutput:
    """Output contract for action decision."""

    action: str = ""
    result: Any = None
    success: bool = True
    error: Optional[str] = None
