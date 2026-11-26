"""Test-only fixture setup for a freshly booted disposable production-image stack.

No public routes, direct INSERT/UPDATE of runtime rows, fabricated notifications,
external providers, or deployment credentials. A controlled repository failure
is not a full ChatRuntime/model failure; the browser proves subsequent behavior.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit


def require_disposable() -> str:
    expected = {
        "KAREN_SMOKE_COMMS_BROWSER_PROOF": "true",
        "ENVIRONMENT": "production",
        "AUTH_DEV_MODE": "false",
        "AUTH_ALLOW_DEV_LOGIN": "false",
        "KARI_AUTH_BYPASS": "false",
        "KARI_ENABLE_COMMUNICATIONS_TERMINAL_PRODUCER": "true",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise RuntimeError("Disposable fixture mode required")
    target = urlsplit(os.environ["DATABASE_URL"])
    host = target.hostname or ""
    if (
        not host.startswith("karen-beta-postgres-")
        or host != os.environ.get("POSTGRES_HOST")
        or target.port != 5432
        or target.path != "/karen_beta_smoke"
        or target.query
        or target.fragment
    ):
        raise RuntimeError("Refusing non-disposable database target")
    return host


def canonical_uuid(value: str) -> str:
    return str(uuid.UUID(value))


async def main() -> dict:
    host = require_disposable()
    from sqlalchemy import text
    from ai_karen_engine.config.runtime import get_runtime_settings
    from ai_karen_engine.persistence.postgres import get_postgres_engine
    from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
    from ai_karen_engine.persistence.repositories.chat_run_repository import SqlChatRunRepository
    from ai_karen_engine.persistence.repositories.communications_inbox_repository import CommunicationsInboxRepository
    from ai_karen_engine.services.auth.auth_service import AuthService, UserRole

    engine = get_postgres_engine()
    try:
        for url in (engine.engine.url, engine.async_engine.url):
            if url.host != host or url.database != "karen_beta_smoke" or url.port != 5432:
                raise RuntimeError("Resolved database differs from disposable target")
        async with engine.async_session_factory() as session:
            if (await session.execute(text("SELECT current_database()"))).scalar_one() != "karen_beta_smoke":
                raise RuntimeError("Unexpected database")
        if not get_runtime_settings().features.enable_communications_terminal_producer:
            raise RuntimeError("Fixture producer not enabled")
        data = json.loads(os.environ["KAREN_COMMS_FIXTURE_INPUT"])
        tenant = canonical_uuid(data["tenant_id"])
        if data["mode"] == "accounts":
            auth = AuthService()
            try:
                result = []
                for account in data["accounts"]:
                    email = account["email"]
                    if not email.startswith("kcomm-smoke-") or not email.endswith("@example.invalid"):
                        raise RuntimeError("Only disposable fixture identities allowed")
                    user, error = await auth.create_user(
                        email=email, password=account["password"], full_name="Communications smoke fixture",
                        tenant_id=tenant, roles=[UserRole.USER], is_verified=True,
                    )
                    if error or user is None or user.tenant_id != tenant or not user.is_verified:
                        raise RuntimeError("Verified fixture identity creation failed")
                    result.append(canonical_uuid(user.id))
                if len(result) != 2 or result[0] == result[1]:
                    raise RuntimeError("Two distinct fixture users required")
                return {"users": result}
            finally:
                await auth.stop()
        if data["mode"] != "runs":
            raise RuntimeError("Unknown fixture mode")
        repo = CommunicationsInboxRepository()
        ledger = SqlChatRunRepository()
        identities = data["identities"]
        if len(identities) != 2 or identities[0]["user_id"] == identities[1]["user_id"]:
            raise RuntimeError("Distinct fixture owners required")
        results = []
        for index, item in enumerate(identities):
            owner = canonical_uuid(item["user_id"])
            conversation = canonical_uuid(item["conversation_id"])
            scope = {"tenant_id": tenant, "user_id": owner}
            # Signed HTTP login and ensure-session created these conversations.
            # The fixture checks ownership again before exercising the ledger.
            async with async_transaction_scope(tenant, user_id=owner, read_only_snapshot=True) as session:
                exists = (await session.execute(text(
                    "SELECT count(*) FROM public.conversations "
                    "WHERE tenant_id=CAST(:tenant_id AS uuid) AND user_id=CAST(:user_id AS uuid) "
                    "AND conversation_id=CAST(:conversation AS uuid)"
                ), {**scope, "conversation": conversation})).scalar_one()
                if exists != 1:
                    raise RuntimeError("Fixture conversation ownership unavailable")
            if (await repo.list_entries(**scope)).entries:
                raise RuntimeError("Fixture inbox not empty")
            lease = await ledger.admit(
                **scope, conversation_id=conversation, transport_run_id=str(uuid.uuid4()),
                request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            )
            if lease is None:
                raise RuntimeError("Fixture runtime admission failed")
            if index == 0:
                # Fault injection exists only in this isolated process. The
                # source transaction commits; no production runtime is patched.
                with patch.object(CommunicationsInboxRepository, "reconcile_pending", side_effect=RuntimeError("disposable projection interruption")):
                    transitioned = await ledger.finish(lease, status="failed", error_code="SMOKE_CONTROLLED_FAILURE")
            else:
                transitioned = await ledger.finish(lease, status="failed", error_code="SMOKE_CONTROLLED_FAILURE")
            if not transitioned:
                raise RuntimeError("Fixture terminal transition failed")
            async with async_transaction_scope(tenant, user_id=owner, read_only_snapshot=True) as session:
                marked = (await session.execute(text(
                    "SELECT count(*) FROM public.runtime_chat_runs "
                    "WHERE execution_id=CAST(:execution AS uuid) AND tenant_id=CAST(:tenant_id AS uuid) "
                    "AND user_id=CAST(:user_id AS uuid) AND status='failed' "
                    "AND communications_attention_eligible_at=terminal_at "
                    "AND communications_attention_conversation_id=conversation_id"
                ), {**scope, "execution": lease.execution_id})).scalar_one()
                if marked != 1:
                    raise RuntimeError("No durable fixture eligibility")
            entries = (await repo.list_entries(**scope)).entries
            if index == 0 and entries:
                raise RuntimeError("Interrupted projection unexpectedly admitted")
            if index == 1 and (len(entries) != 1 or entries[0].execution_id != lease.execution_id):
                raise RuntimeError("Normal projection not verified")
            results.append(lease.execution_id)
        return {"executions": results}
    finally:
        await engine.cleanup()


if __name__ == "__main__":
    try:
        print("KCOMM_FIXTURE_RESULT=" + json.dumps(asyncio.run(main())))
    except Exception as exc:
        print("KCOMM_FIXTURE_FAILED=" + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
