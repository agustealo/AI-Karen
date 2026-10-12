"""Pure grounded identity synthesis tests; no LLM and no memory access."""
from ai_karen_engine.core.runtime.grounded_response_composer import compose_identity_summary


def test_matching_birthplace_and_origin_are_mentioned_once():
    text = compose_identity_summary({
        "preferred_name": "Zeus",
        "birthplace": "Jamaica",
        "origin_location": "jamaica",
        "upbringing_location": "New York City",
        "residence_location": "Detroit",
    })
    assert text.count("Jamaica") == 1
    assert "New York City" in text
    assert "Detroit" in text
    assert text.startswith("You're Zeus.")


def test_different_birthplace_and_origin_remain_distinct():
    text = compose_identity_summary({"birthplace": "Canada", "origin_location": "Jamaica"})
    assert "born in Canada" in text
    assert "from Jamaica" in text


def test_missing_attribute_is_not_inferred():
    text = compose_identity_summary({"origin_location": "Jamaica"})
    assert "from Jamaica" in text
    assert "born" not in text


def test_no_facts_returns_honest_unknown():
    assert "don't have enough verified information" in compose_identity_summary({})


def test_unrelated_personal_claims_are_never_inserted():
    text = compose_identity_summary({"preferred_name": "Zeus"})
    for unsupported in ("father", "mother", "children", "family", "born", "Jamaica"):
        assert unsupported not in text
