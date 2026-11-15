"""Live, isolated Identity Vault plugin credential proof with enforced tenant RLS.

Only runs against /karen_plugin_vault_test; this dedicated database is disposable.
It applies canonical Identity Vault migrations 7/8 then the plugin slot migration
and proves real encryption, no-readback, CAS, revocation and audit rollback.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.core.security.encryption_utils import decrypt_data
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
    PluginCredentialConflict,
)


@pytest.mark.asyncio
async def test_live_plugin_secret_enrollment_rotation_revoke_and_audit_rollback():
    dsn = os.getenv("PLUGIN_VAULT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated PLUGIN_VAULT_TEST_DATABASE_URL is not configured")
    if urlparse(dsn).path != "/karen_plugin_vault_test":
        pytest.fail("Plugin Vault test must use /karen_plugin_vault_test")

    pg_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    raw = await asyncpg.connect(pg_dsn)
    role = "plugin_vault_test_" + uuid.uuid4().hex[:12]
    engine = None
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    plugin_id, field_key = "vault-test", "api_key"
    repo_root = Path(__file__).resolve().parents[2]
    try:
        await raw.execute("CREATE TABLE IF NOT EXISTS public.tenants (id uuid PRIMARY KEY)")
        migrations = (
            "20260827070000_07_identity_vault.sql",
            "20260827080000_08_identity_vault_tenant_scope.sql",
            "20261114050000_53_plugin_vault_binding.sql",
        )
        for filename in migrations:
            await raw.execute(
                (repo_root / "supabase/migrations" / filename).read_text(encoding="utf-8")
            )
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)",
            tenant_a, tenant_b,
        )
        await raw.execute(f'CREATE ROLE "{role}" NOLOGIN')
        await raw.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        await raw.execute(
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON '
            f'public.identity_providers, public.credentials, '
            f'public.credential_secrets, public.credential_audit_events, '
            f'public.plugin_credential_slots TO "{role}"'
        )

        engine = create_async_engine(
            pg_dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
            pool_size=5,
            max_overflow=0,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def scoped_session():
            async with factory() as session:
                # All repository operations run under this non-superuser.
                await session.execute(text(f'SET LOCAL ROLE "{role}"'))
                try:
                    yield session
                finally:
                    # Vault commits writes itself. Roll back any read-only transaction.
                    await session.rollback()

        vault = CredentialVaultService()
        vault._session_scope = scoped_session

        def write_args(secret, revision, tenant=tenant_a):
            return {
                "tenant_id": tenant,
                "actor_user_id": "plugin-admin",
                "plugin_id": plugin_id,
                "field_key": field_key,
                "secret_value": secret,
                "expected_revision": revision,
                "correlation_id": "test-correlation",
            }

        missing = await vault.list_plugin_credential_status(
            tenant_id=tenant_a,
            plugin_id=plugin_id,
            field_keys=frozenset({field_key}),
        )
        assert missing[field_key] == {
            "configured": False, "status": "missing", "revision": 0,
        }
        saved = await vault.write_plugin_credential(**write_args("test-secret-a", 0))
        assert saved == {"configured": True, "status": "active", "revision": 1}

        status_a = await vault.list_plugin_credential_status(
            tenant_id=tenant_a, plugin_id=plugin_id, field_keys=frozenset({field_key}),
        )
        status_b = await vault.list_plugin_credential_status(
            tenant_id=tenant_b, plugin_id=plugin_id, field_keys=frozenset({field_key}),
        )
        assert status_a[field_key]["status"] == "active"
        assert status_b[field_key]["status"] == "missing"
        assert "test-secret-a" not in str(status_a)

        secret_row = await raw.fetchrow(
            "SELECT secret.encrypted_value FROM public.credential_secrets AS secret "
            "JOIN public.plugin_credential_slots AS slot ON "
            "slot.tenant_id = secret.tenant_id AND slot.credential_id = secret.credential_id "
            "WHERE slot.tenant_id = $1 AND slot.plugin_id = $2 AND slot.field_key = $3",
            tenant_a, plugin_id, field_key,
        )
        assert secret_row is not None
        assert secret_row["encrypted_value"] != "test-secret-a"
        assert decrypt_data(secret_row["encrypted_value"].encode("ascii")) == "test-secret-a"

        # FORCE RLS holds even if a direct query omits the application's tenant filter.
        async with scoped_session() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :id, true)"),
                {"id": str(tenant_b)},
            )
            forbidden = await session.execute(text(
                "SELECT plugin_id FROM public.plugin_credential_slots "
                "WHERE tenant_id = CAST(:tenant AS uuid)"
            ), {"tenant": str(tenant_a)})
            assert forbidden.scalars().all() == []

        # Two concurrent writers observed the same revision. Only one can commit.
        outcomes = await asyncio.gather(
            vault.write_plugin_credential(**write_args("test-secret-b", 1)),
            vault.write_plugin_credential(**write_args("test-secret-c", 1)),
            return_exceptions=True,
        )
        assert len([entry for entry in outcomes if isinstance(entry, dict) and entry.get("revision") == 2]) == 1
        assert len([entry for entry in outcomes if isinstance(entry, PluginCredentialConflict)]) == 1

        original = await raw.fetchval(
            "SELECT encrypted_value FROM public.credential_secrets AS secret "
            "JOIN public.plugin_credential_slots AS slot "
            "ON slot.tenant_id=secret.tenant_id AND slot.credential_id=secret.credential_id "
            "WHERE slot.tenant_id=$1 AND slot.plugin_id=$2 AND slot.field_key=$3",
            tenant_a, plugin_id, field_key,
        )

        # Prevent audited persistence: no false success, no vault mutation survives.
        await raw.execute(
            f'REVOKE INSERT ON public.credential_audit_events FROM "{role}"'
        )
        with pytest.raises(Exception, match="permission denied"):
            await vault.write_plugin_credential(
                **write_args("this-must-roll-back", 2)
            )
        await raw.execute(
            f'GRANT INSERT ON public.credential_audit_events TO "{role}"'
        )
        assert await raw.fetchval(
            "SELECT encrypted_value FROM public.credential_secrets AS secret "
            "JOIN public.plugin_credential_slots AS slot "
            "ON slot.tenant_id=secret.tenant_id AND slot.credential_id=secret.credential_id "
            "WHERE slot.tenant_id=$1 AND slot.plugin_id=$2 AND slot.field_key=$3",
            tenant_a, plugin_id, field_key,
        ) == original

        receipt = await vault.revoke_plugin_credential(
            tenant_id=tenant_a,
            actor_user_id="plugin-admin",
            plugin_id=plugin_id,
            field_key=field_key,
            expected_revision=2,
            correlation_id="revoke-correlation",
        )
        assert receipt == {"configured": False, "status": "revoked", "revision": 3}
        assert await raw.fetchval(
            "SELECT count(*) FROM public.credential_secrets AS secret "
            "JOIN public.plugin_credential_slots AS slot "
            "ON slot.tenant_id=secret.tenant_id AND slot.credential_id=secret.credential_id "
            "WHERE slot.tenant_id=$1 AND slot.plugin_id=$2 AND slot.field_key=$3",
            tenant_a, plugin_id, field_key,
        ) == 0
        with pytest.raises(PluginCredentialConflict):
            await vault.revoke_plugin_credential(
                tenant_id=tenant_a, actor_user_id="plugin-admin",
                plugin_id=plugin_id, field_key=field_key,
                expected_revision=2, correlation_id="replay",
            )

        renewed = await vault.write_plugin_credential(
            **write_args("test-secret-after-revocation", 3)
        )
        assert renewed == {"configured": True, "status": "active", "revision": 4}
        audit = await raw.fetch(
            "SELECT event_type, action, audit_metadata FROM public.credential_audit_events "
            "WHERE tenant_id=$1 ORDER BY timestamp, id",
            tenant_a,
        )
        operations = {row["action"] for row in audit}
        assert "plugin_credential_created" in operations
        assert "plugin_credential_rotated" in operations
        assert "plugin_credential_revoked" in operations
        assert "this-must-roll-back" not in str(audit)
        assert "test-secret-after-revocation" not in str(audit)
        assert all(
            set(
                json.loads(row["audit_metadata"])
                if isinstance(row["audit_metadata"], str)
                else row["audit_metadata"]
            ) <= {"plugin_id", "field_key"}
            for row in audit
        )
        assert all(
            (
                json.loads(row["audit_metadata"])
                if isinstance(row["audit_metadata"], str)
                else row["audit_metadata"]
            ).get("plugin_id") == plugin_id
            for row in audit
        )

        # Host-only personal key candidate proof runs in the same disposable
        # PostgreSQL database, under the same restricted tenant role. This
        # metadata read must never decrypt, grant execution, or use another
        # tenant's credential.
        from ai_karen_engine.auth.models import UserData
        from ai_karen_engine.core.runtime.chat_runtime_contract import (
            ChatExecutionContext,
        )
        from ai_karen_engine.core.security.encryption_utils import encrypt_data

        owner = "personal-owner"
        provider_uuid = uuid.uuid4()
        credential_a = uuid.uuid4()
        credential_b = uuid.uuid4()
        await raw.execute(
            "INSERT INTO public.identity_providers "
            "(id, tenant_id, provider_id, display_name, provider_type, "
            "config, supported_capabilities, enabled, is_system) "
            "VALUES ($1, $2, 'openai', 'Registered OpenAI', 'api_key', "
            "$3::json, '[]'::json, true, true)",
            provider_uuid, tenant_a,
            json.dumps({"managed_for": "model_api_key"}),
        )
        await raw.execute(
            "INSERT INTO public.credentials "
            "(id, tenant_id, name, provider_id, status, "
            "credential_type, created_by) "
            "VALUES ($1, $2, 'Test personal key', $3, 'active', "
            "'model_api_key', $4)",
            credential_a, tenant_a, provider_uuid, owner,
        )
        await raw.execute(
            "INSERT INTO public.credential_secrets "
            "(id, tenant_id, credential_id, secret_type, encrypted_value) "
            "VALUES ($1, $2, $3, 'api_key', $4)",
            uuid.uuid4(), tenant_a, credential_a,
            encrypt_data("non-production-personal-test-key").decode("ascii"),
        )

        def owner_context(tenant_id):
            return ChatExecutionContext(
                user_id=owner, tenant_id=str(tenant_id),
                request_id="candidate-integration",
                session_id="candidate-session",
                correlation_id="candidate-correlation",
                authenticated_user=UserData(
                    user_id=owner, tenant_id=str(tenant_id),
                    is_active=True, is_verified=True,
                ),
            )

        owner_a = owner_context(tenant_a)
        owner_b = owner_context(tenant_b)
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) == credential_a
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_b, provider_id="openai",
        ) is None
        await raw.execute(
            "INSERT INTO public.credentials "
            "(id, tenant_id, name, provider_id, status, "
            "credential_type, created_by) "
            "VALUES ($1, $2, 'Second personal key', $3, 'active', "
            "'model_api_key', $4)",
            credential_b, tenant_a, provider_uuid, owner,
        )
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) is None
        assert await vault.revoke_owned_credential(
            credential_b, tenant_a, owner, reason="integration_test",
        ) is True
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) == credential_a
        await raw.execute(
            "UPDATE public.identity_providers SET enabled = false "
            "WHERE id = $1 AND tenant_id = $2",
            provider_uuid, tenant_a,
        )
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) is None
        await raw.execute(
            "UPDATE public.identity_providers SET enabled = true, "
            "config = $3::json WHERE id = $1 AND tenant_id = $2",
            provider_uuid, tenant_a,
            json.dumps({"managed_for": "plugin_credentials"}),
        )
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) is None
        await raw.execute(
            "UPDATE public.identity_providers SET config = $3::json "
            "WHERE id = $1 AND tenant_id = $2",
            provider_uuid, tenant_a,
            json.dumps({"managed_for": "model_api_key"}),
        )
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) == credential_a
        # A persisted owner opt-in must match the exact model. It remains
        # consent metadata, not authorization to read the encrypted key.
        from ai_karen_engine.database.models.identity_vault import (
            CredentialSecretCreate,
        )

        consented_model = "gpt-4o-mini"
        assert await vault.set_owned_personal_model_chat_consent(
            credential_id=credential_a,
            tenant_id=tenant_a,
            user_id=owner,
            model_id=consented_model,
            enabled=True,
            correlation_id="live-consent-enabled",
        ) is True
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
            consented_model_id=consented_model,
        ) == credential_a
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
            consented_model_id="some-other-model",
        ) is None
        stored_metadata = await raw.fetchval(
            "SELECT credential_metadata FROM public.credentials "
            "WHERE id = $1 AND tenant_id = $2", credential_a, tenant_a,
        )
        if isinstance(stored_metadata, str):
            stored_metadata = json.loads(stored_metadata)
        assert stored_metadata["personal_model_chat_consent"] == {
            "enabled": True, "model_id": consented_model,
        }

        # Explicit opt-out must clear stored consent without re-provisioning.
        assert await vault.set_owned_personal_model_chat_consent(
            credential_id=credential_a,
            tenant_id=tenant_a,
            user_id=owner,
            model_id=None,
            enabled=False,
            correlation_id="live-consent-disabled",
        ) is True
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
            consented_model_id=consented_model,
        ) is None

        # A newly rotated secret must not inherit the previous selection.
        assert await vault.set_owned_personal_model_chat_consent(
            credential_id=credential_a,
            tenant_id=tenant_a,
            user_id=owner,
            model_id=consented_model,
            enabled=True,
            correlation_id="live-consent-before-rotation",
        ) is True
        rotated = await vault.rotate_owned_credential(
            credential_a,
            [CredentialSecretCreate(
                secret_type="api_key",
                encrypted_value="non-production-rotated-model-test-key",
            )],
            tenant_a, owner,
        )
        assert rotated is not None
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
            consented_model_id=consented_model,
        ) is None
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) == credential_a
        rotated_metadata = await raw.fetchval(
            "SELECT credential_metadata FROM public.credentials "
            "WHERE id = $1 AND tenant_id = $2", credential_a, tenant_a,
        )
        if isinstance(rotated_metadata, str):
            rotated_metadata = json.loads(rotated_metadata)
        assert "personal_model_chat_consent" not in rotated_metadata

        await raw.execute(
            "UPDATE public.credentials "
            "SET expires_at = CURRENT_TIMESTAMP - INTERVAL '1 second' "
            "WHERE id = $1 AND tenant_id = $2",
            credential_a, tenant_a,
        )
        assert await vault.find_unambiguous_owned_model_key_candidate(
            context=owner_a, provider_id="openai",
        ) is None
        assert await raw.fetchval(
            "SELECT count(*) FROM public.credential_audit_events "
            "WHERE tenant_id = $1 AND action = 'personal_model_credential_resolved'",
            tenant_a,
        ) == 0

    finally:
        if engine is not None:
            await engine.dispose()
        try:
            await raw.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"')
            await raw.execute(f'REVOKE USAGE ON SCHEMA public FROM "{role}"')
            await raw.execute(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            await raw.close()
