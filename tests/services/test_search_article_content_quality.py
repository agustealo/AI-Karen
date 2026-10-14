"""Search should return content-bearing passages, never page navigation as evidence."""

from ai_karen_engine.services.search.search_result_processor import SearchResultProcessor


WIKI_NAV = """
[Jump to content](https://en.wikipedia.org/wiki/History_of_Jamaica#bodyContent)

Main menu Main menu move to sidebar hide Navigation
* [Main page](https://en.wikipedia.org/wiki/Main_Page)
* [Contents](https://en.wikipedia.org/wiki/Wikipedia:Contents)
* [Current events](https://en.wikipedia.org/wiki/Portal:Current_events)

Personal tools
* [Donate](https://donate.wikimedia.org)
* [Create account](https://en.wikipedia.org/w/index.php?title=Special:CreateAccount)

Contents
* [Pre-Columbian Jamaica](https://en.wikipedia.org/wiki/History_of_Jamaica#Pre-Columbian_Jamaica)
* [Spanish period](https://en.wikipedia.org/wiki/History_of_Jamaica#Spanish_period)
"""

WIKI_ARTICLE = """
## History of Jamaica

The history of Jamaica includes the island's Indigenous Taíno communities, followed
by Spanish colonization starting in 1494 and British rule from 1655. Across the
colonial period, enslaved Africans were brought to the island and developed
communities that shaped Jamaican language and culture.

Jamaica gained independence from the United Kingdom on 6 August 1962.
The new nation retained parliamentary institutions while developing its
own cultural and political identity in the Caribbean region.
"""


def test_article_beats_navigation_and_preserves_relevant_facts():
    processor = SearchResultProcessor()
    result = processor.process(
        [{"url": "https://en.wikipedia.org/wiki/History_of_Jamaica",
          "markdown": WIKI_NAV + "\n\n" + WIKI_ARTICLE}],
        "Jamaican History",
    )
    assert result, "Substantive history paragraphs must survive"
    text = " ".join(item["content"] for item in result)
    assert "independence" in text.lower()
    assert "Main menu" not in text
    assert "Jump to content" not in text
    assert "https://en.wikipedia.org/wiki/Main_Page" not in text


def test_navigation_only_is_not_a_usable_search_result():
    processor = SearchResultProcessor()
    result = processor.process(
        [{"url": "https://en.wikipedia.org/wiki/History_of_Jamaica",
          "markdown": WIKI_NAV}],
        "Jamaican History",
    )
    assert result == []


def test_unrelated_article_is_not_presented_as_relevant_evidence():
    processor = SearchResultProcessor()
    result = processor.process(
        [{"url": "https://example.org/other",
          "markdown": "The mountain trail follows a forest road and crosses a small river. "
                      "The walking route is marked with signs and offers views of the valley."}],
        "Jamaican History",
    )
    assert result == []
