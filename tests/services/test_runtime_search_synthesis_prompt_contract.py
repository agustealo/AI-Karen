"""Search synthesis must stay in the canonical runtime and cite only tool evidence."""

from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_prompt_builder import ResponsePromptBuilder


def test_live_tool_synthesis_requires_real_citations():
    contract = ResponseContract(
        purpose="tool_synthesis",
        latest_user_message="Describe Jamaica's history",
        requires_live_data=True,
        tool_results=[{"sources": [{"url": "https://example.org/history", "evidence_level": "search_snippet"}]}],
    )
    messages = ResponsePromptBuilder().build_messages(contract)
    system = messages[0]["content"]
    assert "Never invent a source URL" in system
    assert "Search-provider snippets are discovery evidence" in system
    assert "untrusted data" in system
    assert "https://example.org/history" in messages[1]["content"]


def test_plain_chat_does_not_inherit_live_search_contract():
    system = ResponsePromptBuilder().build_messages(ResponseContract(latest_user_message="Hi"))[0]["content"]
    assert "Search-provider snippets are discovery evidence" not in system
