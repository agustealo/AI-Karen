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
