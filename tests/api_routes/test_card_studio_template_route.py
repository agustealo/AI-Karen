"""KGUI-CARD-STUDIO-01C: authenticated thin HTTP template CRUD contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ai_karen_engine.api_routes.chat import card_studio as api
from ai_karen_engine.api_routes.chat import runtime as ingress
from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.card_studio_template_service import (
    CardStudioMutation,
    CardStudioTemplateService,
)
from ai_karen_engine.persistence.repositories.card_studio_template_repository import (
    CardTemplateConflict,
    CardTemplateMutationReceipt,
    CardTemplateUnavailable,
    SavedCardTemplate,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
TEMPLATE = "55555555-5555-4555-8555-555555555555"
KEY = "99999999-9999-4999-8999-999999999999"


def definition():
    return {
        "schema_version": 1, "template_key": "personal-clock",
        "title": "Observed time", "layout": "stack",
        "density": "comfortable", "interaction_mode": "read_only",
        "slots": [{"slot_id": "main", "component_type": "time.observation"}],
    }


def committed():
    saved = SavedCardTemplate(
        template_id=TEMPLATE, tenant_id=TENANT, user_id=USER,
        template_key="personal-clock", revision=2, lifecycle="draft",
        definition=definition(),
    )
    receipt = CardTemplateMutationReceipt(
        template_id=TEMPLATE, revision=2, operation="revise",
        idempotency_key=KEY, request_digest="a" * 64,
    )
    return CardStudioMutation(template=saved, receipt=receipt)


def make_app(monkeypatch, *, principal=None, enabled=True):
    monkeypatch.setattr(
        api, "get_runtime_settings",
        lambda: SimpleNamespace(
            features=SimpleNamespace(enable_card_studio_crud=enabled)
        ),
    )
    app = FastAPI()
    app.include_router(ingress.router)
    if principal is None:
        principal = UserData(
            user_id=USER, tenant_id=TENANT,
            roles=["user"], permissions=[],
        )
    app.dependency_overrides[api.bypass_user_context_func] = lambda: principal
    return app


async def request(app, method, path, **kwargs):
    kwargs.setdefault("headers", {"Authorization": "Bearer ci-test-auth-bound-by-override"})
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_crud_feature_gate_denies_all_when_off(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch, enabled=False)
    response = await request(app, "POST", "/chat/card-studio/templates", json={
        "draft": definition(), "idempotency_key": KEY,
    })
    assert response.status_code == 404
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cookie_only_write_denied_before_runtime(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch)
    response = await request(
        app, "POST", "/chat/card-studio/templates",
        headers={},
        json={"draft": definition(), "idempotency_key": KEY},
    )
    assert response.status_code == 403
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_anonymous_or_incomplete_principal_cannot_call_runtime(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch, principal={})
    response = await request(app, "POST", "/chat/card-studio/templates", json={
        "draft": definition(), "idempotency_key": KEY,
    })
    assert response.status_code == 401
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_receipt_only_after_committed_runtime_result(monkeypatch):
    result = committed()
    execute = AsyncMock(return_value=result)
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch)
    response = await request(app, "POST", "/chat/card-studio/templates", json={
        "draft": definition(), "idempotency_key": KEY,
    })
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-correlation-id"]
    payload = response.json()
    assert payload["committed"] is True
    assert payload["receipt"]["revision"] == 2
    assert payload["receipt"]["idempotency_key"] == KEY
    assert payload["template"]["definition"] == definition()
    assert "user_id" not in str(payload)
    assert "tenant_id" not in str(payload)
    args = execute.await_args.kwargs
    assert args["operation"] == "create"
    assert args["idempotency_key"] == KEY
    assert args["context"].user_id == USER
    assert args["context"].tenant_id == TENANT
    assert args["context"].authenticated_user.user_id == USER


@pytest.mark.asyncio
async def test_revision_archive_history_and_read_delegate_without_owner_body(monkeypatch):
    backend = committed()
    write = AsyncMock(return_value=backend)
    read = AsyncMock(return_value=backend.template)
    history = AsyncMock(return_value=[backend.template])
    listed = AsyncMock(return_value=[backend.template])
    monkeypatch.setattr(CardStudioTemplateService, "mutate", write)
    monkeypatch.setattr(CardStudioTemplateService, "read_owned", read)
    monkeypatch.setattr(CardStudioTemplateService, "list_revisions", history)
    monkeypatch.setattr(CardStudioTemplateService, "list_owned", listed)
    app = make_app(monkeypatch)

    response = await request(app, "PUT", f"/chat/card-studio/templates/{TEMPLATE}", json={
        "draft": definition(), "expected_revision": 1, "idempotency_key": KEY,
    })
    assert response.status_code == 200, response.text
    assert write.await_args.kwargs["expected_revision"] == 1
    assert write.await_args.kwargs["operation"] == "revise"

    response = await request(
        app, "POST", f"/chat/card-studio/templates/{TEMPLATE}/archive", json={
            "expected_revision": 2, "idempotency_key": KEY,
        },
    )
    assert response.status_code == 200, response.text
    assert write.await_args.kwargs["operation"] == "archive"
    assert "draft" not in write.await_args.kwargs

    response = await request(
        app, "GET", "/chat/card-studio/templates?limit=10&include_archived=true",
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["templates"]) == 1
    assert listed.await_args.kwargs["include_archived"] is True

    response = await request(app, "GET", f"/chat/card-studio/templates/{TEMPLATE}")
    assert response.status_code == 200
    assert response.json()["template"]["template_id"] == TEMPLATE
    response = await request(
        app, "GET", f"/chat/card-studio/templates/{TEMPLATE}/revisions/2",
    )
    assert response.status_code == 200
    assert read.await_args.kwargs["revision"] == 2

    response = await request(
        app, "GET", f"/chat/card-studio/templates/{TEMPLATE}/revisions",
    )
    assert response.status_code == 200
    assert len(response.json()["revisions"]) == 1
    assert history.await_args.kwargs["template_id"] == TEMPLATE


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,expected", [
    (CardTemplateConflict("stale"), 409),
    (CardTemplateUnavailable("foreign"), 404),
    (PermissionError("denied"), 503),
    (ValueError("invalid"), 422),
    (RuntimeError("driver uncertain"), 503),
])
async def test_http_failures_never_fake_commit_and_hide_sensitive_exception(
    monkeypatch, exception, expected,
):
    execute = AsyncMock(side_effect=exception)
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch)
    response = await request(app, "POST", "/chat/card-studio/templates", json={
        "draft": definition(), "idempotency_key": KEY,
    })
    assert response.status_code == expected
    assert "committed" not in response.text
    assert str(exception) not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_readonly_policy_denied_before_store(monkeypatch):
    store = SimpleNamespace(
        list_owned=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        api, "CardStudioTemplateService",
        lambda: CardStudioTemplateService(repository=store),
    )
    app = make_app(monkeypatch, principal=UserData(
        user_id=USER, tenant_id=TENANT,
        roles=["readonly"], permissions=[],
    ))
    response = await request(app, "GET", "/chat/card-studio/templates")
    assert response.status_code == 403
    store.list_owned.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"draft": definition(), "idempotency_key": KEY, "tenant_id": TENANT},
    {"draft": definition(), "idempotency_key": KEY, "user_id": USER},
    {"draft": definition(), "idempotency_key": "not-a-uuid"},
])
async def test_untrusted_identity_fields_and_bad_keys_rejected_at_transport(
    monkeypatch, body,
):
    execute = AsyncMock()
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch)
    response = await request(app, "POST", "/chat/card-studio/templates", json=body)
    assert response.status_code == 422
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_publication_and_unbounded_revision_not_exposed(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(CardStudioTemplateService, "mutate", execute)
    app = make_app(monkeypatch)
    response = await request(
        app, "POST", "/chat/card-studio/templates/publish", json={
            "idempotency_key": KEY, "draft": definition(),
        },
    )
    # The GET-only template detail route exists, but publication has no POST.
    assert response.status_code == 405
    response = await request(
        app, "PUT", f"/chat/card-studio/templates/{TEMPLATE}", json={
            "idempotency_key": KEY, "expected_revision": 0, "draft": definition(),
        },
    )
    assert response.status_code == 422
    execute.assert_not_awaited()
