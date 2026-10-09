"""Execution-path contract for governed memory-save receipts.

The model must not author a save acknowledgement and denied writes must not
reach persistence. This tests the runtime action, not just message formatting.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def test_receipt_execution_denies_write_without_invoking_persistence():
    runtime = ChatRuntime.__new__(ChatRuntime)
    calls = []

    async def persist(*args):
        calls.append(args)
        raise AssertionError("Unauthorized memory persistence invoked")

    runtime._persist_memory = persist
    meta = {}
    result = asyncio.run(
        runtime._execute_memory_write_receipt(
            object(),
            SimpleNamespace(memory_write_allowed=False),
            object(),
            meta,
        )
    )

    assert calls == []
    assert meta["memory_persistence_status"] == "denied_by_policy"
    assert "not authorized" in result
    assert "Saved" not in result


def test_receipt_execution_uses_single_governed_write_and_verified_count():
    runtime = ChatRuntime.__new__(ChatRuntime)
    calls = []
    request, plan = object(), object()

    async def persist(actual_request, text, meta, actual_plan):
        calls.append((actual_request, text, actual_plan))
        meta["memory_persistence_status"] = "persisted"
        return {"status": "completed", "persisted": 2}

    runtime._persist_memory = persist
    meta = {}
    result = asyncio.run(
        runtime._execute_memory_write_receipt(
            request,
            SimpleNamespace(memory_write_allowed=True),
            plan,
            meta,
        )
    )

    assert calls == [(request, "", plan)]
    assert result == "Saved 2 memory facts for future conversations."


def test_receipt_execution_never_reports_success_without_confirmed_storage():
    for status, receipt in (
        ("no_candidate", {"status": "completed", "persisted": 0}),
        ("failed", {"status": "failed", "persisted": 0}),
        ("failed", {"status": "completed", "persisted": 2}),
    ):
        runtime = ChatRuntime.__new__(ChatRuntime)
        calls = []

        async def persist(request, text, meta, plan):
            calls.append(text)
            meta["memory_persistence_status"] = status
            return receipt

        runtime._persist_memory = persist
        result = asyncio.run(
            runtime._execute_memory_write_receipt(
                object(),
                SimpleNamespace(memory_write_allowed=True),
                object(),
                {},
            )
        )

        assert calls == [""]
        assert "Saved" not in result
        assert "couldn't" in result
