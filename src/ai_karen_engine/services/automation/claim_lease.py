"""Reusable heartbeat runner for durable work claims."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

_ResultT = TypeVar("_ResultT")


class ClaimLeaseLost(RuntimeError):
    """Durable work no longer owns the claim under which it started."""


async def run_with_claim_heartbeat(
    operation: Coroutine[Any, Any, _ResultT],
    *,
    renew: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float,
    lost_error: type[ClaimLeaseLost],
    lost_message: str,
) -> _ResultT:
    """Run an operation while renewing its claim and cancel on ownership loss."""
    if heartbeat_seconds <= 0:
        operation.close()
        raise ValueError("heartbeat_seconds must be positive")

    task = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if task in done:
                return await task

            if not await renew():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise lost_error(lost_message)
    except BaseException:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        raise


__all__ = ["ClaimLeaseLost", "run_with_claim_heartbeat"]
