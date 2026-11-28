"""Disposable restore diagnostic: a valid older snapshot is not current consent.

The test uses real backup/restore commands and canonical NeuroVault, with
synthetic records in two generated databases. It intentionally demonstrates
the pre-reconciliation resurrection risk; it does not certify safe admission.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.core.memory.types import MemoryEntry, MemoryMetadata
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    Base, ConsentScope, MemoryAssertion, MemoryEvent, RetentionPolicy,
)
from ai_karen_engine.platform.memory.postgres.vault import (
    NeuroVaultAuthorizationError, PostgresNeuroVault,
)


@pytest.mark.asyncio
@pytest.mark.timeout(180)
@pytest.mark.skipif(
    os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1"
    or os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") != "1",
    reason="requires explicit disposable local PostgreSQL recovery environment",
)
async def test_live_backup_restore_rewinds_revocation_and_refuses_populated_target(tmp_path):
    base = make_url(os.environ["DATABASE_URL"])
    if (
        base.drivername != "postgresql" or base.host != "127.0.0.1"
        or base.database != "ai_karen" or base.username != "postgres"
        or base.query
    ):
        pytest.fail("recovery proof requires the isolated CI PostgreSQL service")

    suffix = uuid.uuid4().hex
    source_name = f"karen_recovery_src_{suffix}"
    target_name = f"karen_recovery_dst_{suffix}"
    source_url = base.set(database=source_name)
    target_url = base.set(database=target_name)
    root = Path(__file__).resolve().parents[2]
    admin = await asyncpg.connect(base.render_as_string(hide_password=False))
    engines = []
    created = []
    physical = os.getenv("KAREN_TEST_PHYSICAL_REPLAY") == "1"
    standby_dir = f"/tmp/karen-physical-replay-{suffix}"
    standby_port = 55432
    standby_url = source_url.set(port=standby_port)
    standby_started = False

    async def command(script, **overrides):
        env = {**os.environ, **overrides}
        return await asyncio.to_thread(
            subprocess.run, ["bash", str(root / "scripts/deploy" / script)],
            cwd=root, env=env, capture_output=True, text=True, timeout=40,
            check=False,
        )

    async def restore(url, archive):
        return await command(
            "database-restore.sh",
            RESTORE_DATABASE_URL=url.render_as_string(hide_password=False),
            BACKUP_FILE=str(archive),
            CONFIRM_RESTORE="I_UNDERSTAND_THIS_IS_DESTRUCTIVE",
        )

    async def docker_postgres(*args, check=True, timeout=45):
        if not physical or os.getenv("GITHUB_ACTIONS") != "true":
            pytest.fail("physical replay fixture requires isolated GitHub CI")
        container = f"ai-karen-postgres-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        result = await asyncio.to_thread(
            subprocess.run, ["docker", "exec", "-u", "postgres", container, *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    async def standby_sql(sql):
        binary = Path(os.environ["KAREN_POSTGRES_BIN_DIR"]) / "psql"
        result = await asyncio.to_thread(
            subprocess.run, [str(binary), "-X", "-qAt", "--set=ON_ERROR_STOP=1",
                             "--dbname", standby_url.render_as_string(hide_password=False),
                             "--command", sql],
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    async def await_standby(sql, expected):
        for _ in range(100):
            if await standby_sql(sql) == expected:
                return
            await asyncio.sleep(0.2)
        pytest.fail("physical standby did not reach required state")

    async def verify_replay(url, receipt_path, expected_digest):
        env = {
            **os.environ, "RECOVERY_DATABASE_URL": url.render_as_string(hide_password=False),
            "RECOVERY_CUTOFF_FILE": str(receipt_path),
            "RECOVERY_CUTOFF_SHA256": expected_digest,
        }
        return await asyncio.to_thread(
            subprocess.run, [os.sys.executable, str(root / "scripts/deploy/database-recovery-replay.py")],
            cwd=root, env=env, capture_output=True, text=True, timeout=40, check=False,
        )

    async def cutoff(url):
        result = await command(
            "database-recovery-cutoff.sh",
            DATABASE_URL=url.render_as_string(hide_password=False),
            CONFIRM_SOURCE_FENCED="I_HAVE_FENCED_SOURCE_WRITERS",
        )
        assert result.returncode == 0, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["schema_version"] == 1
        assert receipt["evidence_type"] == "postgres_physical_wal_cutoff"
        assert receipt["database_name"] == url.database
        assert int(receipt["system_identifier"]) > 0
        assert int(receipt["database_oid"]) > 0
        assert int(receipt["timeline_hex"], 16) > 0
        assert datetime.fromisoformat(receipt["captured_at"]).tzinfo is not None
        assert receipt["server_major"] == admin.get_server_version().major
        assert lsn(receipt["observed_flush_lsn"]) >= lsn(receipt["required_lsn"])
        return receipt

    def lsn(value):
        high, low = value.split("/")
        return (int(high, 16) << 32) + int(low, 16)

    try:
        for name in (source_name, target_name):
            await admin.execute(f'CREATE DATABASE "{name}"')
            created.append(name)
        for url in (source_url, target_url):
            engines.append(create_async_engine(url.set(drivername="postgresql+asyncpg")))
        source, target = engines
        async with source.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=[model.__table__ for model in (
                    MemoryEvent, MemoryAssertion, ConsentScope, RetentionPolicy,
                )],
            )
        source_sessions = async_sessionmaker(source, expire_on_commit=False)
        target_sessions = async_sessionmaker(target, expire_on_commit=False)
        live = PostgresNeuroVault(session_factory=source_sessions)
        recovered = PostgresNeuroVault(session_factory=target_sessions)
        tenant, user, scope_id = (uuid.uuid4() for _ in range(3))
        context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            policy_context={
                "memory_read_authorized": True,
                "memory_write_authorized": True,
                "memory_delete_authorized": True,
            },
        )

        def entry(scope):
            return MemoryEntry(
                id=str(uuid.uuid4()), content=f"synthetic recovery fixture {scope}",
                metadata=MemoryMetadata(
                    tenant_id=str(tenant), user_id=str(user), source="chat_user",
                    custom={"consent_scope": scope},
                ),
            )

        retired, revoked, unrelated = (entry(scope) for scope in (
            "retire-fixture", "revoke-fixture", "independent-fixture",
        ))
        async with source_sessions.begin() as session:
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name="revoke-fixture", is_granted=True,
            ))
        for item in (retired, revoked, unrelated):
            assert (await live.persist(item, context=context)).persisted
        ids = [item.id for item in (retired, revoked, unrelated)]
        assert {item.id for item in await live.export(ids, context=context)} == set(ids)

        missing_confirmation = await command(
            "database-recovery-cutoff.sh",
            DATABASE_URL=source_url.render_as_string(hide_password=False),
            CONFIRM_SOURCE_FENCED="",
        )
        assert missing_confirmation.returncode == 2
        before_cutoff = await cutoff(source_url)
        if physical:
            # Clone only the synthetic disposable CI cluster.
            await docker_postgres(
                "pg_basebackup", "-h", "/var/run/postgresql", "-p", "5432",
                "-U", "postgres", "-D", standby_dir, "-X", "stream",
                "-R", "-c", "fast", "-w",
            )
            standby_started = True
            await docker_postgres(
                "pg_ctl", "-D", standby_dir, "-l", standby_dir + "/standby.log",
                "-o", f"-p {standby_port} -h 127.0.0.1 -k {standby_dir}",
                "-w", "-t", "30", "start",
            )
            await await_standby(
                "SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming'", "1",
            )
            await standby_sql("SELECT pg_wal_replay_pause()")
            await await_standby("SELECT pg_get_wal_replay_pause_state()", "paused")
            assert await standby_sql(
                f"SELECT count(*) FROM memory_assertion WHERE assertion_id = '{retired.id}'"
            ) == "1"
        backup = await command(
            "database-backup.sh",
            DATABASE_URL=source_url.render_as_string(hide_password=False),
            KAREN_BACKUP_ROOT=str(tmp_path / "backups"),
        )
        assert backup.returncode == 0, backup.stderr
        archive = Path(backup.stdout.strip().splitlines()[-1]) / "ai-karen-postgres.dump"
        assert archive.is_file()

        wrong = tmp_path / "wrong.dump"
        wrong.write_bytes(b"not the selected archive")
        shutil.copyfile(str(archive) + ".sha256", str(wrong) + ".sha256")
        mismatch = await restore(target_url, wrong)
        assert mismatch.returncode == 5, mismatch.stderr
        assert "selected backup checksum mismatch" in mismatch.stderr

        refused = await restore(source_url, archive)
        assert refused.returncode == 6, refused.stderr
        assert "restore target contains existing relations" in refused.stderr
        assert {item.id for item in await live.export(ids, context=context)} == set(ids)

        assert (await live.delete(
            retired.id, reason="synthetic recovery deletion", context=context,
        )).persisted
        async with source_sessions.begin() as session:
            row = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id,
            ))).scalar_one()
            row.is_granted = False
            row.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        assert {item.id for item in await live.export(ids, context=context)} == {unrelated.id}
        with pytest.raises(NeuroVaultAuthorizationError, match="retired memory identity"):
            await live.persist(retired, context=replace(context, request_id=str(uuid.uuid4())))
        with pytest.raises(NeuroVaultAuthorizationError, match="memory consent scope is revoked"):
            await live.persist(revoked, context=context)

        after_cutoff = await cutoff(source_url)
        assert after_cutoff["system_identifier"] == before_cutoff["system_identifier"]
        assert after_cutoff["database_oid"] == before_cutoff["database_oid"]
        assert after_cutoff["timeline_hex"] == before_cutoff["timeline_hex"]
        assert lsn(after_cutoff["required_lsn"]) > lsn(before_cutoff["required_lsn"])
        # Retain the receipt outside either database. The logical restore
        # cannot overwrite it. This is test-local retention, not production WORM.
        receipt_path = tmp_path / "independent-cutoff.json"
        receipt_path.write_text(json.dumps(after_cutoff), encoding="utf-8")
        receipt_digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        wrong_digest = await verify_replay(source_url, receipt_path, "0" * 64)
        assert wrong_digest.returncode == 2
        assert "digest mismatch" in wrong_digest.stderr
        primary_rejected = await verify_replay(source_url, receipt_path, receipt_digest)
        assert primary_rejected.returncode == 2
        assert "not a paused read-only physical standby" in primary_rejected.stderr

        if physical:
            lagging = await verify_replay(standby_url, receipt_path, receipt_digest)
            assert lagging.returncode == 2, lagging.stdout
            assert "required WAL cutoff not replayed" in lagging.stderr
            await standby_sql("SELECT pg_wal_replay_resume()")
            await await_standby(
                f"SELECT pg_last_wal_replay_lsn() >= '{after_cutoff['required_lsn']}'::pg_lsn", "t",
            )
            await standby_sql("SELECT pg_wal_replay_pause()")
            await await_standby("SELECT pg_get_wal_replay_pause_state()", "paused")
            verified = await verify_replay(standby_url, receipt_path, receipt_digest)
            assert verified.returncode == 0, verified.stderr
            observation = json.loads(verified.stdout)
            assert observation["evidence_type"] == "paused_standby_replay_observation"
            assert observation["admission_verified"] is False
            assert observation["cutoff_sha256"] == receipt_digest
            assert lsn(observation["replay_lsn"]) >= lsn(after_cutoff["required_lsn"])
            assert await standby_sql(
                f"SELECT count(*) FROM memory_assertion WHERE assertion_id = '{retired.id}'"
            ) == "0"
            assert await standby_sql(
                f"SELECT is_granted FROM consent_scope WHERE scope_id = '{scope_id}'"
            ) == "f"
            assert await standby_sql(
                f"SELECT count(*) FROM memory_assertion WHERE assertion_id = '{unrelated.id}'"
            ) == "1"

        restored = await restore(target_url, archive)
        assert restored.returncode == 0, restored.stderr
        assert "recovery admission is not verified" in restored.stdout
        assert json.loads(receipt_path.read_text(encoding="utf-8")) == after_cutoff
        target_cutoff = await cutoff(target_url)
        # A logical restore in the same cluster can have a NEWER WAL position.
        # Therefore LSN alone is not evidence of physical recovery lineage.
        assert target_cutoff["system_identifier"] == after_cutoff["system_identifier"]
        assert target_cutoff["database_oid"] != after_cutoff["database_oid"]
        assert lsn(target_cutoff["required_lsn"]) >= lsn(after_cutoff["required_lsn"])
        logical_rejected = await verify_replay(target_url, receipt_path, receipt_digest)
        assert logical_rejected.returncode == 2
        assert "not a paused read-only physical standby" in logical_rejected.stderr

        # This is the known unsafe pre-reconciliation state, not authorization
        # to expose recovered records. Keep both databases isolated.
        assert {item.id for item in await recovered.export(ids, context=context)} == set(ids)
        for item in (retired, revoked):
            replay = await recovered.persist(item, context=context)
            assert replay.persisted and replay.metadata["idempotent_replay"] is True
        foreign = replace(context, user_id=str(uuid.uuid4()))
        assert await recovered.export(ids, context=foreign) == []
        assert {item.id for item in await live.export(ids, context=context)} == {unrelated.id}

        repeat = await restore(target_url, archive)
        assert repeat.returncode == 6, repeat.stderr
        assert "restore target contains existing relations" in repeat.stderr
    finally:
        try:
            if standby_started:
                await docker_postgres("pg_ctl", "-D", standby_dir, "-m", "immediate", "-w", "stop", check=False)
            for engine in engines:
                await engine.dispose()
            for name in reversed(created):
                await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await admin.close()
