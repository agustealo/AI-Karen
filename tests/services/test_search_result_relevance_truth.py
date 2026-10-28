"""Regression proof for source and passage ranking truthfulness."""
from ai_karen_engine.services.search.search_result_processor import SearchResultProcessor
from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


def test_relevance_uses_query_coverage_not_saturated_keyword_counts():
    processor = SearchResultProcessor()
    query_terms = {"weather", "detroit"}
    relevant = "Detroit weather updates with forecast conditions for Detroit residents."
    irrelevant = ("Weather affects many things. " * 30)
    assert processor._calculate_score(relevant, query_terms) > processor._calculate_score(
        irrelevant, query_terms
    )


def test_relevance_scores_are_not_always_identical_after_five_repetitions():
    processor = SearchResultProcessor()
    terms = {"weather"}
    shorter = ("Weather matters. " * 6) + "Detailed atmospheric observations."
    longer = ("Weather matters. " * 45) + "Detailed atmospheric observations."
    assert processor._calculate_score(shorter, terms) != processor._calculate_score(longer, terms)


def test_source_builder_does_not_invent_positional_relevance():
    service = object.__new__(InternetCapabilityService)
    service.processor = SearchResultProcessor()
    source = {
        "url": "https://example.org/weather",
        "markdown": (
            "Weather observations provide conditions and recent forecasts "
            "for locations around the world. These observations are updated "
            "using instruments and weather monitoring stations."
        ),
        "metadata": {"title": "Weather observations"},
    }
    result = service._build_sources([source])
    assert len(result) == 1
    assert "relevanceScore" not in result[0]
