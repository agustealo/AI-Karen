"""Transaction management for tenant-scoped PostgreSQL operations."""

from __future__ import annotations

import logging
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


@asynccontextmanager
async def async_transaction_scope(
    tenant_id: Optional[str] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async transactional scope with optional tenant RLS context."""
    engine = get_postgres_engine()
    async with engine.async_session_factory() as session:
        try:
            if tenant_id is not None:
                await _apply_tenant_context_async(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _apply_tenant_context_sync(session: Session, tenant_id: str) -> None:
    """Set canonical and compatibility tenant settings for RLS-aware SQL."""
    tenant = str(tenant_id).strip()
    if not tenant:
        raise ValueError("tenant_id is required when applying tenant context")
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
    tenant = str(tenant_id).strip()
    if not tenant:
        raise ValueError("tenant_id is required when applying tenant context")
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
]
