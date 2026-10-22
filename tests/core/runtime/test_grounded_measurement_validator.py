"""Verified live measurements are evidence without a fetched webpage URL."""

from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_validator import ResponseValidator


def _contract(evidence):
    return ResponseContract(
        purpose="tool_synthesis",
        intent="search.weather",
        latest_user_message="What is the weather in NYC?",
        requires_live_data=True,
        allow_llm_only=False,
        tool_results=[evidence],
    )


def test_verified_measurement_does_not_require_fake_web_citation():
    contract = _contract({
        "evidence_level": "verified_measurement",
        "capability": "search.weather",
        "observation": {"location": "New York", "temperature_f": 54.3},
    })
    assert ResponseValidator().validate(
        "It's currently 54.3°F in New York.", contract
    ).valid


def test_unverified_observation_is_not_sufficient():
    contract = _contract({
        "capability": "search.weather",
        "observation": {"temperature_f": 54.3},
    })
    result = ResponseValidator().validate("It's 54.3°F.", contract)
    assert not result.valid
    assert result.reason == "missing_authorized_source_evidence"


def test_verified_measurements_do_not_authorize_invented_links():
    contract = _contract({
        "evidence_level": "verified_measurement",
        "capability": "time.current",
        "observation": {"timezone": "America/New_York", "value": "11:14 AM"},
    })
    result = ResponseValidator().validate(
        "It is 11:14 AM. https://example.org/imaginary", contract
    )
    assert not result.valid
    assert result.reason == "unverified_citation_url"
