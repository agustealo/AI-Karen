"""Transaction management for tenant-scoped PostgreSQL operations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator, Optional

from sqlalchemy import text
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ai_karen_engine.config.database import get_database_settings
from ai_karen_engine.persistence.postgres import get_postgres_engine

logger = logging.getLogger(__name__)

# Strong ownership of outstanding session retirement tasks. asyncio's event
# loop keeps only weak references to tasks; exceptions may be discarded by
# callers and must not own the lifetime of database cleanup.
_PENDING_SESSION_RETIREMENTS: set[asyncio.Task] = set()

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


class _RollbackStillActive(RuntimeError):
    """A rollback did not settle and still owns the SQLAlchemy session."""

    def __init__(self, task: asyncio.Task) -> None:
        super().__init__("postgres_rollback_unresponsive_connection_uncertain_quarantined")
        self.task = task
        self.retirement_task: asyncio.Task | None = None


class _InvalidationStillActive(_RollbackStillActive):
    """A pending invalidation retains exclusive ownership of its session."""

    def __init__(self, task: asyncio.Task) -> None:
        super().__init__(task)
        self.args = ("postgres_invalidate_unresponsive_connection_uncertain_quarantined",)


async def _bounded_transaction_cleanup(
    operation,
    *,
    seconds: float,
    label: str,
) -> None:
    """Bound the wait without concurrent operations on an active AsyncSession."""
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(operation)
    deadline = loop.time() + seconds
    while not task.done() and loop.time() < deadline:
        try:
            await asyncio.wait({task}, timeout=max(0.0, deadline - loop.time()))
        except asyncio.CancelledError:
            # The calling transaction re-raises cancellation after cleanup.
            continue
    if task.done():
        await task
        return

    task.cancel()
    grace_deadline = loop.time() + min(1.0, seconds)
    while not task.done() and loop.time() < grace_deadline:
        try:
            await asyncio.wait(
                {task}, timeout=max(0.0, grace_deadline - loop.time())
            )
        except asyncio.CancelledError:
            continue
    if task.done():
        try:
            await task
        except BaseException:
            pass
        raise TimeoutError(f"postgres_{label}_deadline_exceeded")
    if label == "rollback":
        raise _RollbackStillActive(task)
    if label == "invalidate":
        raise _InvalidationStillActive(task)

    # Unexpected cleanup operations must still have their result observed.
    task.add_done_callback(_observe_postgres_cleanup_task)
    logger.critical(
        "postgres.transaction_cleanup_unresponsive",
        extra={"operation": label, "deadline_seconds": seconds},
    )
    raise RuntimeError(f"postgres_{label}_unresponsive_connection_uncertain")


def _observe_postgres_cleanup_task(task: asyncio.Task) -> None:
    try:
        task.result()
    except BaseException:
        pass


def _finish_session_retirement(task: asyncio.Task) -> None:
    """Observe completion and release the canonical strong task reference."""
    try:
        _observe_postgres_cleanup_task(task)
    finally:
        _PENDING_SESSION_RETIREMENTS.discard(task)


async def _capture_rollback_connection(session: AsyncSession):
    """Inspect only a connection *already owned* by the SQLAlchemy session.

    Session.connection() is deliberately forbidden here: it may begin a new
    pool checkout if a cancelled acquisition left a logical transaction with
    no physical connection. An acquisition must never precede rollback.
    """
    if (
        not isinstance(session, AsyncSession)
        or not session.in_transaction()
        or not session.is_active
    ):
        return None

    transaction = session.sync_session.get_transaction()
    # SQLAlchemy 2.x stores already-joined Connection objects in the root
    # SessionTransaction. This is private state, isolated to this canonical
    # adapter so no transport operation or new checkout occurs on cleanup.
    owned = getattr(transaction, "_connections", None)
    if not owned:
        return None
    for binding in owned.values():
        connection = binding[0]
        try:
            return connection.connection
        except PendingRollbackError:
            # The physical driver was already invalidated. Roll back the
            # logical transaction without reconnecting or masking the error.
            logger.warning("postgres.rollback_connection_already_invalidated")
            return None
    return None


def _detach_pending_rollback_connection(pool_proxy) -> object | None:
    """Remove a still-checked-out connection from the reusable pool.

    Called only after the rollback deadline has elapsed, while that original
    rollback task remains its sole SQLAlchemy session owner. This operates
    on the pool proxy, without session.invalidate or transaction.close.
    """
    if pool_proxy is None:
        logger.critical("postgres.pending_rollback_without_pool_proxy")
        return None
    driver = pool_proxy.driver_connection
    pool_proxy.detach()
    logger.warning("postgres.pending_rollback_connection_detached")
    return driver


def _schedule_quarantined_session_retirement(
    session: AsyncSession,
    rollback_task: asyncio.Task,
    driver,
    *,
    invalidate_after_task: bool = True,
) -> asyncio.Task:
    """Keep the session owned until its active rollback ends, then close it."""

    if driver is not None and hasattr(driver, "terminate"):
        try:
            # asyncpg's terminate is synchronous and aborts driver I/O.
            driver.terminate()
        except Exception:
            logger.exception("postgres.quarantined_driver_termination_failed")

    async def retire() -> None:
        try:
            await rollback_task
        except BaseException:
            pass
        try:
            # Do not launch a second invalidation when the original
            # invalidation task has just completed. Close sequentially.
            if invalidate_after_task:
                await session.invalidate()
        except BaseException:
            logger.exception("postgres.quarantined_session_invalidation_failed")
        finally:
            try:
                await session.close()
            except BaseException:
                logger.exception("postgres.quarantined_session_close_failed")

    task = asyncio.create_task(retire())
    _PENDING_SESSION_RETIREMENTS.add(task)
    task.add_done_callback(_finish_session_retirement)
    return task


async def rollback_async_transaction(session: AsyncSession) -> None:
    """Quarantine a connection before rollback; never race session teardown."""
    settings = get_database_settings().pool
    pool_proxy = await _capture_rollback_connection(session)
    try:
        await _bounded_transaction_cleanup(
            session.rollback(),
            seconds=settings.rollback_timeout_seconds,
            label="rollback",
        )
    except _RollbackStillActive as pending:
        driver = None
        try:
            driver = _detach_pending_rollback_connection(pool_proxy)
        except BaseException:
            # Ownership must transfer even if the pool proxy is already
            # invalidated. Never close this AsyncSession while rollback runs.
            logger.exception("postgres.pending_rollback_detach_failed")
        pending.retirement_task = _schedule_quarantined_session_retirement(
            session, pending.task, driver
        )
        logger.critical(
            "postgres.rollback_pending_quarantined",
            extra={"pool_detach_confirmed": driver is not None},
        )
        raise
    except BaseException:
        try:
            await _bounded_transaction_cleanup(
                session.invalidate(),
                seconds=settings.invalidate_timeout_seconds,
                label="invalidate",
            )
        except _InvalidationStillActive as pending:
            # The original invalidation is still mutating this AsyncSession.
            # Transfer teardown ownership without starting a competing close
            # or invoking invalidate a second time.
            driver = None
            try:
                driver = _detach_pending_rollback_connection(pool_proxy)
            except BaseException:
                logger.exception("postgres.pending_invalidation_detach_failed")
            pending.retirement_task = _schedule_quarantined_session_retirement(
                session, pending.task, driver, invalidate_after_task=False
            )
            logger.critical(
                "postgres.invalidation_pending_quarantined",
                extra={"pool_detach_confirmed": driver is not None},
            )
            raise
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
    read_only_snapshot: bool = False,
) -> AsyncGenerator[AsyncSession, None]:
    """Provide tenant and authenticated-principal scoped async transaction.

    A quarantined session's asynchronous cleanup is owned by its original
    rollback task; this caller never races close against a pending rollback.
    """
    engine = get_postgres_engine()
    context_manager = engine.async_session_factory()
    session = await context_manager.__aenter__()
    close_in_caller = True
    try:
        try:
            if read_only_snapshot:
                if tenant_id is None or user_id is None:
                    raise ValueError("authenticated_snapshot_identity_required")
                # Must precede the first scope-setting SELECT, which can
                # establish the PostgreSQL MVCC snapshot.
                await session.execute(text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                ))
            if user_id is not None:
                await apply_authenticated_transaction_context(
                    session, tenant_id=tenant_id, user_id=user_id,
                )
            elif tenant_id is not None:
                await _apply_tenant_context_async(session, tenant_id)
            yield session
            await session.commit()
        except _RollbackStillActive:
            # Nested persistence owners may have already quarantined an
            # unresponsive rollback. Its retirement task owns the session;
            # a second rollback or close here would race that task.
            close_in_caller = False
            raise
        except BaseException:
            try:
                await rollback_async_transaction(session)
            except _RollbackStillActive:
                close_in_caller = False
                raise
            raise
    finally:
        if close_in_caller:
            await context_manager.__aexit__(None, None, None)


async def apply_authenticated_transaction_context(
    session: AsyncSession, *, tenant_id: Optional[str], user_id: str,
) -> None:
    """Apply validated identity to an owned transaction before protected SQL.

    The caller must have established authenticated runtime authority; this
    helper only installs transaction-local database scope, not a grant.
    """
    try:
        tenant = str(uuid.UUID(str(tenant_id).strip()))
        principal = str(uuid.UUID(str(user_id).strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("authenticated transaction tenant and principal must be UUIDs") from exc
    await _apply_tenant_context_async(session, tenant)
    await session.execute(
        text("SELECT set_config('app.current_user_id', :user, true)"),
        {"user": principal},
    )


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
    "apply_authenticated_transaction_context",
]
