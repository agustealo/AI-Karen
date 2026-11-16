"""Opt-in real PostgreSQL status-admission latency evidence on the disposable channel test DB.

Runs AFTER test_channel_claim_concurrency_postgres.py sets up and tests the
checked-in migrations. This module never creates or migrates a live database,
and fails closed unless the database name is exactly karen_channel_test.

Samples are descriptive, not release latency SLOs or live Meta measurements.
"""
from __future__ import annotations

import json
import math
import os
import platform
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    ChannelDeliveryState,
    ChannelProviderStatusEvent,
)
from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository

SIZES: tuple[int, ...] = (1, 10, 25, 100)
OUTPUT = Path("artifacts/ci/channel-status-postgres-benchmark.json")


def percentile(samples: list[float], percentage: int) -> float:
    """Linear-interpolated sample percentile. Never invent missing observations."""
    if not samples or not 0 <= percentage <= 100:
        raise ValueError("Samples and percentile in 0..100 are required")
    ordered = sorted(samples)
    at = (len(ordered) - 1) * (percentage / 100)
    low, high = math.floor(at), math.ceil(at)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (at - low), 3)


def summary(samples: list[float]) -> dict[str, float | int]:
    """Include sample count so sparse p95/p99 cannot masquerade as an SLO."""
    return {
        "n": len(samples),
        "min_ms": round(min(samples), 3),
        "p50_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
        "p99_ms": percentile(samples, 99),
        "max_ms": round(max(samples), 3),
    }


def make_statuses(connection_id: str, *, case: str, count: int) -> tuple[ChannelProviderStatusEvent, ...]:
    """Create unique, valid normalized Meta-format test evidence, never raw secrets."""
    statuses = []
    for index in range(count):
        message_id = f"wamid.bench-{case}-{index}"
        statuses.append(ChannelProviderStatusEvent(
            connection_id=connection_id,
            provider_message_id=message_id,
            recipient_id="15551234567",
            state=ChannelDeliveryState.DELIVERED,
            provider_timestamp=1770000000,
            provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                provider_message_id=message_id,
                recipient_id="15551234567",
                state=ChannelDeliveryState.DELIVERED,
                provider_timestamp=1770000000,
            ),
        ))
    return tuple(statuses)


def disposable_postgres_dsn(url: str) -> str:
    """Admit only a loopback disposable database, never remote production."""
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"postgresql", "postgresql+asyncpg"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.path != "/karen_channel_test"
        or not parsed.username
        or not parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Refusing benchmark outside the local disposable channel database")
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def test_benchmark_refuses_nonlocal_or_ambiguous_database_scope() -> None:
    for url in (
        "postgresql://postgres:secret@db.example.com/karen_channel_test",
        "postgresql://postgres:secret@localhost/karen_production",
        "postgresql://postgres:secret@localhost/karen_channel_test?sslmode=disable",
        "postgresql://postgres@localhost/karen_channel_test",
    ):
        with pytest.raises(ValueError, match="local disposable"):
            disposable_postgres_dsn(url)
    assert disposable_postgres_dsn(
        "postgresql://postgres:secret@localhost:5432/karen_channel_test",
    ).endswith("/karen_channel_test")


def test_status_benchmark_percentiles_are_explicit_sample_statistics() -> None:
    assert percentile([1.0, 2.0, 3.0], 50) == 2.0
    assert percentile([1.0, 2.0, 3.0], 95) == 2.9
    assert summary([1.0, 2.0, 3.0])["n"] == 3
    with pytest.raises(ValueError):
        percentile([], 99)


