"""Domain diversity must not fabricate providers or drop scarce evidence."""

from ai_karen_engine.services.tooling.internet_capability_service import InternetCapabilityService


def test_unique_hosts_are_selected_before_repeating_wikipedia():
    urls = [
        "https://en.wikipedia.org/wiki/History_of_Jamaica",
        "https://en.wikipedia.org/wiki/Jamaica",
        "https://www.britannica.com/place/Jamaica",
        "https://jis.gov.jm/about-jamaica/",
    ]
    assert InternetCapabilityService._select_domain_diverse_urls(urls, 3) == [
        urls[0], urls[2], urls[3]
    ]


def test_only_one_available_host_still_fills_all_slots():
    urls = ["https://en.wikipedia.org/wiki/A", "https://en.wikipedia.org/wiki/B"]
    assert InternetCapabilityService._select_domain_diverse_urls(urls, 2) == urls


def test_limit_and_empty_input():
    assert InternetCapabilityService._select_domain_diverse_urls([], 5) == []
    assert InternetCapabilityService._select_domain_diverse_urls(["https://a.org/1", "https://b.org/2"], 1) == ["https://a.org/1"]
