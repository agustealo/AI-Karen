from ai_karen_engine.services.response.response_contracts import ResponseContract
from ai_karen_engine.services.response.response_validator import ResponseValidator


def contract():
    return ResponseContract(
        purpose="tool_synthesis",
        requires_live_data=True,
        latest_user_message="History of Jamaica",
        tool_results=[{"sources": [{"url": "https://example.org/history", "evidence_level": "fetched_page"}]}],
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


# Post-generation citation validation is exercised through ChatRuntime in
# tests/core/runtime/test_search_answer_runtime_synthesis.py. The retired
# ResponseSynthesizer must not regain a model retry path to satisfy a test.


def test_observation_rejects_unverified_urls():
    """Model-authored weather/time text cannot cite URLs from raw observations."""
    validator = ResponseValidator()
    cases = [
        ("search.weather", {"temperature_f": 75}, "It is 75 Fahrenheit. See https://made-up.example/weather."),
        ("search.weather", {"temperature_f": 75}, "It is 75 Fahrenheit (http://made-up.example/weather)."),
        ("search.weather", {"temperature_f": 75}, "It is 75 Fahrenheit. HTTPS://MADE-UP.EXAMPLE/weather"),
        ("time.current", {"timezone": "America/Detroit"}, "Time in America/Detroit: https://made-up.example/clock"),
    ]
    for intent, evidence, text in cases:
        result = validator.validate_observation(text, intent, evidence)
        assert not result.valid, (intent, text)
        assert result.reason == "unverified_observation_url"


def test_observation_without_url_remains_valid():
    """The citation restriction must not block supported plain observations."""
    validator = ResponseValidator()
    assert validator.validate_observation(
        "It is 75 Fahrenheit.", "search.weather", {"temperature_f": 75}
    ).valid
    assert validator.validate_observation(
        "The timezone is America/Detroit.", "time.current", {"timezone": "America/Detroit"}
    ).valid


def test_numbered_direct_deliverables_are_not_unrequested_menus():
    validator = ResponseValidator()
    response = ResponseContract(latest_user_message="Build a simple card game.")
    for answer in (
        "1. Shuffle the deck.\n2. Deal five cards.\n3. Take turns.",
        "## Implementation\n1. Create the game state.",
        "1) Introduction\n2) Methods\n3) Results",
    ):
        result = validator.validate(answer, response)
        assert result.valid, result.reason


def test_numbered_research_answer_still_requires_authorized_citations():
    validator = ResponseValidator()
    result = validator.validate(
        "1. Independence in 1962 (https://example.org/history).", contract()
    )
    assert result.valid, result.reason
    result = validator.validate("1. Independence in 1962.", contract())
    assert not result.valid
    assert result.reason == "missing_evidence_citation"


def test_explicit_unrequested_menu_remains_rejected():
    result = ResponseValidator().validate(
        "Which option would you like?",
        ResponseContract(latest_user_message="Choose a simple card game."),
    )
    assert not result.valid
    assert result.reason == "unrequested_menu"
