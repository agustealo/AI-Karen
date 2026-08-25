from __future__ import annotations

from .capability_registry import CapabilityRegistry, get_capability_registry
from .capability_types import CapabilityDefinition, CapabilityId


DEFAULT_CAPABILITY_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        id=CapabilityId.CHAT_GENERATE,
        name="Chat Generation",
        description="Generate assistant chat responses.",
        allowed_execution_layers=("core", "provider", "extension"),
        required_inputs=("messages",),
        output_type="text",
    ),
    CapabilityDefinition(
        id=CapabilityId.TEXT_GENERATE,
        name="Text Generation",
        description="Generate free-form text.",
        allowed_execution_layers=("core", "provider", "extension"),
        required_inputs=("prompt",),
        output_type="text",
    ),
    CapabilityDefinition(
        id=CapabilityId.TEXT_EMBED,
        name="Text Embeddings",
        description="Create vector embeddings for text.",
        allowed_execution_layers=("core", "extension", "provider"),
        required_inputs=("text",),
        output_type="embedding",
    ),
    CapabilityDefinition(
        id=CapabilityId.TEXT_SUMMARIZE,
        name="Text Summarization",
        description="Summarize supplied text or documents.",
        allowed_execution_layers=("core", "provider", "extension"),
        required_inputs=("text",),
        output_type="text",
    ),
    CapabilityDefinition(
        id=CapabilityId.INTENT_CLASSIFY,
        name="Intent Classification",
        description="Classify user intent for routing and policy decisions.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("text",),
        output_type="classification",
    ),
    CapabilityDefinition(
        id=CapabilityId.MEMORY_SCORE,
        name="Memory Scoring",
        description="Score candidate memories for recall or persistence.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("candidate", "context"),
        output_type="score",
    ),
    CapabilityDefinition(
        id=CapabilityId.EVIDENCE_RERANK,
        name="Evidence Reranking",
        description="Rerank retrieved evidence for relevance and trust.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("query", "evidence"),
        output_type="ranked_evidence",
    ),
    CapabilityDefinition(
        id=CapabilityId.SAFETY_CLASSIFY,
        name="Safety Classification",
        description="Classify content for safety and policy routing.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("text",),
        output_type="classification",
    ),
    CapabilityDefinition(
        id=CapabilityId.VISION_ANALYZE,
        name="Vision Analysis",
        description="Analyze image or visual input.",
        allowed_execution_layers=("core", "provider", "extension"),
        required_inputs=("image",),
        output_type="vision_result",
    ),
    CapabilityDefinition(
        id=CapabilityId.SPEECH_TRANSCRIBE,
        name="Speech Transcription",
        description="Convert speech audio to text.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("audio",),
        output_type="text",
    ),
    CapabilityDefinition(
        id=CapabilityId.SPEECH_SYNTHESIZE,
        name="Speech Synthesis",
        description="Convert text to speech audio.",
        allowed_execution_layers=("core", "extension"),
        required_inputs=("text",),
        output_type="audio",
    ),
)


def register_default_capabilities(
    registry: CapabilityRegistry | None = None,
) -> CapabilityRegistry:
    target = registry or get_capability_registry()
    for capability in DEFAULT_CAPABILITY_DEFINITIONS:
        target.upsert(capability)
    return target