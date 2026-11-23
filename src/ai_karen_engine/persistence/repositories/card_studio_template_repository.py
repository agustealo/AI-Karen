"""Canonical PostgreSQL repository for owner-scoped, inert Card Studio drafts.

This service owns persistence only. The caller must obtain authenticated
principal IDs and mutation admission from RuntimePolicy; drafts never grant
execution, action, source access, publication, or rich replay permissions.

No frontend or API mutation path is enabled by this source-only slice.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ai_karen_engine.core.runtime.presentation_contract import (
    validate_card_template_draft,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


_MAX_LIBRARY = 100
_MAX_REVISION = 9223372036854775805
_SELECT = """
    t.template_id, t.tenant_id, t.user_id, t.template_key,
    t.head_revision, t.lifecycle, r.definition
"""


class CardTemplateConflict(RuntimeError):
    """Mutation could not be authorized against current owner/revision state."""


class CardTemplateUnavailable(LookupError):
    """The requested template is not accessible to the authenticated owner."""


@dataclass(frozen=True, slots=True)
class SavedCardTemplate:
    template_id: str
    tenant_id: str
    user_id: str
    template_key: str
    revision: int
    lifecycle: str
    definition: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CardTemplateMutationReceipt:
    template_id: str
    revision: int
    operation: str
    idempotency_key: str
    request_digest: str


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Canonical UUID required")
    try:
        canonical = str(uuid.UUID(value))
    except (AttributeError, ValueError) as exc:
        raise ValueError("Canonical UUID required") from exc
    if value != canonical:
        raise ValueError("Canonical UUID required")
    return canonical


def _revision(value: int) -> int:
    if type(value) is not int or not 1 <= value <= _MAX_REVISION:
        raise ValueError("Valid template revision required")
    return value


def _draft(value: Any) -> dict[str, Any]:
    clean = validate_card_template_draft(value)
    if clean is None or clean["template_key"].startswith("system-"):
        raise ValueError("Invalid or reserved Card Studio draft")
    return clean


def _digest(operation: str, fields: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"operation": operation, "fields": fields},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _record(value: dict[str, Any], *, tenant: str, user: str) -> SavedCardTemplate:
    if str(value.get("tenant_id")) != tenant or str(value.get("user_id")) != user:
        raise CardTemplateUnavailable("Card template unavailable")
    definition = validate_card_template_draft(value.get("definition"))
    if definition is None or definition["template_key"] != value.get("template_key"):
        raise CardTemplateUnavailable("Card template unavailable")
    template_id = _uuid(str(value["template_id"]))
    revision = _revision(int(value["revision"]))
    lifecycle = value.get("lifecycle")
    if lifecycle not in ("draft", "archived"):
        raise CardTemplateUnavailable("Card template unavailable")
    return SavedCardTemplate(
        template_id=template_id, tenant_id=tenant, user_id=user,
        template_key=definition["template_key"], revision=revision,
        lifecycle=lifecycle, definition=definition,
    )


def _snapshot(record: SavedCardTemplate) -> dict[str, Any]:
    return {
        "template_id": record.template_id,
        "tenant_id": record.tenant_id,
        "user_id": record.user_id,
        "template_key": record.template_key,
        "revision": record.revision,
        "lifecycle": record.lifecycle,
        "definition": record.definition,
    }


async def _lock_idempotency(session: Any, *, tenant: str, user: str, key: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {"scope": f"card-studio-mutation:{tenant}:{user}:{key}"},
    )


async def _replay(
    session: Any, *, tenant: str, user: str, key: str,
    operation: str, digest: str,
) -> tuple[SavedCardTemplate, CardTemplateMutationReceipt] | None:
    row = (await session.execute(text("""
        SELECT operation, request_digest, template_id, committed_revision, result_snapshot
        FROM public.card_studio_template_mutation_receipts
        WHERE tenant_id = :tenant AND user_id = :user AND idempotency_key = :key
    """), {"tenant": tenant, "user": user, "key": key})).mappings().first()
    if row is None:
        return None
    if row["operation"] != operation or row["request_digest"] != digest:
        raise CardTemplateConflict("Idempotency key reused with different request")
    record = _record(row["result_snapshot"], tenant=tenant, user=user)
    if record.template_id != str(row["template_id"]) or record.revision != int(row["committed_revision"]):
        raise CardTemplateConflict("Committed template receipt inconsistent")
    return record, CardTemplateMutationReceipt(
        template_id=record.template_id, revision=record.revision,
        operation=operation, idempotency_key=key, request_digest=digest,
    )


async def _persist_receipt(
    session: Any, *, record: SavedCardTemplate, key: str,
    operation: str, digest: str,
) -> CardTemplateMutationReceipt:
    await session.execute(text("""
        INSERT INTO public.card_studio_template_mutation_receipts
            (tenant_id, user_id, idempotency_key, operation, request_digest,
             template_id, committed_revision, result_snapshot)
        VALUES (:tenant, :user, :key, :operation, :digest,
                :template, :revision, CAST(:snapshot AS jsonb))
    """), {
        "tenant": record.tenant_id, "user": record.user_id,
        "key": key, "operation": operation, "digest": digest,
        "template": record.template_id, "revision": record.revision,
        "snapshot": json.dumps(_snapshot(record), sort_keys=True, separators=(",", ":")),
    })
    return CardTemplateMutationReceipt(
        template_id=record.template_id, revision=record.revision,
        operation=operation, idempotency_key=key, request_digest=digest,
    )


class CardStudioTemplateRepository:
    """Owner-scoped durable drafts, with immutable revisions and mutation receipts.

    All principals MUST be supplied by the authenticated runtime, not from
    a template, chat model output, request body, or plugin-provided identity.
    """

    async def create_draft(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        draft: Any, idempotency_key: str,
    ) -> tuple[SavedCardTemplate, CardTemplateMutationReceipt]:
        tenant, user, key = (
            _uuid(authenticated_tenant_id),
            _uuid(authenticated_user_id),
            _uuid(idempotency_key),
        )
        definition = _draft(draft)
        digest = _digest("create", {"definition": definition})
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                # Capacity is serialized across this owner's concurrent creates.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": f"card-studio-owner:{tenant}:{user}"},
                )
                await _lock_idempotency(session, tenant=tenant, user=user, key=key)
                replayed = await _replay(
                    session, tenant=tenant, user=user, key=key,
                    operation="create", digest=digest,
                )
                if replayed is not None:
                    return replayed
                count = (await session.execute(text("""
                    SELECT count(*) FROM public.card_studio_templates
                    WHERE tenant_id=:tenant AND user_id=:user AND lifecycle='draft'
                """), {"tenant": tenant, "user": user})).scalar_one()
                if count >= _MAX_LIBRARY:
                    raise CardTemplateConflict("Card library capacity reached")
                template_id = str(uuid.uuid4())
                await session.execute(text("""
                    INSERT INTO public.card_studio_templates
                        (template_id, tenant_id, user_id, template_key, head_revision, lifecycle)
                    VALUES (:template, :tenant, :user, :template_key, 1, 'draft')
                """), {
                    "template": template_id, "tenant": tenant,
                    "user": user, "template_key": definition["template_key"],
                })
                await session.execute(text("""
                    INSERT INTO public.card_studio_template_revisions
                        (template_id, tenant_id, user_id, revision, definition)
                    VALUES (:template, :tenant, :user, 1, CAST(:definition AS jsonb))
                """), {
                    "template": template_id, "tenant": tenant, "user": user,
                    "definition": json.dumps(definition, sort_keys=True, separators=(",", ":")),
                })
                record = SavedCardTemplate(
                    template_id=template_id, tenant_id=tenant, user_id=user,
                    template_key=definition["template_key"], revision=1,
                    lifecycle="draft", definition=definition,
                )
                receipt = await _persist_receipt(
                    session, record=record, key=key, operation="create", digest=digest,
                )
                return record, receipt
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CardTemplateConflict("Card template key or request conflicts") from None
            raise

    async def revise_draft(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        template_id: str, expected_revision: int, draft: Any,
        idempotency_key: str,
    ) -> tuple[SavedCardTemplate, CardTemplateMutationReceipt]:
        tenant, user, target, key = (
            _uuid(authenticated_tenant_id), _uuid(authenticated_user_id),
            _uuid(template_id), _uuid(idempotency_key),
        )
        expected = _revision(expected_revision)
        definition = _draft(draft)
        digest = _digest("revise", {
            "template_id": target, "expected_revision": expected, "definition": definition,
        })
        async with async_transaction_scope(tenant, user_id=user) as session:
            await _lock_idempotency(session, tenant=tenant, user=user, key=key)
            replayed = await _replay(
                session, tenant=tenant, user=user, key=key,
                operation="revise", digest=digest,
            )
            if replayed is not None:
                return replayed
            row = (await session.execute(text("""
                UPDATE public.card_studio_templates
                   SET head_revision = head_revision + 1, updated_at = clock_timestamp()
                 WHERE template_id = :template AND tenant_id = :tenant
                   AND user_id = :user AND head_revision = :expected
                   AND template_key = :template_key AND lifecycle = 'draft'
                RETURNING template_id, tenant_id, user_id, template_key, head_revision
            """), {
                "template": target, "tenant": tenant, "user": user,
                "expected": expected, "template_key": definition["template_key"],
            })).mappings().first()
            if row is None:
                raise CardTemplateConflict("Card template revision or ownership conflict")
            new_revision = int(row["head_revision"])
            await session.execute(text("""
                INSERT INTO public.card_studio_template_revisions
                    (template_id, tenant_id, user_id, revision, definition)
                VALUES (:template, :tenant, :user, :revision, CAST(:definition AS jsonb))
            """), {
                "template": target, "tenant": tenant, "user": user,
                "revision": new_revision,
                "definition": json.dumps(definition, sort_keys=True, separators=(",", ":")),
            })
            record = SavedCardTemplate(
                template_id=target, tenant_id=tenant, user_id=user,
                template_key=definition["template_key"], revision=new_revision,
                lifecycle="draft", definition=definition,
            )
            receipt = await _persist_receipt(
                session, record=record, key=key, operation="revise", digest=digest,
            )
            return record, receipt

    async def archive_draft(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        template_id: str, expected_revision: int, idempotency_key: str,
    ) -> tuple[SavedCardTemplate, CardTemplateMutationReceipt]:
        tenant, user, target, key = (
            _uuid(authenticated_tenant_id), _uuid(authenticated_user_id),
            _uuid(template_id), _uuid(idempotency_key),
        )
        expected = _revision(expected_revision)
        digest = _digest("archive", {"template_id": target, "expected_revision": expected})
        async with async_transaction_scope(tenant, user_id=user) as session:
            await _lock_idempotency(session, tenant=tenant, user=user, key=key)
            replayed = await _replay(
                session, tenant=tenant, user=user, key=key,
                operation="archive", digest=digest,
            )
            if replayed is not None:
                return replayed
            saved = (await session.execute(text(f"""
                SELECT {_SELECT}
                FROM public.card_studio_templates t
                JOIN public.card_studio_template_revisions r
                  ON r.template_id=t.template_id AND r.revision=t.head_revision
                 AND r.tenant_id=t.tenant_id AND r.user_id=t.user_id
                WHERE t.template_id=:template AND t.tenant_id=:tenant
                  AND t.user_id=:user AND t.head_revision=:expected
                  AND t.lifecycle='draft'
            """), {
                "template": target, "tenant": tenant, "user": user, "expected": expected,
            })).mappings().first()
            if saved is None:
                raise CardTemplateConflict("Card template revision or ownership conflict")
            changed = (await session.execute(text("""
                UPDATE public.card_studio_templates
                SET lifecycle='archived', updated_at=clock_timestamp()
                WHERE template_id=:template AND tenant_id=:tenant AND user_id=:user
                  AND head_revision=:expected AND lifecycle='draft'
                RETURNING template_id
            """), {
                "template": target, "tenant": tenant, "user": user, "expected": expected,
            })).mappings().first()
            if changed is None:
                raise CardTemplateConflict("Card template revision or ownership conflict")
            active = _record({
                "template_id": saved["template_id"],
                "tenant_id": saved["tenant_id"],
                "user_id": saved["user_id"],
                "template_key": saved["template_key"],
                "revision": saved["head_revision"],
                "lifecycle": "archived",
                "definition": saved["definition"],
            }, tenant=tenant, user=user)
            receipt = await _persist_receipt(
                session, record=active, key=key, operation="archive", digest=digest,
            )
            return active, receipt

    async def list_owned(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        limit: int = 20, include_archived: bool = False,
    ) -> list[SavedCardTemplate]:
        tenant, user = _uuid(authenticated_tenant_id), _uuid(authenticated_user_id)
        if type(limit) is not int or not 1 <= limit <= 50 or type(include_archived) is not bool:
            raise ValueError("Invalid Card Studio list options")
        async with async_transaction_scope(tenant, user_id=user) as session:
            rows = (await session.execute(text(f"""
                SELECT {_SELECT}
                FROM public.card_studio_templates t
                JOIN public.card_studio_template_revisions r
                  ON r.template_id=t.template_id AND r.revision=t.head_revision
                 AND r.tenant_id=t.tenant_id AND r.user_id=t.user_id
                WHERE t.tenant_id=:tenant AND t.user_id=:user
                  AND (:include_archived OR t.lifecycle='draft')
                ORDER BY t.updated_at DESC, t.template_id DESC
                LIMIT :maximum
            """), {
                "tenant": tenant, "user": user,
                "include_archived": include_archived, "maximum": limit,
            })).mappings().all()
            return [
                _record({
                    **row, "revision": row["head_revision"],
                }, tenant=tenant, user=user)
                for row in rows
            ]

    async def read_owned(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        template_id: str, revision: int | None = None,
    ) -> SavedCardTemplate:
        tenant, user, target = (
            _uuid(authenticated_tenant_id), _uuid(authenticated_user_id),
            _uuid(template_id),
        )
        requested = _revision(revision) if revision is not None else None
        async with async_transaction_scope(tenant, user_id=user) as session:
            row = (await session.execute(text(f"""
                SELECT {_SELECT}, r.revision AS selected_revision
                FROM public.card_studio_templates t
                JOIN public.card_studio_template_revisions r
                  ON r.template_id=t.template_id AND r.tenant_id=t.tenant_id
                 AND r.user_id=t.user_id
                 AND r.revision=COALESCE(:requested, t.head_revision)
                WHERE t.template_id=:template AND t.tenant_id=:tenant
                  AND t.user_id=:user
            """), {
                "template": target, "tenant": tenant, "user": user,
                "requested": requested,
            })).mappings().first()
            if row is None:
                raise CardTemplateUnavailable("Card template unavailable")
            return _record({
                **row, "revision": row["selected_revision"],
            }, tenant=tenant, user=user)

    async def list_revisions(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str,
        template_id: str, limit: int = 20,
    ) -> list[SavedCardTemplate]:
        tenant, user, target = (
            _uuid(authenticated_tenant_id), _uuid(authenticated_user_id),
            _uuid(template_id),
        )
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("Invalid Card Studio history limit")
        async with async_transaction_scope(tenant, user_id=user) as session:
            rows = (await session.execute(text(f"""
                SELECT {_SELECT}, r.revision AS selected_revision
                FROM public.card_studio_templates t
                JOIN public.card_studio_template_revisions r
                  ON r.template_id=t.template_id AND r.tenant_id=t.tenant_id
                 AND r.user_id=t.user_id
                WHERE t.template_id=:template AND t.tenant_id=:tenant
                  AND t.user_id=:user
                ORDER BY r.revision DESC LIMIT :maximum
            """), {
                "template": target, "tenant": tenant, "user": user, "maximum": limit,
            })).mappings().all()
            return [
                _record({**row, "revision": row["selected_revision"]}, tenant=tenant, user=user)
                for row in rows
            ]
