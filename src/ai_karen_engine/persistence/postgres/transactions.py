"""Transaction management for tenant-scoped PostgreSQL operations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ai_karen_engine.persistence.postgres import get_postgres_engine

logger = logging.getLogger(__name__)

# Canonical RLS setting used by the Supabase baseline policies.
_TENANT_SETTING = "app.current_tenant_id"
# Compatibility setting retained while older SQL/helpers are audited.
_LEGACY_TENANT_SETTING = "app.tenant_id"


@contextmanager
def transaction_scope(
    tenant_id: Optional[str] = None,
) -> Generator[Session, None, None]:
    """Provide a transactional scope with optional tenant RLS context."""
    engine = get_postgres_engine()
    session = engine.get_session()
    try:
        if tenant_id is not None:
            _apply_tenant_context_sync(session, tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def rollback_async_transaction(session: AsyncSession) -> None:
    """Complete rollback despite repeated cancellation, invalidating on failure."""
    rollback_task = asyncio.create_task(session.rollback())
    while not rollback_task.done():
        try:
            await asyncio.shield(rollback_task)
        except asyncio.CancelledError:
            if rollback_task.done():
                break
    try:
        await rollback_task
    except BaseException:
        invalidate_task = asyncio.create_task(session.invalidate())
        while not invalidate_task.done():
            try:
                await asyncio.shield(invalidate_task)
            except asyncio.CancelledError:
                if invalidate_task.done():
                    break
        await invalidate_task
        raise


@asynccontextmanager
async def async_transaction_scope(
    tenant_id: Optional[str] = None,
    *, user_id: Optional[str] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide tenant and authenticated-principal scoped async transaction."""
    engine = get_postgres_engine()
    async with engine.async_session_factory() as session:
        try:
            if user_id is not None and tenant_id is None:
                raise ValueError("tenant_id required when binding transaction principal")
            if tenant_id is not None:
                await _apply_tenant_context_async(session, tenant_id)
            if user_id is not None:
                try:
                    principal = str(uuid.UUID(str(user_id).strip()))
                except (AttributeError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "authenticated transaction principal must be a UUID"
                    ) from exc
                await session.execute(
                    text("SELECT set_config('app.current_user_id', :user, true)"),
                    {"user": principal},
                )
            yield session
            await session.commit()
        except BaseException:
            # Cancellation must not escape while a caller-owned transaction
            # remains active. SQLAlchemy's session context also closes it,
            # but explicit rollback keeps the transaction boundary reliable.
            await rollback_async_transaction(session)
            raise


def _apply_tenant_context_sync(session: Session, tenant_id: str) -> None:
    """Set canonical and compatibility tenant settings for RLS-aware SQL."""
    try:
        tenant = str(uuid.UUID(str(tenant_id).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("tenant_id must be a UUID") from exc
    session.execute(
        text("SELECT set_config(:setting, :tid, true)"),
        {"setting": _TENANT_SETTING, "tid": tenant},
    )
    session.execute(
        text("SELECT set_config(:setting, :tid, true)"),
        {"setting": _LEGACY_TENANT_SETTING, "tid": tenant},
    )


async def _apply_tenant_context_async(session: AsyncSession, tenant_id: str) -> None:
    """Set canonical and compatibility tenant settings for async RLS-aware SQL."""
    try:
        tenant = str(uuid.UUID(str(tenant_id).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("tenant_id must be a UUID") from exc
    await session.execute(
        text("SELECT set_config(:setting, :tid, true)"),
        {"setting": _TENANT_SETTING, "tid": tenant},
    )
    await session.execute(
        text("SELECT set_config(:setting, :tid, true)"),
        {"setting": _LEGACY_TENANT_SETTING, "tid": tenant},
    )


__all__ = [
    "transaction_scope",
    "async_transaction_scope",
    "rollback_async_transaction",
]
