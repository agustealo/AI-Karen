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

from ai_karen_engine.config.database import get_database_settings
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


async def _bounded_transaction_cleanup(
    operation,
    *,
    seconds: float,
    label: str,
) -> None:
    """Drain an async SQLAlchemy cleanup operation within a finite budget.

    Repeated caller cancellations cannot bypass rollback safety. If the
    driver ignores its own cancellation, fail closed and report an uncertain
    session, rather than claim the connection was returned cleanly.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    task = asyncio.create_task(operation)
    while not task.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait({task}, timeout=remaining)
        except asyncio.CancelledError:
            # The original cancellation is re-raised by the transaction
            # owner once cleanup is complete or its deadline has expired.
            continue
    if task.done():
        await task
        return

    task.cancel()
    # A driver that supports cancellation should finish teardown promptly.
    grace_deadline = loop.time() + min(1.0, seconds)
    while not task.done() and loop.time() < grace_deadline:
        try:
            await asyncio.wait(
                {task}, timeout=max(0.0, grace_deadline - loop.time())
            )
        except asyncio.CancelledError:
            continue

    if task.done():
        # Consume cancellation/failure so the abandoned task cannot emit a
        # never-retrieved exception or be mistaken for clean rollback.
        try:
            await task
        except BaseException:
            pass
        raise TimeoutError(f"postgres_{label}_deadline_exceeded")

    def _observe_late_completion(completed: asyncio.Task) -> None:
        try:
            completed.result()
        except BaseException:
            pass

    task.add_done_callback(_observe_late_completion)
    logger.critical(
        "postgres.transaction_cleanup_unresponsive",
        extra={"operation": label, "deadline_seconds": seconds},
    )
    raise RuntimeError(f"postgres_{label}_unresponsive_connection_uncertain")


async def rollback_async_transaction(session: AsyncSession) -> None:
    """Rollback within configured deadlines; invalidate after uncertain outcome."""
    settings = get_database_settings().pool
    try:
        await _bounded_transaction_cleanup(
            session.rollback(),
            seconds=settings.rollback_timeout_seconds,
            label="rollback",
        )
    except BaseException:
        try:
            await _bounded_transaction_cleanup(
                session.invalidate(),
                seconds=settings.invalidate_timeout_seconds,
                label="invalidate",
            )
        except BaseException:
            logger.exception(
                "postgres.transaction_invalidation_failed",
                extra={"rollback_state": "uncertain"},
            )
            raise RuntimeError(
                "postgres_transaction_cleanup_failed_connection_uncertain"
            ) from None
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
            if user_id is not None:
                try:
                    tenant_id = str(uuid.UUID(str(tenant_id).strip()))
                except (AttributeError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "authenticated transaction tenant must be a UUID"
                    ) from exc
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
    "rollback_async_transaction",
]
