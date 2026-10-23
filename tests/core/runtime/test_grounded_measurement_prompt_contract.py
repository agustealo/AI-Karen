"""Regression coverage for source-aware direct-capability prompt guidance."""

from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_prompt_builder import ResponsePromptBuilder


def _contract(tool_results):
    return ResponseContract(
        purpose="tool_synthesis",
        intent="search.weather",
        latest_user_message="What is the current weather?",
        requires_live_data=True,
        allow_llm_only=False,
        tool_results=tool_results,
    )


def test_verified_measurement_prompt_never_requires_invented_url():
    contract = _contract([
        {
            "evidence_level": "verified_measurement",
            "capability": "search.weather",
            "observation": {"temperature_f": 54.3, "location": "New York"},
        }
    ])
    system = ResponsePromptBuilder().build_messages(contract)[0]["content"]
    assert "only when the authorized evidence includes them" in system
    assert "never invent a URL" in system
    assert "Ground factual claims strictly" in system


def test_fetched_page_prompt_retains_source_integrity_instruction():
    contract = _contract([
        {"evidence_level": "fetched_page", "url": "https://example.org/weather"}
    ])
    system = ResponsePromptBuilder().build_messages(contract)[0]["content"]
    assert "Cite supporting source URLs" in system
    assert "Never invent a source URL" in system
    assert "untrusted data" in system
