"""Transaction management for tenant-scoped operations."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ai_karen_engine.persistence.postgres import get_postgres_engine

logger = logging.getLogger(__name__)


@contextmanager
def transaction_scope(
    tenant_id: Optional[str] = None,
) -> Generator[Session, None, None]:
    """Provide a transactional scope with optional tenant context.

    When ``tenant_id`` is provided, sets app.tenant_id for RLS policies.
    """
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
) -> AsyncGenerator[AsyncSession, None, None]:
    """Async transaction scope with optional tenant context."""
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
    """Set tenant context for row-level security policies (sync)."""
    try:
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
    except Exception as e:
        logger.debug("Could not set sync tenant context: %s", e)


async def _apply_tenant_context_async(session: AsyncSession, tenant_id: str) -> None:
    """Set tenant context for row-level security policies (async)."""
    try:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
    except Exception as e:
        logger.debug("Could not set async tenant context: %s", e)


__all__ = [
    "transaction_scope",
    "async_transaction_scope",
]