@pytest.mark.asyncio
async def test_live_postgres_status_batch_latency_and_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.getenv("CHANNEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated CHANNEL_TEST_DATABASE_URL not configured")
    try:
        dsn = disposable_postgres_dsn(url)
    except ValueError as exc:
        pytest.fail(str(exc))
    try:
        repetitions = int(os.getenv("KAREN_CHANNEL_STATUS_BENCHMARK_REPETITIONS", "6"))
    except (ValueError, TypeError):
        pytest.fail("Benchmark repetitions must be an integer")
    if not 3 <= repetitions <= 100:
        pytest.fail("Benchmark repetitions must be between 3 and 100")

    raw = await asyncpg.connect(dsn)
    engine = None
    tenant = uuid.uuid4()
    connection_id = f"wa-bench-{uuid.uuid4().hex}"
    created_tenant = False

    try:
        if await raw.fetchval("SELECT current_database()") != "karen_channel_test":
            pytest.fail("Database identity does not match the disposable benchmark")
        if await raw.fetchval("SELECT to_regclass('public.channel_provider_status_events')") is None:
            pytest.fail("Run the canonical channel PostgreSQL integration proof before the benchmark")
        await raw.execute("INSERT INTO public.tenants (id) VALUES ($1)", tenant)
        created_tenant = True
        await raw.execute(
            """INSERT INTO public.channel_connections (
                   connection_id, tenant_id, installation_id, provider_account_id,
                   credential_handle, enabled, revision
               ) VALUES ($1, $2, 'whatsapp-cloud', '10987654321',
                         'vault://benchmark-disposable', true, 1)""",
            connection_id, tenant,
        )
        engine = create_async_engine(
            "postgresql+asyncpg://" + dsn.split("://", 1)[1],
            pool_size=4, max_overflow=0,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        counters = {"transactions": 0}

        @asynccontextmanager
        async def real_scope(tenant_id: str):
            counters["transactions"] += 1
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield session

        monkeypatch.setattr(module, "async_transaction_scope", real_scope)
        repo = SqlChannelRepository()
        connection = ChannelConnection(
            tenant_id=str(tenant), connection_id=connection_id,
            installation_id="whatsapp-cloud", provider_account_id="10987654321",
            credential_handle="vault://benchmark-disposable",
            enabled=True, revision=1,
        )

        async def invoke(mode: str, statuses: tuple[ChannelProviderStatusEvent, ...]) -> tuple[float, int]:
            before = counters["transactions"]
            started = time.perf_counter_ns()
            if mode == "single":
                for status in statuses:
                    assert await repo.record_provider_status(
                        connection=connection, status=status,
                    )
            else:
                assert mode == "batch"
                assert await repo.record_provider_status_batch(
                    connection=connection, statuses=statuses,
                ) == len(statuses)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            transactions = counters["transactions"] - before
            assert transactions == (len(statuses) if mode == "single" else 1)
            return elapsed_ms, transactions

        # Warm both methods before sampling; never contaminate measured calls.
        for mode in ("single", "batch"):
            await invoke(mode, make_statuses(
                connection_id, case=f"warm-{mode}-{uuid.uuid4().hex}", count=1,
            ))

        measurements: dict[tuple[str, int, str], list[float]] = defaultdict(list)
        transactions_observed: dict[tuple[str, int, str], list[int]] = defaultdict(list)
        persisted_count = 2
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""", tenant, connection_id,
        ) == persisted_count
        for size in SIZES:
            for trial in range(repetitions):
                # Alternate method order to reduce systematic cache/thermal drift.
                modes = ("single", "batch") if trial % 2 == 0 else ("batch", "single")
                for mode in modes:
                    statuses = make_statuses(
                        connection_id,
                        case=f"{mode}-{size}-{trial}-{uuid.uuid4().hex}", count=size,
                    )
                    elapsed, count = await invoke(mode, statuses)
                    measurements[(mode, size, "insert")].append(elapsed)
                    transactions_observed[(mode, size, "insert")].append(count)
                    persisted_count += size
                    assert await raw.fetchval(
                        """SELECT COUNT(*) FROM public.channel_provider_status_events
                           WHERE tenant_id=$1 AND connection_id=$2""",
                        tenant, connection_id,
                    ) == persisted_count

                    elapsed, count = await invoke(mode, statuses)
                    measurements[(mode, size, "replay")].append(elapsed)
                    transactions_observed[(mode, size, "replay")].append(count)
                    assert await raw.fetchval(
                        """SELECT COUNT(*) FROM public.channel_provider_status_events
                           WHERE tenant_id=$1 AND connection_id=$2""",
                        tenant, connection_id,
                    ) == persisted_count

        rows = []
        for mode in ("single", "batch"):
            for size in SIZES:
                for phase in ("insert", "replay"):
                    key = (mode, size, phase)
                    values = measurements[key]
                    tx = transactions_observed[key]
                    assert len(values) == repetitions
                    assert len(set(tx)) == 1
                    rows.append({
                        "mode": mode, "status_count": size, "phase": phase,
                        "transactions_per_sample": tx[0],
                        "latency_ms": summary(values),
                        "samples_ms": [round(value, 3) for value in values],
                    })
        evidence = {
            "schema": "ai-karen.channel-status-postgres-benchmark.v1",
            "source_sha": os.getenv("GITHUB_SHA", "local-unspecified"),
            "python_version": platform.python_version(),
            "postgres_version": await raw.fetchval("SHOW server_version"),
            "runner_os": os.getenv("RUNNER_OS", "unknown"),
            "pool_size": 4,
            "repetitions": repetitions,
            "percentiles_are_exploratory": repetitions < 100,
            "scope": "direct repository PostgreSQL commit/replay, no Meta network or runtime",
            "transaction_count_is_instrumented": True,
            "cases": rows,
        }
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        if engine is not None:
            await engine.dispose()
        if created_tenant:
            await raw.execute("DELETE FROM public.tenants WHERE id=$1", tenant)
        await raw.close()
