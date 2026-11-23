"""KIS-SEC-04: adversarial unit proof for the canonical browser egress guard.

All requests are fake in-memory Playwright routes. No real browser or network
is needed for this contract test. Network-level DNS pinning and process
sandbox acceptance remain separate deployment proofs.
"""

import asyncio
from types import SimpleNamespace

import pytest

from ai_karen_engine.integrations.web.crawl4ai_integration import (
    Crawl4AIIntegration,
    Crawl4AISettings,
)


class Response:
    def __init__(self, status=200, headers=None, content=b"public content"):
        self.status = status
        self.headers = headers or {}
        self.content = content
        self.disposed = False

    async def body(self):
        return self.content

    async def dispose(self):
        self.disposed = True


class Route:
    def __init__(self, url, responses=(), navigation=True):
        self.request = SimpleNamespace(
            url=url, is_navigation_request=lambda: navigation
        )
        self.responses = list(responses)
        self.fetched = []
        self.fulfilled = []
        self.aborted = 0

    async def fetch(self, **kwargs):
        self.fetched.append(kwargs)
        assert kwargs["max_redirects"] == 0
        assert self.responses
        return self.responses.pop(0)

    async def fulfill(self, **kwargs):
        self.fulfilled.append(kwargs)

    async def abort(self):
        self.aborted += 1


def integration(*, allowed_urls=(), max_browser_requests=16, max_redirects=5,
                max_response_bytes=1024, respect_robots_txt=False):
    crawler = object.__new__(Crawl4AIIntegration)
    crawler.settings = Crawl4AISettings(
        respect_robots_txt=respect_robots_txt,
        max_browser_requests=max_browser_requests,
        max_redirects=max_redirects,
        max_response_bytes=max_response_bytes,
    )
    # Never resolve real DNS in tests; production uses _validate_url.
    crawler._validate_url = lambda url: (
        None if url in allowed_urls else
        {"failure_code": "private_network_blocked", "error": "denied"}
    )
    crawler.robots_policy = SimpleNamespace(is_allowed=None)
    return crawler


def budget():
    return {"count": 0, "lock": asyncio.Lock()}


@pytest.mark.asyncio
async def test_public_request_is_fetched_once_without_implicit_redirects():
    url = "https://public.example/page"
    crawler = integration(allowed_urls=[url])
    route = Route(url, [Response()])
    await crawler._guard_browser_request(route, budget())
    assert len(route.fetched) == 1
    assert route.fetched[0]["url"] == url
    assert route.fulfilled
    assert route.aborted == 0


@pytest.mark.asyncio
async def test_private_redirect_is_aborted_before_any_private_fetch():
    origin = "https://public.example/article"
    internal = "http://127.0.0.1:8888/admin"
    redirected = Response(302, {"location": internal}, b"")
    route = Route(origin, [redirected])
    crawler = integration(allowed_urls=[origin])
    await crawler._guard_browser_request(route, budget())
    assert [call["url"] for call in route.fetched] == [origin]
    assert route.fulfilled == []
    assert route.aborted == 1
    assert redirected.disposed is True


@pytest.mark.asyncio
async def test_multiple_public_redirects_are_each_validated_and_bounded():
    first = "https://public.example/first"
    second = "https://public.example/second"
    final = "https://public.example/final"
    crawler = integration(allowed_urls=[first, second, final])
    route = Route(first, [
        Response(302, {"location": "/second"}, b""),
        Response(307, {"location": final}, b""),
        Response(200, {}, b"final public content"),
    ])
    await crawler._guard_browser_request(route, budget())
    assert [call["url"] for call in route.fetched] == [first, second, final]
    assert route.aborted == 0
    assert len(route.fulfilled) == 1


@pytest.mark.asyncio
async def test_redirect_hop_limit_aborts_chain():
    first = "https://public.example/first"
    second = "https://public.example/second"
    crawler = integration(allowed_urls=[first, second], max_redirects=0)
    route = Route(first, [Response(302, {"location": second}, b"")])
    await crawler._guard_browser_request(route, budget())
    assert len(route.fetched) == 1
    assert route.fulfilled == []
    assert route.aborted == 1


