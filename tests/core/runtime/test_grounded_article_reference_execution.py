"""Executable synthesis-gate tests: scoped article access must precede model calls."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.services.database.repositories import repository_factory


class ArticleServiceDouble:
    def __init__(self, document):
        self.document = document
        self.calls = []

    async def read_for_chat(self, *, execution_context, article_id):
        self.calls.append((execution_context.user_id, execution_context.tenant_id, article_id))
        return self.document


class MeterDouble:
    def __init__(self, allow=False):
        self.allow = allow
        self.model_calls = 0

    async def consume_model_call(self):
        self.model_calls += 1
        return self.allow

    async def check_duration(self):
        return True


def request():
    return SimpleNamespace(
        context=SimpleNamespace(user_id="owner", tenant_id="tenant-a", correlation_id="test", request_id="req-test"),
        messages=[{"role": "user", "content": "What does this source establish?"}],
        preferred_provider=None, preferred_model=None, temperature=0.2,
    )


def retrieved(*, source="plugin", article_id="article-1"):
    return SimpleNamespace(
        success=True, source=source, source_id="intelligent-search",
        sources=[{
            "url": "https://example.org/article",
            "evidence_level": "fetched_page",
            "article_id": article_id,
            "content": "Untrusted inline fallback must not enter synthesis",
        }],
    )


@pytest.mark.asyncio
async def test_unauthorized_plugin_does_not_resolve_reference_or_call_model(monkeypatch):
    articles = ArticleServiceDouble("private document")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=[]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == []
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_missing_scoped_article_does_not_use_inline_fallback(monkeypatch):
    articles = ArticleServiceDouble(None)
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=["intelligent-search"]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == [("owner", "tenant-a", "article-1")]
    assert meter.model_calls == 0


@pytest.mark.asyncio
async def test_authorized_scoped_document_reaches_model_budget_gate(monkeypatch):
    articles = ArticleServiceDouble("Scoped verified document")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    meter = MeterDouble()
    result = await ChatRuntime._synthesize_search_evidence(
        object(), request(), SimpleNamespace(intent="search.general"),
        SimpleNamespace(allowed_plugins=["intelligent-search"]), meter, retrieved(),
    )
    assert result is None
    assert articles.calls == [("owner", "tenant-a", "article-1")]
    assert meter.model_calls == 1


@pytest.mark.asyncio
async def test_scoped_evidence_is_composed_via_gateway_with_model_receipt(monkeypatch):
    articles = ArticleServiceDouble("Verified scoped article evidence")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)
    captured = []

    class Gateway:
        async def generate(self, task):
            captured.append(task)
            return SimpleNamespace(
                text="The source establishes the result. https://example.org/article",
                provider="local-test", model="test-model", degraded=False,
                runtime_engine="local", engine_id="local", degradation_reason=None,
            )

    class RuntimeHarness:
        _composition = SimpleNamespace(expression_gateway=Gateway())

        def _resolve_chat_generation_max_tokens(self, request, plan):
            return 256

    plan = SimpleNamespace(
        allowed_plugins=["intelligent-search"], required_capabilities=[],
        forbidden_capabilities=[],
    )
    decision = SimpleNamespace(
        intent="search.general", required_capabilities=[],
        forbidden_capabilities=[], time_budget_ms=10000,
    )
    answer = await ChatRuntime._synthesize_search_evidence(
        RuntimeHarness(), request(), decision, plan,
        MeterDouble(allow=True), retrieved(),
    )
    assert answer is not None
    assert answer[0] == "The source establishes the result. https://example.org/article"
    assert answer[1]["actual_provider"] == "local-test"
    assert answer[1]["actual_model"] == "test-model"
    assert answer[1]["response_source"] == "grounded_search_model"
    assert len(captured) == 1
    prompt = str(captured[0].messages)
    assert "Verified scoped article evidence" in prompt
    assert "Untrusted inline fallback must not enter synthesis" not in prompt


@pytest.mark.asyncio
async def test_validation_rejection_does_not_emit_grounded_model_receipt(monkeypatch):
    from ai_karen_engine.services.response import response_validator

    articles = ArticleServiceDouble("Scoped trusted storage text")
    monkeypatch.setattr(repository_factory, "get_runtime_search_article_service", lambda: articles)

    class Gateway:
        async def generate(self, task):
            return SimpleNamespace(
                text="Unsupported conclusion", provider="local-test",
                model="test-model", degraded=False,
            )

    class RuntimeHarness:
        _composition = SimpleNamespace(expression_gateway=Gateway())

        def _resolve_chat_generation_max_tokens(self, request, plan):
            return 256

    monkeypatch.setattr(
        response_validator.ResponseValidator, "validate",
        lambda self, answer, contract: SimpleNamespace(
            valid=False, reason="unsupported_claim",
        ),
    )
    result = await ChatRuntime._synthesize_search_evidence(
        RuntimeHarness(), request(),
        SimpleNamespace(
            intent="search.general", required_capabilities=[],
            forbidden_capabilities=[], time_budget_ms=10000,
        ),
        SimpleNamespace(allowed_plugins=["intelligent-search"]),
        MeterDouble(allow=True), retrieved(),
    )
    assert result is None
    assert articles.calls == [("owner", "tenant-a", "article-1")]
