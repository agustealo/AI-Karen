from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class CapabilityId(str, Enum):
    CHAT_GENERATE = "chat.generate"
    TEXT_GENERATE = "text.generate"
    TEXT_EMBED = "text.embed"
    TEXT_SUMMARIZE = "text.summarize"
    INTENT_CLASSIFY = "intent.classify"
    MEMORY_SCORE = "memory.score"
    EVIDENCE_RERANK = "evidence.rerank"
    SAFETY_CLASSIFY = "safety.classify"
    VISION_ANALYZE = "vision.analyze"
    SPEECH_TRANSCRIBE = "speech.transcribe"
    SPEECH_SYNTHESIZE = "speech.synthesize"


ExecutionLayer = Literal["core", "provider", "extension", "emergency"]


class CapabilityStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    id: CapabilityId
    name: str
    description: str
    status: CapabilityStatus = CapabilityStatus.ENABLED
    allowed_execution_layers: tuple[ExecutionLayer, ...] = ("core", "provider", "extension")
    required_permissions: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    output_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapabilityLookupResult:
    found: bool
    capability: CapabilityDefinition | None = None
    reason: str | None = None