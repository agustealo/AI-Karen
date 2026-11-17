"""Real PostgreSQL multi-session proof for application-global lifecycle claims.

Requires a disposable DB named exactly /karen_plugin_lifecycle_test. The test
applies the actual migrations and uses a restricted non-superuser backend role
for every repository operation. This test cannot exercise the physical kernel
transition, which remains gated pending verified finalization.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import replace
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
    PluginLifecycleApprovalScope,
    PluginLifecycleKernelObservation,
)
from ai_karen_engine.services.plugin_service import PluginService
from ai_karen_engine.persistence.repositories import plugin_lifecycle_repository as ledger_module
from ai_karen_engine.persistence.repositories.plugin_lifecycle_repository import (
    PluginLifecycleApprovalRejected,
    PluginLifecycleLedger,
    PluginLifecycleLedgerError,
    PluginLifecycleOperationNotFound,
    PluginLifecycleRevisionConflict,
)


def _scope(
    *,
    installation_id: str,
    tenant: uuid.UUID,
    actor: uuid.UUID,
    checksum: str = "a" * 64,
    revision: int = 1,
) -> PluginLifecycleApprovalScope:
    return PluginLifecycleApprovalScope(
        installation_id=installation_id,
        action="disable",
        manifest_checksum=checksum,
        expected_state="enabled",
        expected_revision=revision,
        tenant_id=str(tenant),
        user_id=str(actor),
        session_id="session-1",
        conversation_id=str(uuid.UUID("22222222-2222-2222-2222-222222222222")),
    )


@pytest.mark.asyncio
async def test_global_lifecycle_claim_cas_approval_rls_and_uncertain_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    dsn = os.getenv("PLUGIN_LIFECYCLE_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated plugin lifecycle PostgreSQL is not configured")
    if urlparse(dsn).path != "/karen_plugin_lifecycle_test":
        pytest.fail("Lifecycle proof requires /karen_plugin_lifecycle_test")

    raw = await asyncpg.connect(
        dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    engine = None
    suffix = uuid.uuid4().hex[:12]
    backend_role = "lifecycle_backend_" + suffix
    client_role = "lifecycle_client_" + suffix
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    actor_a, actor_b = uuid.uuid4(), uuid.uuid4()
    try:
        await raw.execute(
            "CREATE TABLE IF NOT EXISTS public.tenants(id uuid PRIMARY KEY);"
            "CREATE TABLE IF NOT EXISTS public.auth_users(user_id uuid PRIMARY KEY);"
        )
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2) ON CONFLICT DO NOTHING",
            tenant_a, tenant_b,
        )
        await raw.execute(
            "INSERT INTO public.auth_users(user_id) VALUES($1),($2) ON CONFLICT DO NOTHING",
            actor_a, actor_b,
        )
        await raw.execute(f'CREATE ROLE "{backend_role}" NOLOGIN')
        await raw.execute(f'CREATE ROLE "{client_role}" NOLOGIN')
        await raw.execute(
            (
                Path(__file__).resolve().parents[2]
                / "supabase/migrations/20261006030000_26_runtime_human_approval_authority.sql"
            ).read_text(encoding="utf-8")
        )
        await raw.execute(
            (
                Path(__file__).resolve().parents[2]
                / "supabase/migrations/20261117010000_60_plugin_global_lifecycle_revision.sql"
            ).read_text(encoding="utf-8")
        )
        await raw.execute(
            (
                Path(__file__).resolve().parents[2]
                / "supabase/migrations/20261117020000_61_plugin_global_lifecycle_terminal_status.sql"
            ).read_text(encoding="utf-8")
        )
        status_max_length = await raw.fetchval(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'extension_lifecycle_operations' "
            "AND column_name = 'status'"
        )
        assert status_max_length >= len("verified_committed")
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{backend_role}"')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{client_role}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.extension_lifecycle_revisions TO "{backend_role}"'
        )
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE ON public.extension_lifecycle_operations TO "{backend_role}"'
        )
        await raw.execute(
            f'GRANT SELECT, UPDATE ON public.runtime_approval_requests TO "{backend_role}"'
        )
        engine = create_async_engine(
            dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_size=5, max_overflow=0,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def scoped_transaction(tenant_id: str | None = None):
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(text(f'SET LOCAL ROLE "{backend_role}"'))
                    if tenant_id is not None:
                        await session.execute(
                            text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                            {"tenant": tenant_id},
                        )
                    yield session

        monkeypatch.setattr(ledger_module, "async_transaction_scope", scoped_transaction)
        ledger = PluginLifecycleLedger()

        async def approve(scope: PluginLifecycleApprovalScope) -> str:
            approval_id = uuid.uuid4()
            await raw.execute(
                """
                INSERT INTO public.runtime_approval_requests
                (approval_id, tenant_id, user_id, conversation_id,
                 request_fingerprint, policy_decision_id, intent, risk_level,
                 request_payload, status, expires_at)
                VALUES ($1, $2, $3, $4, 'test-only-fingerprint', 'policy-test-1',
                        $5, 'high', $6::jsonb, 'approved',
                        now() + interval '20 minutes')
                """,
                approval_id, uuid.UUID(scope.tenant_id), uuid.UUID(scope.user_id),
                uuid.UUID(scope.conversation_id),
                "plugin.lifecycle." + scope.action,
                json.dumps({"plugin_lifecycle_scope": scope.to_record()}),
            )
            return str(approval_id)

        clock = _scope(installation_id="timezone-clock", tenant=tenant_a, actor=actor_a)
        snapshot = await ledger.initialize_observation(
            installation_id=clock.installation_id,
            manifest_checksum=clock.manifest_checksum,
            observed_state="enabled",
        )
        assert snapshot["revision"] == 1
        assert snapshot["disposition"] == "ready"
        with pytest.raises(PluginLifecycleRevisionConflict):
            await ledger.initialize_observation(
                installation_id=clock.installation_id,
                manifest_checksum="b" * 64,
                observed_state="enabled",
            )

        # For a global installation, two different tenants may both have
        # legitimate admin approvals, but only one revision claim may win.
        tenant_b_clock = _scope(
            installation_id="timezone-clock", tenant=tenant_b, actor=actor_b,
        )
        approval_a, approval_b = await approve(clock), await approve(tenant_b_clock)
        attempts = await asyncio.gather(
            ledger.reserve_approved(
                approval_id=approval_a, scope=clock,
                request_id="a-request", correlation_id="a-correlation",
            ),
            ledger.reserve_approved(
                approval_id=approval_b, scope=tenant_b_clock,
                request_id="b-request", correlation_id="b-correlation",
            ),
            return_exceptions=True,
        )
        winners = [value for value in attempts if isinstance(value, dict)]
        conflicts = [
            value for value in attempts
            if isinstance(value, PluginLifecycleRevisionConflict)
        ]
        assert len(winners) == len(conflicts) == 1
        claim = winners[0]
        assert claim["status"] == "prepared"
        assert claim["expected_revision"] == 1
        assert claim["target_state"] == "disabled"
        assert "success" not in claim and "mutation_performed" not in claim

        observed = await ledger.read_observation("timezone-clock")
        assert observed is not None
        assert observed["disposition"] == "unresolved"
        assert observed["revision"] == 1
        assert observed["observed_state"] == "enabled"
        assert observed["active_operation_id"] == claim["operation_id"]

        winner_tenant = claim["tenant_id"]
        winner_actor = claim["actor_user_id"]
        loser_tenant = str(tenant_a) if winner_tenant == str(tenant_b) else str(tenant_b)
        loser_actor = str(actor_a) if winner_actor == str(actor_b) else str(actor_b)
        assert await ledger.read_operation(
            operation_id=claim["operation_id"],
            tenant_id=loser_tenant,
            actor_user_id=loser_actor,
        ) is None
        assert (await ledger.read_operation(
            operation_id=claim["operation_id"],
            tenant_id=winner_tenant,
            actor_user_id=winner_actor,
        ))["status"] == "prepared"

        unknown = await ledger.mark_unknown(
            operation_id=claim["operation_id"],
            tenant_id=winner_tenant,
            actor_user_id=winner_actor,
        )
        assert unknown["status"] == "unknown"
        assert (await ledger.mark_unknown(
            operation_id=claim["operation_id"],
            tenant_id=winner_tenant,
            actor_user_id=winner_actor,
        ))["status"] == "unknown"
        assert (await ledger.read_observation("timezone-clock"))["disposition"] == "unresolved"

        claimed_approval_id = (
            approval_a if claim["tenant_id"] == str(tenant_a) else approval_b
        )
        with pytest.raises(PluginLifecycleApprovalRejected):
            await ledger.reserve_approved(
                approval_id=claimed_approval_id,
                scope=clock if claim["tenant_id"] == str(tenant_a) else tenant_b_clock,
                request_id="replay", correlation_id="replay",
            )

        # Rollback proof: denied operation insert must not consume approval,
        # or leave a globally frozen revision without a durable claim row.
        second = _scope(installation_id="rollback-plugin", tenant=tenant_a, actor=actor_a)
        await ledger.initialize_observation(
            installation_id=second.installation_id,
            manifest_checksum=second.manifest_checksum,
            observed_state="enabled",
        )
        second_approval = await approve(second)
        await raw.execute(
            f'REVOKE INSERT ON public.extension_lifecycle_operations FROM "{backend_role}"'
        )
        with pytest.raises(Exception, match="permission denied"):
            await ledger.reserve_approved(
                approval_id=second_approval, scope=second,
                request_id="rollback", correlation_id="rollback",
            )
        await raw.execute(
            f'GRANT INSERT ON public.extension_lifecycle_operations TO "{backend_role}"'
        )
        assert (await ledger.read_observation(second.installation_id))["disposition"] == "ready"
        assert await raw.fetchval(
            "SELECT status FROM public.runtime_approval_requests WHERE approval_id = $1",
            uuid.UUID(second_approval),
        ) == "approved"

        # Drifted manifest approval is rejected before the global row can move.
        wrong_scope = _scope(
            installation_id="rollback-plugin", tenant=tenant_a, actor=actor_a,
            checksum="b" * 64,
        )
        with pytest.raises(PluginLifecycleApprovalRejected):
            await ledger.reserve_approved(
                approval_id=second_approval, scope=wrong_scope,
                request_id="changed", correlation_id="changed",
            )
        assert (await ledger.read_observation(second.installation_id))["disposition"] == "ready"

        # KPLUG-CONV-02C3: actual canonical kernel transition and typed
        # postcondition, not a model/chat-supplied completion assertion.
        package = tmp_path / "terminal-demo"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "handler.py").write_text(
            "class MainExtension:\n    pass\n", encoding="utf-8"
        )
        (package / "plugin_manifest.json").write_text(
            json.dumps({
                "name": "terminal-demo",
                "version": "1.0.0",
                "display_name": "Terminal Proof Plugin",
                "description": "Disposable kernel integration fixture",
                "author": "KAREN",
                "license": "MIT",
                "category": "test",
                "entrypoint": "handler:MainExtension",
                "rbac": {"default_enabled": False},
            }),
            encoding="utf-8",
        )
        (package / ".karen-manual-disabled").write_text(
            "Plugin disabled explicitly; requires enable\n", encoding="utf-8"
        )
        service = PluginService(tmp_path, tmp_path)
        await service.initialize()
        kernel = service.kernel
        assert kernel is not None
        observed_before = kernel.get_record("terminal-demo")
        assert observed_before is not None
        assert observed_before["status"] == "disabled"
        # C2 approvals use the loader-selected manifest SHA-256, NOT the
        # catalog's legacy MD5 directory fingerprint.
        preflight_evidence = await kernel.observe_lifecycle_for_finalization(
            "terminal-demo", operation_id=str(uuid.uuid4()),
        )
        checksum = preflight_evidence.manifest_checksum
        assert len(checksum) == 64
        assert checksum != str(observed_before["checksum"])

        enable_scope = PluginLifecycleApprovalScope(
            installation_id="terminal-demo",
            action="enable",
            manifest_checksum=checksum,
            expected_state="disabled",
            expected_revision=1,
            tenant_id=str(tenant_a),
            user_id=str(actor_a),
            session_id="session-1",
            conversation_id=str(uuid.UUID("22222222-2222-2222-2222-222222222222")),
        )
        await ledger.initialize_observation(
            installation_id="terminal-demo",
            manifest_checksum=checksum,
            observed_state="disabled",
        )
        enable_approval = await approve(enable_scope)
        enable_claim = await ledger.reserve_approved(
            approval_id=enable_approval,
            scope=enable_scope,
            request_id="kernel-proof",
            correlation_id="kernel-correlation",
        )
        # A prepared claim alone cannot mint a final receipt.
        with pytest.raises(TypeError, match="Trusted kernel"):
            await ledger.complete_verified(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                observation={"observed_state": "enabled"},
            )
        await service.enable_plugin("terminal-demo")
        observation = await kernel.observe_lifecycle_for_finalization(
            "terminal-demo", operation_id=enable_claim["operation_id"],
        )
        assert isinstance(observation, PluginLifecycleKernelObservation)
        assert observation.observed_state == "enabled"
        assert observation.manifest_checksum == checksum

        for altered in (
            replace(observation, operation_id=str(uuid.uuid4())),
            replace(observation, manifest_checksum="b" * 64),
            replace(observation, observed_state="disabled"),
        ):
            with pytest.raises(PluginLifecycleRevisionConflict):
                await ledger.complete_verified(
                    operation_id=enable_claim["operation_id"],
                    tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                    observation=altered,
                )
        with pytest.raises(PluginLifecycleOperationNotFound):
            await ledger.complete_verified(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_b), actor_user_id=str(actor_b),
                observation=observation,
            )
        assert (await ledger.read_observation("terminal-demo"))["disposition"] == "unresolved"

        # Fail specifically AFTER the revision CAS, when writing the
        # operation's terminal receipt. SELECT FOR UPDATE retains its ordinary
        # privilege, so this tests actual two-row transaction rollback.
        await raw.execute("""
            CREATE FUNCTION public.kplug_ci_reject_terminal_receipt()
            RETURNS trigger LANGUAGE plpgsql AS $kplug$
            BEGIN
                RAISE EXCEPTION 'kplug test-only terminal write rejection';
            END
            $kplug$;
            CREATE TRIGGER kplug_ci_reject_terminal_receipt
            BEFORE UPDATE OF status ON public.extension_lifecycle_operations
            FOR EACH ROW
            WHEN (NEW.status = 'verified_committed')
            EXECUTE FUNCTION public.kplug_ci_reject_terminal_receipt();
        """)
        try:
            with pytest.raises(Exception, match="kplug test-only terminal"):
                await ledger.complete_verified(
                    operation_id=enable_claim["operation_id"],
                    tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                    observation=observation,
                )
        finally:
            await raw.execute("""
                DROP TRIGGER kplug_ci_reject_terminal_receipt
                    ON public.extension_lifecycle_operations;
                DROP FUNCTION public.kplug_ci_reject_terminal_receipt();
            """)
        staged = await ledger.read_observation("terminal-demo")
        assert staged["disposition"] == "unresolved"
        assert staged["revision"] == 1
        assert staged["observed_state"] == "disabled"
        assert (await ledger.read_operation(
            operation_id=enable_claim["operation_id"],
            tenant_id=str(tenant_a), actor_user_id=str(actor_a),
        ))["status"] == "prepared"

        # Competing processes/sessions race for one prepared receipt.
        # Exactly one global CAS may commit, with no duplicate revision.
        completion_attempts = await asyncio.gather(
            ledger.complete_verified(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                observation=observation,
            ),
            ledger.complete_verified(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                observation=observation,
            ),
            return_exceptions=True,
        )
        committed_rows = [
            result for result in completion_attempts if isinstance(result, dict)
        ]
        denied_rows = [
            result for result in completion_attempts
            if isinstance(result, PluginLifecycleOperationNotFound)
        ]
        assert len(committed_rows) == len(denied_rows) == 1
        committed = committed_rows[0]
        assert committed["status"] == "verified_committed"
        assert committed["prior_revision"] == 1
        assert committed["next_revision"] == 2
        assert committed["verification_source"] == "plugin_kernel"
        finalized = await ledger.read_observation("terminal-demo")
        assert finalized["disposition"] == "ready"
        assert finalized["active_operation_id"] is None
        assert finalized["observed_state"] == "enabled"
        assert finalized["revision"] == 2
        with pytest.raises(PluginLifecycleOperationNotFound):
            await ledger.complete_verified(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_a), actor_user_id=str(actor_a),
                observation=observation,
            )
        with pytest.raises(PluginLifecycleLedgerError):
            await ledger.mark_unknown(
                operation_id=enable_claim["operation_id"],
                tenant_id=str(tenant_a), actor_user_id=str(actor_a),
            )
        # Unknown is not rehabilitated merely because a later snapshot
        # matches its target, even when submitted by a privileged host.
        with pytest.raises(PluginLifecycleOperationNotFound):
            await ledger.complete_verified(
                operation_id=claim["operation_id"],
                tenant_id=winner_tenant, actor_user_id=winner_actor,
                observation=PluginLifecycleKernelObservation(
                    operation_id=claim["operation_id"],
                    installation_id=claim["installation_id"],
                    manifest_checksum=claim["manifest_checksum"],
                    observed_state=claim["target_state"],
                ),
            )

        # A client with no host privilege must never read global revisions
        # or operation receipts directly, even though the tables exist.
        async with session_factory() as session:
            await session.execute(text(f'SET LOCAL ROLE "{client_role}"'))
            with pytest.raises(Exception, match="permission denied"):
                await session.execute(
                    text("SELECT * FROM public.extension_lifecycle_revisions LIMIT 1")
                )
            await session.rollback()
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            await raw.execute(
                f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{backend_role}"'
            )
            await raw.execute(
                f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{client_role}"'
            )
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{backend_role}"')
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{client_role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{backend_role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{client_role}"')
        finally:
            await raw.close()
