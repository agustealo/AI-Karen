from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_validator import ResponseValidator


def contract():
    return ResponseContract(
        purpose="tool_synthesis",
        requires_live_data=True,
        latest_user_message="History of Jamaica",
        tool_results=[{"sources": [{"url": "https://example.org/history"}]}],
    )


def test_grounded_url_passes():
    assert ResponseValidator().validate(
        "Jamaica became independent in 1962 (https://example.org/history).", contract()
    ).valid


def test_hallucinated_url_is_rejected():
    result = ResponseValidator().validate("See https://made-up.org/facts", contract())
    assert not result.valid
    assert result.reason == "unverified_citation_url"


def test_missing_citation_is_rejected_with_evidence():
    result = ResponseValidator().validate("Jamaica became independent in 1962.", contract())
    assert not result.valid
    assert result.reason == "missing_evidence_citation"


def test_normal_chat_not_affected():
    contract_without_evidence = ResponseContract(latest_user_message="Hi")
    assert ResponseValidator().validate("Hello there.", contract_without_evidence).valid


def test_no_authorized_sources_fails_closed():
    empty_evidence = ResponseContract(
        purpose="tool_synthesis",
        requires_live_data=True,
        latest_user_message="Jamaica history",
        tool_results=[{"sources": [], "results": []}],
    )
    result = ResponseValidator().validate("Jamaica became independent in 1962.", empty_evidence)
    assert not result.valid
    assert result.reason == "missing_authorized_source_evidence"


def test_discovery_only_link_cannot_authorize_citation():
    discovery = ResponseContract(
        purpose="tool_synthesis",
        requires_live_data=True,
        latest_user_message="History of Jamaica",
        tool_results=[{"sources": [{"url": "https://discovery.example/history", "evidence_level": "search_snippet"}]}],
    )
    result = ResponseValidator().validate("History: https://discovery.example/history", discovery)
    assert not result.valid
    assert result.reason == "missing_authorized_source_evidence"


def test_fetched_page_can_authorize_citation():
    fetched = ResponseContract(
        purpose="tool_synthesis",
        requires_live_data=True,
        latest_user_message="History of Jamaica",
        tool_results=[{"sources": [{"url": "https://verified.example/history", "evidence_level": "fetched_page"}]}],
    )
    assert ResponseValidator().validate("History: https://verified.example/history", fetched).valid
