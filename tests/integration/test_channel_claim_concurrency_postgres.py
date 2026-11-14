"""Real PostgreSQL channel claim/race proof on a disposable dedicated database.

Runs only with CHANNEL_TEST_DATABASE_URL pointing to a database whose name is
exactly karen_channel_test. This test is destructive to that dedicated database.
It executes the checked-in channel migration and the actual repository SQL.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ai_karen_engine.persistence.repositories import channel_repository as module
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository


@pytest.mark.asyncio
async def test_live_postgres_outbound_race_and_unknown_quarantine(monkeypatch):
    url = os.getenv("CHANNEL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated CHANNEL_TEST_DATABASE_URL is not configured")
    if urlparse(url).path != "/karen_channel_test":
        pytest.fail("Live channel test must use the dedicated karen_channel_test database")

    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    raw = await asyncpg.connect(dsn)
    tenant_a, tenant_b, user, binding, inbox, delivery = [
        uuid.uuid4() for _ in range(6)
    ]
    connection_id = f"live-channel-{uuid.uuid4().hex}"
    engine = None
    try:
        # Disposable dedicated DB, with only prerequisites of the migration.
        await raw.execute("""
            DROP TABLE IF EXISTS public.channel_personal_credential_deletions CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_pairing_state CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_pairing_consents CASCADE;
            DROP TABLE IF EXISTS public.channel_connection_owners CASCADE;
            DROP TABLE IF EXISTS public.channel_outbox CASCADE;
            DROP TABLE IF EXISTS public.channel_inbox CASCADE;
            DROP TABLE IF EXISTS public.channel_link_challenges CASCADE;
            DROP TABLE IF EXISTS public.channel_identity_bindings CASCADE;
            DROP TABLE IF EXISTS public.channel_connections CASCADE;
            DROP TABLE IF EXISTS public.auth_users CASCADE;
            DROP TABLE IF EXISTS public.tenants CASCADE;
            CREATE TABLE public.tenants (id uuid PRIMARY KEY);
            CREATE TABLE public.auth_users (
                user_id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
                is_active boolean NOT NULL, is_verified boolean NOT NULL
            );
        """)
        migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261017010000_31_channel_gateway_durable_admission.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(migration)
        consent_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261018010000_33_channel_personal_pairing_consent.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(consent_migration)
        pairing_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261018020000_34_channel_personal_pairing_state.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(pairing_migration)
        deletion_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261018030000_35_channel_personal_credential_deletions.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(deletion_migration)
        retirement_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261114010000_50_channel_retirement_evidence_guard.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(retirement_migration)
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1),($2)", tenant_a, tenant_b,
        )
        await raw.execute(
            """INSERT INTO public.auth_users
               (user_id,tenant_id,is_active,is_verified)
               VALUES ($1,$2,true,true)""", user, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id,tenant_id,installation_id,provider_account_id,
                credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot','demo','vault://test',true,1)""",
            connection_id, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_identity_bindings
               (binding_id,tenant_id,connection_id,external_sender_id,user_id,
                verified_at)
               VALUES ($1,$2,$3,'sender',$4,now())""",
            binding, tenant_a, connection_id, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'event','sender','room','text','hello',$4,
                       'completed',$5,$6)""",
            inbox, tenant_a, connection_id, "a" * 64, binding, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                idempotency_key,message_kind,message_text)
               VALUES ($1,$2,$3,$4,'room','event','text','answer')""",
            delivery, tenant_a, connection_id, inbox,
        )

        engine = create_async_engine(
            "postgresql+asyncpg://" + dsn.split("://", 1)[1],
            pool_size=4, max_overflow=0,
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def real_scope(tenant_id: str):
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                        {"tenant": tenant_id},
                    )
                    yield session

        monkeypatch.setattr(module, "async_transaction_scope", real_scope)

        # Governed repository only assigns the first active verified owner.
        owner_repo = SqlChannelRepository()
        assert await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user),
        )
        assert not await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user),
        )
        assert not await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_b), connection_id=connection_id,
            user_id=str(user),
        )
        another_user = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.auth_users
               (user_id,tenant_id,is_active,is_verified)
               VALUES ($1,$2,true,true)""",
            another_user, tenant_a,
        )
        assert not await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(another_user),
        )
        assert not await owner_repo.is_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(another_user),
        )
        assert await SqlChannelRepository().is_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=connection_id, user_id=str(user),
        )
        assert not await SqlChannelRepository().is_personal_connection_owner(
            tenant_id=str(tenant_b), connection_id=connection_id, user_id=str(user),
        )

        # KOC-05 retired-host deletion request status is a read of durable
        # intent, scoped to the assigned owner and tenant, never vendor erasure.
        assert await owner_repo.list_owned_personal_credential_deletion_requests(
            tenant_id=str(tenant_a), user_id=str(user),
        ) == []
        deletion = await owner_repo.request_personal_credential_deletion(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="retired-operator",
            connection_revision=1, session_reference="opaque-session",
            credential_scope="companion-credentials",
            idempotency_key="retired-deletion-request",
        )
        assert deletion["status"] == "requested"
        recovered = await owner_repo.list_owned_personal_credential_deletion_requests(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        assert recovered == [{
            "request_id": deletion["request_id"],
            "connection_id": connection_id,
            "provider_id": "retired-operator",
            "connection_revision": 1,
            "status": "requested",
        }]
        assert await owner_repo.list_owned_personal_credential_deletion_requests(
            tenant_id=str(tenant_a), user_id=str(another_user),
        ) == []
        assert await owner_repo.list_owned_personal_credential_deletion_requests(
            tenant_id=str(tenant_b), user_id=str(user),
        ) == []

        # A direct connection DELETE must fail at transaction commit even when
        # the connection is disabled or its ChannelHost has retired.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with raw.transaction():
                await raw.execute(
                    "DELETE FROM public.channel_connections "
                    "WHERE tenant_id=$1 AND connection_id=$2",
                    tenant_a, connection_id,
                )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.channel_connections "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_a, connection_id,
        ) == 1
        assert await owner_repo.list_owned_personal_credential_deletion_requests(
            tenant_id=str(tenant_a), user_id=str(user),
        ) == recovered

        # Ordinary unowned connections remain deletable when no personal
        # retirement ledger has ever existed.
        disposable_connection = "generic-" + uuid.uuid4().hex
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id, provider_account_id,
                credential_handle, enabled, revision)
               VALUES ($1,$2,'telegram-bot','disposable','vault://test',false,1)""",
            disposable_connection, tenant_b,
        )
        assert await raw.execute(
            "DELETE FROM public.channel_connections WHERE connection_id=$1",
            disposable_connection,
        ) == "DELETE 1"

        # Exercise actual SQL consent acceptance, scope and durable revocation.
        from ai_karen_engine.services.channels.personal_pairing_policy import (
            PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        consent_repo = SqlChannelRepository()
        consent_args = dict(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="approved-managed-connector",
        )
        assert await consent_repo.get_personal_pairing_consent(**consent_args) is None
        assert await consent_repo.acknowledge_personal_pairing_risk(
            **consent_args, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        assert not await consent_repo.acknowledge_personal_pairing_risk(
            **consent_args, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        recorded = await consent_repo.get_personal_pairing_consent(**consent_args)
        assert recorded is not None
        assert recorded.user_id == str(user)
        assert recorded.policy_version == PERSONAL_WHATSAPP_CONSENT_VERSION
        assert await consent_repo.get_personal_pairing_consent(
            **{**consent_args, "tenant_id": str(tenant_b)},
        ) is None
        assert await consent_repo.revoke_personal_pairing_consent(**consent_args)
        assert await consent_repo.get_personal_pairing_consent(**consent_args) is None
        # Reacceptance creates NEW historical evidence, never overwrites revocation.
        assert await consent_repo.acknowledge_personal_pairing_risk(
            **consent_args, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        rows = await raw.fetch(
            """SELECT revoked_at FROM public.channel_personal_pairing_consents
               WHERE tenant_id=$1 AND connection_id=$2 AND user_id=$3
               ORDER BY accepted_at, consent_id""",
            tenant_a, connection_id, user,
        )
        assert len(rows) == 2
        assert sum(row["revoked_at"] is None for row in rows) == 1

        # Two independently opened SQL sessions race to write the same QR
        # event. Only one may win the locked-connection/sequence transition.
        from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
            PairingEvent, PairingEvidenceDenied, PairingObservation, PairingPhase,
        )

        def pairing_event(sequence, kind, *, receipt=None, expiry=None, provider="approved-managed-connector"):
            return PairingObservation(
                tenant_id=str(tenant_a),
                connection_id=connection_id,
                provider_id=provider,
                connection_revision=1,
                sequence=sequence,
                event=kind,
                observed_at=datetime.now(timezone.utc) - timedelta(seconds=2),
                authenticated=True,
                provider_receipt_id=receipt,
                qr_expires_at=expiry,
            )

        qr = pairing_event(
            1, PairingEvent.QR_ISSUED,
            expiry=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        attempts = await asyncio.gather(
            SqlChannelRepository().commit_personal_pairing_observation(
                observation=qr, user_id=str(user),
                provider_vetted_and_enabled=True,
            ),
            SqlChannelRepository().commit_personal_pairing_observation(
                observation=qr, user_id=str(user),
                provider_vetted_and_enabled=True,
            ),
            return_exceptions=True,
        )
        assert sum(
            not isinstance(result, Exception) for result in attempts
        ) == 1
        assert sum(
            isinstance(result, PairingEvidenceDenied) for result in attempts
        ) == 1
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == 1
        with pytest.raises(PairingEvidenceDenied):
            await SqlChannelRepository().commit_personal_pairing_observation(
                observation=pairing_event(
                    2, PairingEvent.LINK_CONFIRMED,
                    receipt="forged-foreign-tenant",
                ),
                user_id=str(another_user),
                provider_vetted_and_enabled=True,
            )
        connected = await SqlChannelRepository().commit_personal_pairing_observation(
            observation=pairing_event(
                2, PairingEvent.LINK_CONFIRMED,
                receipt="provider-link-evidence",
            ),
            user_id=str(user), provider_vetted_and_enabled=True,
        )
        assert connected.phase is PairingPhase.CONNECTED
        assert connected.sequence == 2
        assert connected.provider_link_receipt_id == "provider-link-evidence"
        # Revoking consent must deny another QR, but never trap an existing
        # linked device: authenticated teardown must still commit.
        assert await SqlChannelRepository().revoke_personal_pairing_consent(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="approved-managed-connector",
        )
        pending = await SqlChannelRepository().commit_personal_pairing_observation(
            observation=pairing_event(3, PairingEvent.DISCONNECT_REQUESTED),
            user_id=str(user), provider_vetted_and_enabled=False,
        )
        assert pending.phase is PairingPhase.DISCONNECT_PENDING
        assert pending.provider_unlink_receipt_id is None
        unlinked = await SqlChannelRepository().commit_personal_pairing_observation(
            observation=pairing_event(
                4, PairingEvent.UNLINK_CONFIRMED,
                receipt="provider-unlink-evidence",
            ),
            user_id=str(user), provider_vetted_and_enabled=False,
        )
        assert unlinked.phase is PairingPhase.DISCONNECTED
        assert unlinked.provider_unlink_receipt_id == "provider-unlink-evidence"
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == 4
        # Reacceptance does not resurrect a disconnected session.
        assert await SqlChannelRepository().acknowledge_personal_pairing_risk(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="approved-managed-connector",
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        with pytest.raises(PairingEvidenceDenied):
            await SqlChannelRepository().commit_personal_pairing_observation(
                observation=pairing_event(
                    5, PairingEvent.LINK_CONFIRMED, receipt="replay-link",
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )

        # Prove FORCE RLS using a genuinely non-owner database role. A
        # superuser's tenant-filtered SELECT would not exercise PostgreSQL
        # row-level security and is insufficient evidence of isolation.
        await raw.execute("CREATE ROLE karen_channel_rls_probe NOLOGIN")
        await raw.execute(
            "GRANT USAGE ON SCHEMA public TO karen_channel_rls_probe"
        )
        await raw.execute(
            "GRANT SELECT ON public.channel_inbox, public.channel_outbox, "
            "public.channel_personal_pairing_consents, public.channel_connection_owners, "
            "public.channel_personal_pairing_state, "
            "public.channel_personal_credential_deletions "
            "TO karen_channel_rls_probe"
        )
        await raw.execute(
            "GRANT DELETE ON public.channel_personal_pairing_consents, "
            "public.channel_connection_owners, "
            "public.channel_personal_pairing_state, "
            "public.channel_personal_credential_deletions "
            "TO karen_channel_rls_probe"
        )
        async with raw.transaction():
            await raw.execute("SET LOCAL ROLE karen_channel_rls_probe")
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_a),
            )
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_inbox"
            ) == 1
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_outbox"
            ) == 1
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_pairing_consents"
            ) == 3
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_pairing_state"
            ) == 1
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_credential_deletions"
            ) == 1
            # The tenant-scoped role has DELETE privileges but no DELETE
            # policies on governed retirement evidence tables.
            for protected_table in (
                "channel_connection_owners",
                "channel_personal_pairing_consents",
                "channel_personal_pairing_state",
                "channel_personal_credential_deletions",
            ):
                assert await raw.execute(
                    "DELETE FROM public." + protected_table
                    + " WHERE tenant_id=$1",
                    tenant_a,
                ) == "DELETE 0"
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_b),
            )
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_inbox"
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_outbox"
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_pairing_consents"
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_pairing_state"
            ) == 0
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_credential_deletions"
            ) == 0
        await raw.execute(
            "REVOKE SELECT ON public.channel_inbox, public.channel_outbox, "
            "public.channel_personal_pairing_consents, public.channel_connection_owners, "
            "public.channel_personal_pairing_state, "
            "public.channel_personal_credential_deletions "
            "FROM karen_channel_rls_probe"
        )
        await raw.execute(
            "REVOKE DELETE ON public.channel_personal_pairing_consents, "
            "public.channel_connection_owners, "
            "public.channel_personal_pairing_state, "
            "public.channel_personal_credential_deletions "
            "FROM karen_channel_rls_probe"
        )
        await raw.execute(
            "REVOKE USAGE ON SCHEMA public FROM karen_channel_rls_probe"
        )
        await raw.execute("DROP ROLE karen_channel_rls_probe")



        # Establish a second provider-scoped QR, then serialize a revocation
        # ahead of a delayed link confirmation while holding the shared
        # connection row lock. The post-revocation link must fail closed.
        assert await SqlChannelRepository().acknowledge_personal_pairing_risk(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="race-provider",
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        qr_race = pairing_event(
            1, PairingEvent.QR_ISSUED, provider="race-provider",
            expiry=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        assert (await SqlChannelRepository().commit_personal_pairing_observation(
            observation=qr_race, user_id=str(user),
            provider_vetted_and_enabled=True,
        )).phase is PairingPhase.QR_AVAILABLE
        async with raw.transaction():
            await raw.fetchrow(
                """SELECT connection_id FROM public.channel_connections
                   WHERE tenant_id=$1 AND connection_id=$2 FOR UPDATE""",
                tenant_a, connection_id,
            )
            revocation = asyncio.create_task(
                SqlChannelRepository().revoke_personal_pairing_consent(
                    tenant_id=str(tenant_a), connection_id=connection_id,
                    user_id=str(user), provider_id="race-provider",
                )
            )
            await asyncio.sleep(0.1)
            assert not revocation.done()
        assert await revocation
        with pytest.raises(PairingEvidenceDenied):
            await SqlChannelRepository().commit_personal_pairing_observation(
                observation=pairing_event(
                    2, PairingEvent.LINK_CONFIRMED,
                    provider="race-provider", receipt="too-late",
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        assert await raw.fetchval(
            """SELECT phase FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2 AND provider_id='race-provider'""",
            tenant_a, connection_id,
        ) == "qr_available"

        first, second = await asyncio.gather(
            SqlChannelRepository().claim_outbound(
                tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
            ),
            SqlChannelRepository().claim_outbound(
                tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
            ),
        )
        assert sum(value is not None for value in (first, second)) == 1
        winner = first or second
        assert winner is not None and winner.user_id == str(user)
        assert await SqlChannelRepository().claim_outbound(
            tenant_id=str(tenant_b), delivery_id=str(delivery), lease_seconds=90,
        ) is None

        # A second host cannot finalize the first host's reservation,
        # even if it fabricates provider success evidence.
        from ai_karen_engine.extensions.channels.contracts import (
            ChannelDeliveryReceipt, ChannelDeliveryState,
        )
        false_receipt = ChannelDeliveryReceipt(
            delivery_id=str(delivery),
            state=ChannelDeliveryState.SENT,
            provider_message_id="not-verified-by-this-claim",
        )
        assert await SqlChannelRepository().finalize_outbound_claim(
            tenant_id=str(tenant_a),
            claim_token=str(uuid.uuid4()),
            receipt=false_receipt,
        ) is False
        assert await SqlChannelRepository().finalize_outbound_claim(
            tenant_id=str(tenant_b),
            claim_token=winner.claim_token,
            receipt=false_receipt,
        ) is False
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            delivery,
        ) == "accepted"

        await raw.execute(
            """UPDATE public.channel_outbox SET claim_expires_at =
               clock_timestamp() - interval '10 seconds'
               WHERE delivery_id = $1""", delivery,
        )
        # Once the lease expires, even its original holder cannot
        # manufacture a late SENT result. Quarantine owns the outcome.
        assert await SqlChannelRepository().finalize_outbound_claim(
            tenant_id=str(tenant_a),
            claim_token=winner.claim_token,
            receipt=false_receipt,
        ) is False
        quarantined = await SqlChannelRepository().quarantine_expired_outbound_claims(
            tenant_id=str(tenant_a),
        )
        assert quarantined == [str(delivery)]
        state = await raw.fetchrow(
            """SELECT status,attempt_count,claim_token,claim_expires_at
               FROM public.channel_outbox WHERE delivery_id=$1""", delivery,
        )
        assert state["status"] == "unknown"
        assert state["attempt_count"] == 1
        assert state["claim_token"] is None
        assert state["claim_expires_at"] is None
        assert await SqlChannelRepository().claim_outbound(
            tenant_id=str(tenant_a), delivery_id=str(delivery), lease_seconds=90,
        ) is None
        assert await SqlChannelRepository().list_unattempted_outbound(
            tenant_id=str(tenant_a), connection_id=connection_id,
        ) == []

        # Explicit tenant-account erasure must still cascade through personal
        # evidence, even though direct connection deletion is now restricted.
        erase_tenant, erase_user = uuid.uuid4(), uuid.uuid4()
        erase_connection = "erase-" + uuid.uuid4().hex
        await raw.execute(
            "INSERT INTO public.tenants(id) VALUES($1)", erase_tenant,
        )
        await raw.execute(
            "INSERT INTO public.auth_users(user_id,tenant_id,is_active,is_verified) "
            "VALUES ($1,$2,true,true)",
            erase_user, erase_tenant,
        )
        await raw.execute(
            """INSERT INTO public.channel_connections
                (connection_id,tenant_id,installation_id,provider_account_id,
                 credential_handle,enabled,revision)
                VALUES ($1,$2,'telegram-bot','erase-test','vault://test',false,1)""",
            erase_connection, erase_tenant,
        )
        await raw.execute(
            "INSERT INTO public.channel_connection_owners "
            "(tenant_id,connection_id,user_id) VALUES ($1,$2,$3)",
            erase_tenant, erase_connection, erase_user,
        )
        await raw.execute(
            "INSERT INTO public.channel_personal_pairing_consents "
            "(tenant_id,connection_id,user_id,provider_id,policy_version) "
            "VALUES ($1,$2,$3,'retired-operator','v1')",
            erase_tenant, erase_connection, erase_user,
        )
        await raw.execute(
            "INSERT INTO public.channel_personal_pairing_state "
            "(tenant_id,connection_id,provider_id,connection_revision) "
            "VALUES ($1,$2,'retired-operator',1)",
            erase_tenant, erase_connection,
        )
        await raw.execute(
            """INSERT INTO public.channel_personal_credential_deletions
               (tenant_id,request_id,connection_id,provider_id,user_id,
                connection_revision,session_reference,credential_scope,
                idempotency_key)
               VALUES ($1,$2,$3,'retired-operator',$4,1,
                       'session','credentials','purge-test')""",
            erase_tenant, uuid.uuid4(), erase_connection, erase_user,
        )
        assert await raw.execute(
            "DELETE FROM public.tenants WHERE id=$1", erase_tenant,
        ) == "DELETE 1"
        for evidence_table in (
            "channel_connections", "channel_connection_owners",
            "channel_personal_pairing_consents", "channel_personal_pairing_state",
            "channel_personal_credential_deletions",
        ):
            assert await raw.fetchval(
                "SELECT count(*) FROM public." + evidence_table
                + " WHERE tenant_id=$1",
                erase_tenant,
            ) == 0
        # This minimal test auth_users table deliberately has no tenant FK.
        await raw.execute(
            "DELETE FROM public.auth_users WHERE user_id=$1", erase_user,
        )

        # User erasure must clear owner-scoped consent and deletion intent
        # without silently leaving those personal rows bound to the account.
        erase_principal = uuid.uuid4()
        personal_connection = "user-erase-" + uuid.uuid4().hex
        await raw.execute(
            "INSERT INTO public.auth_users(user_id,tenant_id,is_active,is_verified) "
            "VALUES ($1,$2,true,true)",
            erase_principal, tenant_b,
        )
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id,tenant_id,installation_id,provider_account_id,
                credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot','user-erase','vault://test',false,1)""",
            personal_connection, tenant_b,
        )
        await raw.execute(
            "INSERT INTO public.channel_connection_owners "
            "(tenant_id,connection_id,user_id) VALUES ($1,$2,$3)",
            tenant_b, personal_connection, erase_principal,
        )
        await raw.execute(
            "INSERT INTO public.channel_personal_pairing_consents "
            "(tenant_id,connection_id,user_id,provider_id,policy_version) "
            "VALUES ($1,$2,$3,'retired-operator','v1')",
            tenant_b, personal_connection, erase_principal,
        )
        await raw.execute(
            """INSERT INTO public.channel_personal_credential_deletions
               (tenant_id,request_id,connection_id,provider_id,user_id,
                connection_revision,session_reference,credential_scope,
                idempotency_key)
               VALUES ($1,$2,$3,'retired-operator',$4,1,
                       'session','credentials','user-purge-test')""",
            tenant_b, uuid.uuid4(), personal_connection, erase_principal,
        )
        assert await raw.execute(
            "DELETE FROM public.auth_users WHERE user_id=$1", erase_principal,
        ) == "DELETE 1"
        for personal_table in (
            "channel_connection_owners",
            "channel_personal_pairing_consents",
            "channel_personal_credential_deletions",
        ):
            assert await raw.fetchval(
                "SELECT count(*) FROM public." + personal_table
                + " WHERE tenant_id=$1 AND connection_id=$2",
                tenant_b, personal_connection,
            ) == 0
        assert await raw.execute(
            "DELETE FROM public.channel_connections WHERE connection_id=$1",
            personal_connection,
        ) == "DELETE 1"

        # Independent inbox workers race for a separate pending receipt.
        pending_inbox = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'event-pending','sender','room',
                       'text','pending',$4,'pending',$5,$6)""",
            pending_inbox, tenant_a, connection_id, "b" * 64, binding, user,
        )
        inbound_a, inbound_b = await asyncio.gather(
            SqlChannelRepository().claim_inbound(
                tenant_id=str(tenant_a), inbox_id=str(pending_inbox),
                lease_seconds=90,
            ),
            SqlChannelRepository().claim_inbound(
                tenant_id=str(tenant_a), inbox_id=str(pending_inbox),
                lease_seconds=90,
            ),
        )
        assert sum(result is not None for result in (inbound_a, inbound_b)) == 1
        assert await SqlChannelRepository().claim_inbound(
            tenant_id=str(tenant_b), inbox_id=str(pending_inbox),
            lease_seconds=90,
        ) is None
        # A revoked native sender may not claim any fresh pending work.
        await raw.execute(
            "UPDATE public.channel_identity_bindings SET revoked_at=now() "
            "WHERE binding_id=$1", binding,
        )
        after_revoke = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'event-revoked','sender','room',
                       'text','blocked',$4,'pending',$5,$6)""",
            after_revoke, tenant_a, connection_id, "c" * 64, binding, user,
        )
        assert await SqlChannelRepository().claim_inbound(
            tenant_id=str(tenant_a), inbox_id=str(after_revoke),
            lease_seconds=90,
        ) is None
    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
