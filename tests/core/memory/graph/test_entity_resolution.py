from ai_karen_engine.core.memory.graph.entity_resolution import extract_entity_cues


def test_extracts_named_entities_and_informative_tokens():
    cues = extract_entity_cues("Why did we choose Supabase for Michigan Home Innovation memory?")
    lowered = {cue.casefold() for cue in cues}
    assert "supabase" in lowered
    assert "michigan home innovation" in lowered
    assert "why" not in lowered


def test_quoted_phrase_is_prioritized():
    cues = extract_entity_cues('What happened with "Michigan Home Innovation" last time?', max_cues=3)
    assert cues[0] == "Michigan Home Innovation"


def test_cues_are_bounded_and_deduplicated():
    cues = extract_entity_cues("Supabase Supabase Postgres PostgreSQL Redis graph memory", max_cues=3)
    assert len(cues) <= 3
    assert len({cue.casefold() for cue in cues}) == len(cues)


def test_empty_query_returns_no_cues():
    assert extract_entity_cues("") == ()
