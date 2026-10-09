"""Direct, governed resource intent contract."""
from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


def test_resource_question_uses_registered_tool_without_model_generation():
    for question in ("How much memory I got left?", "How much RAM do I have left?",
                     "What's the available VRAM?", "How much disk space available?"):
        result = resolve_capability_decision(question)
        assert result.intent == "system.resources"
        assert result.capability == "system.resources"
        assert result.handler == "system_resources"
        assert not result.allow_llm_only


def test_resource_intent_does_not_intercept_ai_context_or_generic_memory():
    for question in ("How much conversational memory can Karen remember?",
                     "How does human memory work?", "Where am I from?"):
        assert resolve_capability_decision(question).intent != "system.resources"


def test_resource_result_renders_measured_available_bytes():
    executor = DirectCapabilityExecutor()
    text = executor._render("system.resources", "How much memory I got left?", {
        "memory": {"available": True, "available_bytes": 4 * 1024 ** 3,
                   "total_bytes": 16 * 1024 ** 3}
    })
    assert text == "Available memory: 4.00 GiB of 16.00 GiB."


def test_resource_result_never_invents_missing_capacity():
    executor = DirectCapabilityExecutor()
    assert "could not be measured" in executor._render(
        "system.resources", "What's the available VRAM?",
        {"vram": {"available": False}}
    )