@pytest.mark.asyncio
async def test_per_context_request_cap_prevents_more_network_fetches():
    url = "https://public.example/item"
    crawler = integration(allowed_urls=[url], max_browser_requests=1)
    usage = budget()
    initial = Route(url, [Response()])
    denied = Route(url, [Response()])
    await crawler._guard_browser_request(initial, usage)
    await crawler._guard_browser_request(denied, usage)
    assert len(initial.fetched) == 1
    assert denied.fetched == []
    assert denied.aborted == 1
    assert usage["count"] == 1


@pytest.mark.asyncio
async def test_response_byte_budget_prevents_content_release():
    url = "https://public.example/large"
    crawler = integration(allowed_urls=[url], max_response_bytes=16)
    response = Response(200, {}, b"!" * 17)
    route = Route(url, [response])
    await crawler._guard_browser_request(route, budget())
    assert route.aborted == 1
    assert route.fulfilled == []
    assert response.disposed


@pytest.mark.asyncio
async def test_robots_denied_on_redirect_before_fetch():
    first = "https://public.example/first"
    second = "https://public.example/blocked"
    crawler = integration(allowed_urls=[first, second], respect_robots_txt=True)

    async def is_allowed(url):
        return (url != second, "blocked")

    crawler.robots_policy.is_allowed = is_allowed
    route = Route(first, [Response(302, {"location": second}, b"")])
    await crawler._guard_browser_request(route, budget())
    assert [call["url"] for call in route.fetched] == [first]
    assert route.aborted == 1


def test_missing_browser_hook_fails_closed():
    crawler = integration()
    with pytest.raises(RuntimeError, match="egress hook"):
        crawler._install_browser_egress_hook(SimpleNamespace())


@pytest.mark.asyncio
async def test_hook_installs_route_before_navigation():
    url = "https://public.example/allow"
    crawler = integration(allowed_urls=[url])

    class Strategy:
        hook = None

        def set_hook(self, name, hook):
            assert name == "on_page_context_created"
            self.hook = hook

    class Context:
        installed = None

        async def route(self, pattern, handler):
            assert pattern == "**/*"
            self.installed = handler

    strategy = Strategy()
    crawler._install_browser_egress_hook(
        SimpleNamespace(crawler_strategy=strategy)
    )
    assert callable(strategy.hook)
    context = Context()
    page = object()
    assert await strategy.hook(page, context) is page
    assert callable(context.installed)
    route = Route(url, [Response()])
    await context.installed(route)
    assert route.fulfilled and not route.aborted


def test_credentials_in_browser_url_are_rejected_before_dns():
    crawler = Crawl4AIIntegration(resolve_dns_for_safety=True)
    refused = crawler._validate_url("https://user:password@public.example/page")
    assert refused["failure_code"] == "invalid_url"


def test_browser_config_disables_untrusted_page_scripts(monkeypatch):
    from ai_karen_engine.integrations.web import crawl4ai_integration as module

    class BrowserConfig:
        def __init__(self, **kwargs):
            self.options = kwargs

    monkeypatch.setattr(module, "BrowserConfig", BrowserConfig)
    crawler = Crawl4AIIntegration(resolve_dns_for_safety=False)
    assert crawler.browser_config.options["java_script_enabled"] is False
    assert crawler.browser_config.options["use_persistent_context"] is False
    assert crawler.browser_config.options["accept_downloads"] is False


def test_incompatible_sdk_browser_config_fails_closed(monkeypatch):
    from ai_karen_engine.integrations.web import crawl4ai_integration as module

    class OldBrowserConfig:
        def __init__(self, headless=True):
            self.headless = headless

    monkeypatch.setattr(module, "BrowserConfig", OldBrowserConfig)
    with pytest.raises(RuntimeError, match="secure browser settings"):
        Crawl4AIIntegration(resolve_dns_for_safety=False)
