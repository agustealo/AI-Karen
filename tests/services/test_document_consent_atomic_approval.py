"""WS-04A9G: canonical approval repository single-transaction consume contract."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
)

pytestmark = pytest.mark.asyncio


class _Rows:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


def _args():
    return dict(
        approval_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        author_actor_id=str(uuid.uuid4()),
        fingerprint="a" * 64,
        action="issue",
        scope_record={"source_sha256": "a" * 64, "action": "issue"},
    )


@pytest.mark.parametrize("field,value", [
    ("approval_id", "forged"),
    ("tenant_id", "forged"),
    ("author_actor_id", "forged"),
    ("fingerprint", "not-a-digest"),
    ("fingerprint", "A" * 64),
    ("action", "publish"),
    ("action", "general_assist"),
])
async def test_invalid_approval_scope_denied_before_sql(field, value):
    session = SimpleNamespace(execute=AsyncMock())
    arguments = _args()
    arguments[field] = value
    assert await SqlApprovalRepository.consume_document_consent_in_session(
        session, **arguments,
    ) is None
    session.execute.assert_not_awaited()


async def test_approval_consumption_requires_author_actor_intent_and_exact_fingerprint():
    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows()))
    args = _args()
    assert await SqlApprovalRepository.consume_document_consent_in_session(
        session, **args,
    ) is None
    statement, params = session.execute.await_args.args
    sql = str(statement)
    for condition in (
        "status='approved'", "decided_by=CAST(:actor AS uuid)",
        "request_fingerprint=:fingerprint", "intent=:intent",
        "expires_at>clock_timestamp()", "RETURNING *",
        "SET status='consumed'", "request_payload='{}'::jsonb",
        "decision_reason='explicit_author_confirmation'",
        "NULLIF(policy_decision_id, '') IS NOT NULL",
        "CAST(:scope_record AS jsonb)", "risk_level='high'",
        "decided_at IS NOT NULL",
    ):
        assert condition in sql
    assert params["intent"] == "writing_style.document_consent.issue"
    assert params["fingerprint"] == args["fingerprint"]
    assert params["actor"] == args["author_actor_id"]
    assert params["scope_record"] is not None


async def test_approved_receipt_is_returned_only_from_database_row():
    args = _args()
    row = {
        "approval_id": uuid.UUID(args["approval_id"]),
        "tenant_id": uuid.UUID(args["tenant_id"]),
        "user_id": uuid.UUID(args["author_actor_id"]),
        "conversation_id": None,
        "request_fingerprint": args["fingerprint"],
        "policy_decision_id": "server-policy-id",
        "intent": "writing_style.document_consent.issue",
        "risk_level": "high",
        "reason_codes": [],
        "request_payload": {},
        "status": "consumed",
        "decision_reason": None,
        "decided_by": uuid.UUID(args["author_actor_id"]),
        "created_at": None,
        "expires_at": None,
        "decided_at": None,
        "consumed_at": None,
        "updated_at": None,
    }
    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows(row)))
    result = await SqlApprovalRepository.consume_document_consent_in_session(
        session, **args,
    )
    assert result is not None
    assert result["status"] == "consumed"
    assert result["approval_id"] == args["approval_id"]
