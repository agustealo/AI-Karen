"""Relevance ranker resists substring matches and repeated keyword stuffing."""

from ai_karen_engine.services.search.search_result_processor import SearchResultProcessor


def test_search_ranker_uses_whole_words_not_substrings():
    processor = SearchResultProcessor()
    assert processor._calculate_score("catalog category catalog", {"cat"}) == 0
    assert processor._calculate_score("A cat and another cat.", {"cat"}) == 2


def test_search_ranker_caps_keyword_stuffing():
    processor = SearchResultProcessor()
    assert processor._calculate_score("clock " * 100, {"clock"}) == 5


def test_search_ranker_keeps_heading_relevance_boost():
    processor = SearchResultProcessor()
    assert processor._calculate_score("# Clock and clock", {"clock"}) == 3.0


def test_search_ranker_preserves_result_shape_and_adds_score():
    processor = SearchResultProcessor()
    chunks = [{"content": "clock clock", "url": "https://example.com"}]
    ranked = processor._rank(chunks, "clock")
    assert ranked[0]["score"] == 2
