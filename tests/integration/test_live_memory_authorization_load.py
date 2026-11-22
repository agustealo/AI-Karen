"""Opt-in real PostgreSQL memory authorization load evidence, never a synthetic benchmark."""
from __future__ import annotations

import asyncio
import json
import os
import platform
import time
import uuid
from datetime import timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.persistence.postgres.engine import get_postgres_engine
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.event_source import PostgresEventSource
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
)


def _percentile(values: list[float], percentile: int) -> float | None:
    """Nearest-rank percentile; never fabricate latency for empty samples."""
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, (len(ordered) * percentile + 99) // 100 - 1)
    return round(ordered[position], 3)


async def _measure(
    gate: PostgresEventSource,
    *,
    tenant: uuid.UUID,
    user: uuid.UUID,
    origin: dict[str, str],
    concurrency: int,
    samples: int,
    expected: bool,
) -> dict:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    failures: list[str] = []
    mismatches = 0
    start = time.perf_counter()

    async def call() -> tuple[float, bool | None, str | None]:
        async with semaphore:
            before = time.perf_counter()
            try:
                # Bound the complete canonical authorization transaction,
                # including pool acquisition, query, commit, and cleanup.
                async with asyncio.timeout(15):
                    observed = await gate.authorize_selected_records(
                        tenant_id=str(tenant), user_id=str(user),
                        origins=[origin],
                    )
                return (1000.0 * (time.perf_counter() - before), observed, None)
            except Exception as exc:
                return (1000.0 * (time.perf_counter() - before),
                        None, type(exc).__name__)

    # All tasks are owned by the TaskGroup. Database errors are recorded and
    # never silently treated as valid denials or discarded from sample counts.
    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(call()) for _ in range(samples)]
    for task in tasks:
        latency, actual, error = task.result()
        latencies.append(latency)
        if error is not None:
            failures.append(error)
        elif actual is not expected:
            mismatches += 1

    elapsed = time.perf_counter() - start
    return {
        "concurrency": concurrency,
        "attempted": samples,
        "successes": samples - len(failures) - mismatches,
        "errors": len(failures),
        "error_types": sorted(set(failures)),
        "authorization_mismatches": mismatches,
        "expected_authorized": expected,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
        "max_ms": round(max(latencies), 3) if latencies else None,
        "duration_ms": round(elapsed * 1000.0, 3),
        "throughput_requests_per_sec": (
            round(samples / elapsed, 3) if elapsed > 0 else None
        ),
    }


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1"
    or os.getenv("KAREN_MEMORY_AUTH_LOAD") != "1",
    reason="opt-in migrated PostgreSQL authorization performance evidence",
)
async def test_memory_authorization_load_report() -> None:
    """Measure live normal/revoked authorization at configured concurrencies."""
    levels = tuple(
        int(part.strip())
        for part in os.getenv("KAREN_MEMORY_AUTH_LOAD_LEVELS", "1,8,32,64").split(",")
    )
    if not levels or any(n <= 0 or n > 256 for n in levels):
        raise ValueError("Load concurrency levels must be between 1 and 256")
    per_level = int(os.getenv("KAREN_MEMORY_AUTH_LOAD_SAMPLES", "128"))
    if per_level < max(levels):
        raise ValueError("Sample count must be >= the highest concurrency")
    report_path = Path(
        os.getenv("KAREN_MEMORY_AUTH_LOAD_REPORT", "memory-auth-load-report.json")
    )
    if report_path.suffix.lower() != ".json":
        raise ValueError("Load evidence report must be a JSON file")

    tenant, user = uuid.uuid4(), uuid.uuid4()
    event_id, assertion_id, scope_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    consent_name = f"ci-load-{uuid.uuid4().hex}"
    gate = PostgresEventSource()
    engine = get_postgres_engine()
    results: list[dict] = []
    failure_type: str | None = None
    cleanup_failure_type: str | None = None
    try:
        async with asyncio.timeout(15):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=event_id, tenant_id=tenant, user_id=user,
                    event_type="memory_persisted", source_type="chat_user",
                    payload_hash=uuid.uuid4().hex, consent_state="granted",
                    payload={"content": "isolated load evidence", "vault": {
                        "consent_scope": consent_name,
                    }},
                ))
                await session.flush()
                session.add(MemoryAssertion(
                    assertion_id=assertion_id, event_id=event_id,
                    tenant_id=tenant, user_id=user,
                    content="isolated load evidence", consent_state="granted",
                ))
                session.add(ConsentScope(
                    scope_id=scope_id, tenant_id=tenant, user_id=user,
                    scope_name=consent_name, is_granted=True,
                ))
        async with asyncio.timeout(15):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                row = (await session.execute(select(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == assertion_id,
                ))).scalar_one()
                revision = row.updated_at
        if revision.tzinfo is None:
            revision = revision.replace(tzinfo=timezone.utc)
        origin = {
            "record_type": "memory_assertion",
            "record_id": str(assertion_id),
            "event_id": str(event_id),
            "record_updated_at": revision.astimezone(timezone.utc).isoformat(),
        }
        async with asyncio.timeout(15):
            async with asyncio.timeout(15):
                assert await gate.authorize_selected_records(
                    tenant_id=str(tenant), user_id=str(user), origins=[origin],
                ) is True
    
        # Warm-up is excluded from measured samples and explicitly reported.
        for _ in range(4):
            assert await gate.authorize_selected_records(
                tenant_id=str(tenant), user_id=str(user), origins=[origin],
            ) is True
        for concurrency in levels:
            results.append(await _measure(
                gate, tenant=tenant, user=user, origin=origin,
                concurrency=concurrency, samples=per_level, expected=True,
            ))
    
        async with asyncio.timeout(15):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                scope = (await session.execute(select(ConsentScope).where(
                    ConsentScope.scope_id == scope_id,
                ))).scalar_one()
                scope.is_granted = False
        async with asyncio.timeout(15):
            assert await gate.authorize_selected_records(
                tenant_id=str(tenant), user_id=str(user), origins=[origin],
            ) is False
        for concurrency in levels:
            results.append(await _measure(
                gate, tenant=tenant, user=user, origin=origin,
                concurrency=concurrency, samples=per_level, expected=False,
            ))
    
    except BaseException as exc:
        failure_type = type(exc).__name__
        raise
    finally:
        try:
            async with asyncio.timeout(15):
                async with async_transaction_scope(tenant_id=str(tenant)) as session:
                    await session.execute(delete(MemoryAssertion).where(
                        MemoryAssertion.assertion_id == assertion_id,
                    ))
                    await session.execute(delete(MemoryEvent).where(
                        MemoryEvent.event_id == event_id,
                    ))
                    await session.execute(delete(ConsentScope).where(
                        ConsentScope.scope_id == scope_id,
                    ))
        except BaseException as cleanup_exc:
            cleanup_failure_type = type(cleanup_exc).__name__
            if failure_type is None:
                raise
        finally:
            # Write the evidence on all exits, including a failed revocation,
            # incomplete batch, or failed fixture cleanup. Never log IDs or
            # database credentials in the report.
            report = {
                "schema_version": 1,
                "test": "canonical_postgres_memory_authorization",
                "source": "PostgresEventSource.authorize_selected_records",
                "status": (
                    "complete"
                    if failure_type is None and cleanup_failure_type is None
                    and len(results) == 2 * len(levels)
                    and all(row["errors"] == 0 and row["authorization_mismatches"] == 0 for row in results)
                    else "incomplete"
                ),
                "failure_type": failure_type,
                "cleanup_failure_type": cleanup_failure_type,
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "database_driver": engine.async_engine.dialect.name,
                "pool_status": engine.async_engine.pool.status(),
                "warmup_calls": 4,
                "sample_count_per_condition_and_level": per_level,
                "concurrency_levels": list(levels),
                "latency_method": "wall_clock_elapsed_per_call_including_pool_wait",
                "per_call_timeout_seconds": 15,
                "measurements": results,
                "limitations": [
                    "No provider generation, network delivery, or cancellation latency",
                    "No memory-free ChatRuntime stream baseline",
                    "No production-host resource, network, or database server telemetry",
                    "No release thresholds asserted from benchmark output",
                ],
            }
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )

    assert results
    assert all(row["attempted"] == per_level for row in results)
    assert all(row["errors"] == 0 and row["authorization_mismatches"] == 0
               for row in results), report_path.as_posix()
