"""KGUI-CARD-STUDIO-01B: owned template drafts, CAS, receipts and SQL guards.

Fakes validate repository contracts; production release also requires observed
PostgreSQL/RLS execution and authenticated cross-tenant browser acceptance.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from ai_karen_engine.persistence.repositories import (
    card_studio_template_repository as module,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OWNER = "11111111-1111-1111-1111-111111111111"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
TEMPLATE = "55555555-5555-4555-8555-555555555555"
KEY = "99999999-9999-4999-8999-999999999999"


def draft(title="Current clock", key="personal-clock"):
    return {
        "schema_version": 1, "template_key": key,
        "title": title, "layout": "stack", "density": "comfortable",
        "interaction_mode": "read_only",
        "slots": [{"slot_id": "main", "component_type": "time.observation"}],
    }


def saved_row(*, revision=1, lifecycle="draft", template=TEMPLATE, tenant=TENANT, user=OWNER):
    return {
        "template_id": template, "tenant_id": tenant, "user_id": user,
        "template_key": "personal-clock", "head_revision": revision,
        "revision": revision, "selected_revision": revision,
        "lifecycle": lifecycle, "definition": draft(),
    }


class Result:
    def __init__(self, first=None, scalar=None, all_rows=None):
        self._first = first
        self._scalar = scalar
        self._rows = all_rows if all_rows is not None else []

    def mappings(self):
        return self

    def first(self):
        return self._first

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar


class FakeSession:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.statements = []
        self.params = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params)
        if not self.outputs:
            raise AssertionError("Unexpected SQL statement")
        return self.outputs.pop(0)


def patch_scope(monkeypatch, results):
    fake = FakeSession(results)
    scopes = []

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id):
        scopes.append((tenant_id, user_id))
        yield fake

    monkeypatch.setattr(module, "async_transaction_scope", transaction)
    return fake, scopes


@pytest.mark.asyncio
async def test_create_is_one_owner_scoped_receipted_transaction(monkeypatch):
    fake, scopes = patch_scope(monkeypatch, [Result() for _ in range(3)] + [
        Result(scalar=0), Result(), Result(), Result(),
    ])
    saved, receipt = await module.CardStudioTemplateRepository().create_draft(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        idempotency_key=KEY, draft=draft(),
    )
    assert scopes == [(TENANT, OWNER)]
    assert len(fake.statements) == 7
    assert saved.template_id == receipt.template_id
    assert saved.lifecycle == "draft"
    assert saved.revision == receipt.revision == 1
    assert receipt.operation == "create"
    assert receipt.idempotency_key == KEY
    assert "INSERT INTO public.card_studio_templates" in fake.statements[4]
    assert "INSERT INTO public.card_studio_template_revisions" in fake.statements[5]
    assert "INSERT INTO public.card_studio_template_mutation_receipts" in fake.statements[6]
    assert all(
        fake.params[index]["tenant"] == TENANT and fake.params[index]["user"] == OWNER
        for index in [2, 3, 4, 5, 6]
    )
    assert "CAST(:definition AS jsonb)" in fake.statements[5]
    assert "request_digest" not in fake.params[6]  # bound as digest, not copied from user payload


@pytest.mark.asyncio
async def test_idempotent_create_retry_reuses_committed_receipt_not_a_second_insert(monkeypatch):
    definition = draft()
    digest = module._digest("create", {"definition": definition})
    receipt_row = {
        "operation": "create", "request_digest": digest,
        "template_id": TEMPLATE, "committed_revision": 1,
        "result_snapshot": {
            "template_id": TEMPLATE, "tenant_id": TENANT, "user_id": OWNER,
            "template_key": "personal-clock", "revision": 1,
            "lifecycle": "draft", "definition": definition,
        },
    }
    fake, scopes = patch_scope(monkeypatch, [
        Result(), Result(), Result(first=receipt_row),
    ])
    saved, receipt = await module.CardStudioTemplateRepository().create_draft(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        idempotency_key=KEY, draft=definition,
    )
    assert saved.template_id == TEMPLATE
    assert receipt.request_digest == digest
    assert len(fake.statements) == 3
    assert scopes == [(TENANT, OWNER)]
    assert not any("INSERT INTO" in query for query in fake.statements)


@pytest.mark.asyncio
async def test_reusing_key_with_different_draft_fails_closed(monkeypatch):
    fake, _ = patch_scope(monkeypatch, [
        Result(), Result(), Result(first={
            "operation": "create", "request_digest": "f" * 64,
            "template_id": TEMPLATE, "committed_revision": 1,
            "result_snapshot": {},
        }),
    ])
    with pytest.raises(module.CardTemplateConflict, match="Idempotency"):
        await module.CardStudioTemplateRepository().create_draft(
            authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
            idempotency_key=KEY, draft=draft(),
        )
    assert len(fake.statements) == 3


@pytest.mark.asyncio
async def test_revision_cas_and_immutable_history_insert(monkeypatch):
    fake, scopes = patch_scope(monkeypatch, [
        Result(), Result(), Result(first={
            "template_id": TEMPLATE, "tenant_id": TENANT, "user_id": OWNER,
            "template_key": "personal-clock", "head_revision": 2,
        }), Result(), Result(),
    ])
    definition = draft(title="Updated clock")
    saved, receipt = await module.CardStudioTemplateRepository().revise_draft(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        template_id=TEMPLATE, expected_revision=1, draft=definition,
        idempotency_key=KEY,
    )
    assert scopes == [(TENANT, OWNER)]
    assert saved.revision == 2 and receipt.revision == 2
    assert saved.definition["title"] == "Updated clock"
    assert "head_revision = :expected" in fake.statements[2]
    assert "user_id = :user" in fake.statements[2]
    assert "lifecycle = 'draft'" in fake.statements[2]
    assert fake.params[2]["expected"] == 1
    assert fake.params[3]["revision"] == 2
    assert "INSERT INTO public.card_studio_template_mutation_receipts" in fake.statements[4]


@pytest.mark.asyncio
async def test_stale_or_foreign_revision_cannot_commit(monkeypatch):
    fake, scopes = patch_scope(monkeypatch, [
        Result(), Result(), Result(first=None),
    ])
    with pytest.raises(module.CardTemplateConflict, match="revision or ownership"):
        await module.CardStudioTemplateRepository().revise_draft(
            authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
            template_id=TEMPLATE, expected_revision=1, draft=draft(),
            idempotency_key=KEY,
        )
    assert scopes == [(TENANT, OWNER)]
    assert len(fake.statements) == 3


@pytest.mark.asyncio
async def test_archive_requires_cas_and_preserves_committed_definition(monkeypatch):
    fake, _ = patch_scope(monkeypatch, [
        Result(), Result(), Result(first=saved_row()),
        Result(first={"template_id": TEMPLATE}), Result(),
    ])
    saved, receipt = await module.CardStudioTemplateRepository().archive_draft(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        template_id=TEMPLATE, expected_revision=1,
        idempotency_key=KEY,
    )
    assert saved.lifecycle == "archived"
    assert saved.definition == draft()
    assert receipt.operation == "archive" and receipt.revision == 1
    assert "head_revision=:expected" in fake.statements[3]
    assert "lifecycle='draft'" in fake.statements[3]
    assert "DELETE FROM" not in "\n".join(fake.statements)


@pytest.mark.asyncio
async def test_owner_scoped_list_read_history_and_missing_are_non_enumerating(monkeypatch):
    repo = module.CardStudioTemplateRepository()
    fake, scopes = patch_scope(monkeypatch, [
        Result(all_rows=[saved_row()]),
        Result(first=saved_row()),
        Result(all_rows=[saved_row()]),
        Result(first=None),
    ])
    listed = await repo.list_owned(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
    )
    one = await repo.read_owned(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        template_id=TEMPLATE,
    )
    history = await repo.list_revisions(
        authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
        template_id=TEMPLATE,
    )
    with pytest.raises(module.CardTemplateUnavailable, match="unavailable"):
        await repo.read_owned(
            authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
            template_id=TEMPLATE, revision=44,
        )
    assert listed == history == [one]
    assert scopes == [(TENANT, OWNER)] * 4
    assert all("t.tenant_id=:tenant" in statement or "t.tenant_id = :tenant" in statement for statement in fake.statements)
    assert all("t.user_id=:user" in statement or "t.user_id = :user" in statement for statement in fake.statements)


@pytest.mark.parametrize("invalid", ["", OTHER.upper(), "not-a-uuid"])
def test_identity_validation_rejects_noncanonical_uuids(invalid):
    with pytest.raises(ValueError):
        module._uuid(invalid)


@pytest.mark.parametrize("rev", [-1, 0, 1.5, True, 9223372036854775806])
def test_invalid_expected_revision_is_rejected(rev):
    with pytest.raises(ValueError):
        module._revision(rev)


@pytest.mark.parametrize("key", ["system-time-observation", "system-planner-task-list"])
def test_system_templates_cannot_be_impersonated(key):
    with pytest.raises(ValueError, match="reserved"):
        module._draft(draft(key=key))


@pytest.mark.parametrize("limit", [0, 51, -1, True, 1.5])
@pytest.mark.asyncio
async def test_invalid_read_limit_never_opens_database(monkeypatch, limit):
    @asynccontextmanager
    async def forbidden(*args, **kwargs):
        raise AssertionError("Invalid input opened the database")
        yield

    monkeypatch.setattr(module, "async_transaction_scope", forbidden)
    with pytest.raises(ValueError, match="limit|options"):
        await module.CardStudioTemplateRepository().list_owned(
            authenticated_tenant_id=TENANT, authenticated_user_id=OWNER,
            limit=limit,
        )


def test_migration_has_immutable_owner_boundaries_and_no_client_access():
    path = Path("supabase/migrations/20261122235900_67_card_studio_template_drafts.sql")
    source = path.read_text()
    for required in (
        "CREATE TABLE public.card_studio_templates",
        "CREATE TABLE public.card_studio_template_revisions",
        "CREATE TABLE public.card_studio_template_mutation_receipts",
        "UNIQUE (tenant_id, user_id, template_key)",
        "FOREIGN KEY (template_id, tenant_id, user_id)",
        "ON DELETE CASCADE",
        "FORCE ROW LEVEL SECURITY",
        "app.current_tenant_id",
        "app.current_user_id",
        "REVOKE ALL ON public.card_studio_templates FROM PUBLIC",
        "REVOKE ALL ON public.card_studio_template_revisions FROM PUBLIC",
        "REVOKE ALL ON public.card_studio_template_mutation_receipts FROM PUBLIC",
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')",
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated')",
        "BEFORE DELETE ON public.card_studio_templates",
        "Card Studio templates require soft archive",
        "BEFORE UPDATE OR DELETE ON public.card_studio_template_revisions",
        "BEFORE UPDATE OR DELETE ON public.card_studio_template_mutation_receipts",
        "octet_length(definition::text) <= 4096",
        "template_key NOT LIKE 'system-%'",
    ):
        assert required in source
    assert "GRANT " not in source
    assert "INSERT INTO public.card_studio" not in source
    assert "model_name" not in source
    assert "code_artifact" not in source
