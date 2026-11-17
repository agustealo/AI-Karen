"""Real PostgreSQL channel claim/race proof on a disposable dedicated database.

Runs only with CHANNEL_TEST_DATABASE_URL pointing to a database whose name is
exactly karen_channel_test. This test is destructive to that dedicated database.
It executes the checked-in channel migration and the actual repository SQL.
"""

from __future__ import annotations

import asyncio
import hashlib
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
            DROP TABLE IF EXISTS public.channel_telegram_bot_owners CASCADE;
            DROP TABLE IF EXISTS public.channel_telegram_webhook_claims CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_retirement_holds CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_credential_deletions CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_pairing_state CASCADE;
            DROP TABLE IF EXISTS public.channel_personal_pairing_consents CASCADE;
            DROP TABLE IF EXISTS public.channel_connection_owners CASCADE;
            DROP TABLE IF EXISTS public.channel_provider_status_tombstones CASCADE;
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
        link_proof_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261017020000_32_channel_link_proof.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(link_proof_migration)
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
        integrity_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261114020000_51_channel_personal_deletion_ledger_integrity.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(integrity_migration)
        hold_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261114040000_52_channel_personal_retirement_hold.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(hold_migration)
        status_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261116010000_54_channel_provider_status_ledger.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(status_migration)
        customer_window_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261116030000_56_whatsapp_customer_window_evidence.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(customer_window_migration)
        registration_claim_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261116150000_55_telegram_webhook_registration_claim.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(registration_claim_migration)
        bot_ownership_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261116160000_58_telegram_global_bot_ownership.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(bot_ownership_migration)
        status_retention_migration = (
            Path(__file__).resolve().parents[2]
            / "supabase/migrations/20261116040000_57_channel_provider_status_retention_tombstones.sql"
        ).read_text(encoding="utf-8")
        await raw.execute(status_retention_migration)
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

        # KWA-01C6B: the operator inventory must read only the scoped
        # WhatsApp connection, never disclose its Vault handle or another
        # tenant's account, and never infer live provider availability.
        operator_a_id = str(uuid.uuid4())
        operator_b_id = str(uuid.uuid4())
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id,
                provider_account_id, credential_handle, enabled, revision)
               VALUES ($1,$2,'whatsapp-cloud','990000000000001',
                       'vault://tenant-a-private',false,1),
                      ($3,$4,'whatsapp-cloud','990000000000002',
                       'vault://tenant-b-private',true,2)""",
            operator_a_id, tenant_a, operator_b_id, tenant_b,
        )
        operator_repository = SqlChannelRepository()
        assert await operator_repository.list_whatsapp_operator_connections(
            tenant_id=str(tenant_a),
        ) == [{
            "connection_id": operator_a_id,
            "connection_revision": 1,
            "enabled": False,
        }]
        assert await operator_repository.list_whatsapp_operator_connections(
            tenant_id=str(tenant_b),
        ) == [{
            "connection_id": operator_b_id,
            "connection_revision": 2,
            "enabled": True,
        }]
        assert await operator_repository.list_whatsapp_operator_connections(
            tenant_id=str(uuid.uuid4()),
        ) == []
        # Keep the existing multi-scenario test isolated. Later WhatsApp
        # acceptance cases deliberately reuse a known Meta account identity,
        # and PostgreSQL must continue enforcing its account uniqueness index.
        assert await raw.execute(
            """DELETE FROM public.channel_connections
               WHERE (tenant_id=$1 AND connection_id=$2)
                  OR (tenant_id=$3 AND connection_id=$4)""",
            tenant_a, operator_a_id, tenant_b, operator_b_id,
        ) == "DELETE 2"

        # KWA-01C6C2C1: actual SQL/RLS read projection of one scoped
        # *fixture-only* WhatsApp inbox -> ChatRuntime outbox -> status chain.
        # Never interpret manually inserted fixture rows as live Meta evidence.
        trial_connection = str(uuid.uuid4())
        trial_inbox, trial_binding, trial_delivery, trial_correlation = [
            uuid.uuid4() for _ in range(4)
        ]
        trial_event = f"wamid.fixture-{uuid.uuid4().hex}"
        trial_provider_id = f"wamid.fixture-outbound-{uuid.uuid4().hex}"
        trial_sender = "15551234444"
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id,
                provider_account_id, credential_handle, enabled, revision)
               VALUES ($1,$2,'whatsapp-cloud',$3,'vault://trial-fixture',
                       true,4)""",
            trial_connection, tenant_a, f"trial-{uuid.uuid4().hex}",
        )
        await raw.execute(
            """INSERT INTO public.channel_identity_bindings
               (binding_id, tenant_id, connection_id, external_sender_id,
                user_id, verified_at)
               VALUES ($1,$2,$3,$4,$5,now())""",
            trial_binding, tenant_a, trial_connection, trial_sender, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id, tenant_id, connection_id, connection_revision,
                external_event_id, external_sender_id,
                external_conversation_id, message_kind, message_text,
                event_digest, status, binding_id, user_id,
                correlation_id, provider_event_at)
               VALUES ($1,$2,$3,4,$4,$5,$5,'text','fixture prompt',
                       $6,'completed',$7,$8,$9,now())""",
            trial_inbox, tenant_a, trial_connection, trial_event,
            trial_sender, "a" * 64, trial_binding, user, trial_correlation,
        )
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id, tenant_id, connection_id, inbox_id,
                destination_id, idempotency_key, message_kind,
                message_text, status, provider_message_id)
               VALUES ($1,$2,$3,$4,$5,$6,'text','fixture reply',
                       'read',$7)""",
            trial_delivery, tenant_a, trial_connection,
            trial_inbox, trial_sender, str(trial_inbox), trial_provider_id,
        )
        await raw.execute(
            """INSERT INTO public.channel_provider_status_events
               (tenant_id, connection_id, connection_revision,
                provider_message_id, recipient_id, state,
                provider_timestamp, receipt_id, event_digest)
               VALUES ($1,$2,4,$3,$4,'delivered',1770000000,$5,$6),
                      ($1,$2,4,$3,$4,'read',1770000001,$7,$8),
                      ($1,$2,3,$3,$4,'sent',1770000002,$9,$10)""",
            tenant_a, trial_connection, trial_provider_id, trial_sender,
            "1" * 64, "2" * 64, "3" * 64, "4" * 64,
            "5" * 64, "6" * 64,
        )
        observed = await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=str(tenant_a), connection_id=trial_connection,
            external_event_id=trial_event,
        )
        assert observed is not None
        assert observed.inbox_id == str(trial_inbox)
        assert observed.correlation_id == str(trial_correlation)
        assert observed.inbox_status == "completed"
        assert observed.outbound_status == "read"
        assert observed.provider_receipt_states == ("delivered", "read")
        assert observed.outbound_provider_message_sha256 is not None
        assert trial_provider_id not in str(observed)
        assert trial_sender not in str(observed)
        assert "fixture prompt" not in str(observed)
        assert await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=str(tenant_b), connection_id=trial_connection,
            external_event_id=trial_event,
        ) is None
        assert await SqlChannelRepository().inspect_whatsapp_trial(
            tenant_id=str(tenant_a), connection_id=trial_connection,
            external_event_id="wamid.missing-event",
        ) is None
        # KWA-01C6C2C2: actual digest-only issuance and one-use binding
        # consumption, queried via tenant-RLS under the original principal.
        # Fixture consumption is NOT independent Meta signature evidence.
        proof_store = SqlChannelRepository()
        proof_digest = hashlib.sha256(b"fixture-sender-proof-a").hexdigest()
        proof_issued = await proof_store.issue_link_challenge(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection,
            proof_digest=proof_digest, ttl_seconds=600,
        )
        assert proof_issued is not None
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection, challenge_id=proof_issued,
        ) == "pending"
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_b), user_id=str(user),
            connection_id=trial_connection, challenge_id=proof_issued,
        ) is None
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(uuid.uuid4()),
            connection_id=trial_connection, challenge_id=proof_issued,
        ) is None
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=connection_id, challenge_id=proof_issued,
        ) is None
        # Consume through the exact canonical repository transaction. A
        # second proof use cannot mint a new sender identity.
        original_connection = await proof_store.get_enabled_connection(
            tenant_id=str(tenant_a), connection_id=trial_connection,
        )
        assert original_connection is not None
        new_sender = "15551234555"
        consumed = await proof_store.consume_verified_link(
            connection=original_connection,
            external_sender_id=new_sender,
            proof_digest=proof_digest,
        )
        assert consumed is not None and consumed.user_id == str(user)
        assert await proof_store.consume_verified_link(
            connection=original_connection,
            external_sender_id=new_sender,
            proof_digest=proof_digest,
        ) is None
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection, challenge_id=proof_issued,
        ) == "consumed"

        superseded = await proof_store.issue_link_challenge(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection,
            proof_digest=hashlib.sha256(b"fixture-sender-proof-b").hexdigest(),
            ttl_seconds=600,
        )
        expiring = await proof_store.issue_link_challenge(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection,
            proof_digest=hashlib.sha256(b"fixture-sender-proof-c").hexdigest(),
            ttl_seconds=600,
        )
        assert superseded is not None and expiring is not None
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection, challenge_id=superseded,
        ) == "revoked"
        await raw.execute(
            """UPDATE public.channel_link_challenges
               SET created_at = clock_timestamp() - interval '20 minutes',
                   expires_at = clock_timestamp() - interval '10 minutes'
               WHERE challenge_id = $1 AND tenant_id = $2""",
            uuid.UUID(expiring), tenant_a,
        )
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection, challenge_id=expiring,
        ) == "expired"
        # Preserve the consumed historical status even after connection
        # deactivation/rotation; never assert current binding availability.
        await raw.execute(
            """UPDATE public.channel_connections
               SET enabled = false, revision = revision + 1
               WHERE tenant_id = $1 AND connection_id = $2""",
            tenant_a, trial_connection,
        )
        assert await proof_store.inspect_link_challenge_status(
            tenant_id=str(tenant_a), user_id=str(user),
            connection_id=trial_connection, challenge_id=proof_issued,
        ) == "consumed"

        # Isolate this fixture before the rest of the integration scenario.
        assert await raw.execute(
            "DELETE FROM public.channel_connections WHERE tenant_id=$1 AND connection_id=$2",
            tenant_a, trial_connection,
        ) == "DELETE 1"

        # KWA-01D: actual PostgreSQL row locking and durable claim uniqueness.
        # A separate connection avoids changing the existing outbox assertions.
        webhook_connection = f"telegram-lease-{uuid.uuid4().hex}"
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id,
                provider_account_id, credential_handle, enabled, revision)
               VALUES ($1, $2, 'telegram-bot', 'lease-test',
                       'vault://registration', true, 1)""",
            webhook_connection, tenant_a,
        )
        webhook_store = SqlChannelRepository()
        concurrent_tokens = await asyncio.gather(*(
            webhook_store.claim_telegram_webhook_registration(
                tenant_id=str(tenant_a), connection_id=webhook_connection,
                expected_revision=1, provider_bot_id=123456,
            )
            for _ in range(4)
        ))
        accepted = [token for token in concurrent_tokens if token is not None]
        assert len(accepted) == 1
        # Ownership cannot evaporate through implicit tenant or connection
        # deletion. A separate governed release must first prove unlink.
        owner_foreign_keys = await raw.fetch("""
            SELECT conname, confdeltype::text AS delete_action
            FROM pg_constraint
            WHERE conrelid = 'public.channel_telegram_bot_owners'::regclass
              AND contype = 'f'
        """)
        assert len(owner_foreign_keys) == 2
        assert all(row["delete_action"] == "r" for row in owner_foreign_keys)
        competitor = f"telegram-competing-{uuid.uuid4().hex}"
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id, provider_account_id,
                credential_handle, enabled, revision)
               VALUES ($1, $2, 'telegram-bot', 'competing',
                       'vault://competing', true, 1)""",
            competitor, tenant_b,
        )
        with pytest.raises(PermissionError, match="ownership verification denied"):
            await webhook_store.claim_telegram_webhook_registration(
                tenant_id=str(tenant_b), connection_id=competitor,
                expected_revision=1, provider_bot_id=123456,
            )
        # A collision cannot leave a partial claim for the competing tenant.
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_telegram_webhook_claims
               WHERE connection_id = $1""", competitor,
        ) == 0
        assert await webhook_store.claim_telegram_webhook_registration(
            tenant_id=str(tenant_b), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is None
        # Transition attempts through the repository must be denied while the
        # remote effect is in flight. A lease expiry cannot grant retry.
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await webhook_store.set_connection_enabled(
                tenant_id=str(tenant_a), connection_id=webhook_connection,
                expected_revision=1, enabled=False,
            )
        assert await webhook_store.complete_telegram_webhook_registration(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, claim_token=accepted[0], verified=False,
        ) is False
        assert await webhook_store.claim_telegram_webhook_registration(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is None
        with pytest.raises(IntegrityError):
            await webhook_store.set_connection_enabled(
                tenant_id=str(tenant_a), connection_id=webhook_connection,
                expected_revision=1, enabled=False,
            )



        # KWA-01D4: recovery never turns an unexpired or in-flight claim
        # into permission to retry. A provider read-back must be independently
        # supplied by the host before this narrowly fenced SQL transition.
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is False
        await raw.execute(
            """UPDATE public.channel_telegram_webhook_claims
               SET claim_expires_at = clock_timestamp() - interval '1 second'
               WHERE tenant_id = $1 AND connection_id = $2""",
            tenant_a, webhook_connection,
        )
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_b), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is False
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=987654,
        ) is False
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=2, provider_bot_id=123456,
        ) is False
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is True
        assert await webhook_store.verify_uncertain_telegram_webhook_claim(
            tenant_id=str(tenant_a), connection_id=webhook_connection,
            expected_revision=1, provider_bot_id=123456,
        ) is False
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_telegram_bot_owners
               WHERE tenant_id = $1 AND connection_id = $2
                 AND provider_bot_id = 123456""",
            tenant_a, webhook_connection,
        ) == 1

        # KWA-01C2: real SQL proves a signed Meta customer timestamp,
        # a closed 24h window, a later customer reset, immutable evidence,
        # and denial of tenant/recipient substitution after a one-shot claim.
        from ai_karen_engine.extensions.channels.contracts import InboundChannelEvent
        from ai_karen_engine.persistence.repositories.channel_repository import (
            ChannelAdmissionDenied,
        )

        wa_store = SqlChannelRepository()
        wa_connection = f"wa-window-{uuid.uuid4().hex}"
        wa_recipient = "15551234567"
        wa_binding = uuid.uuid4()
        wa_delivery = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id, provider_account_id,
                credential_handle, enabled, revision)
               VALUES ($1, $2, 'whatsapp-cloud', '10987654321', 'vault://meta',
                       true, 1)""",
            wa_connection, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_identity_bindings
               (binding_id, tenant_id, connection_id, external_sender_id,
                user_id, verified_at)
               VALUES ($1, $2, $3, $4, $5, now())""",
            wa_binding, tenant_a, wa_connection, wa_recipient, user,
        )
        wa_account = await wa_store.get_enabled_connection(
            tenant_id=str(tenant_a), connection_id=wa_connection,
        )
        assert wa_account is not None
        old_customer_time = int(
            (datetime.now(timezone.utc) - timedelta(hours=25)).timestamp()
        )
        stale_admission = await wa_store.admit_verified_inbound(
            connection=wa_account,
            event=InboundChannelEvent(
                connection_id=wa_connection, external_event_id="wamid.customer-old",
                external_sender_id=wa_recipient,
                external_conversation_id=wa_recipient,
                message_kind="text", text="Old question",
                provider_timestamp=old_customer_time,
            ),
        )
        recorded_time = await raw.fetchval(
            "SELECT extract(epoch FROM provider_event_at)::bigint "
            "FROM public.channel_inbox WHERE inbox_id=$1",
            uuid.UUID(stale_admission.inbox_id),
        )
        assert recorded_time == old_customer_time
        await raw.execute(
            """UPDATE public.channel_inbox SET status='completed'
               WHERE inbox_id=$1""",
            uuid.UUID(stale_admission.inbox_id),
        )
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id, tenant_id, connection_id, inbox_id,
                destination_id, idempotency_key, message_kind, message_text)
               VALUES ($1, $2, $3, $4, $5, 'reply-old', 'text', 'Reply')""",
            wa_delivery, tenant_a, wa_connection,
            uuid.UUID(stale_admission.inbox_id), wa_recipient,
        )
        wa_claim = await wa_store.claim_outbound(
            tenant_id=str(tenant_a), delivery_id=str(wa_delivery), lease_seconds=90,
        )
        assert wa_claim is not None
        assert not await wa_store.whatsapp_customer_window_open(
            tenant_id=str(tenant_a), claimed=wa_claim,
        )
        with pytest.raises(asyncpg.PostgresError):
            await raw.execute(
                "UPDATE public.channel_inbox SET provider_event_at=now() "
                "WHERE inbox_id=$1",
                uuid.UUID(stale_admission.inbox_id),
            )
        # Another authenticated message from the exact same contact/binding
        # refreshes the policy window; an outgoing message never does.
        fresh_admission = await wa_store.admit_verified_inbound(
            connection=wa_account,
            event=InboundChannelEvent(
                connection_id=wa_connection, external_event_id="wamid.customer-new",
                external_sender_id=wa_recipient,
                external_conversation_id=wa_recipient,
                message_kind="text", text="New question",
                provider_timestamp=int(
                    (datetime.now(timezone.utc) - timedelta(minutes=2)).timestamp()
                ),
            ),
        )
        assert fresh_admission.inserted
        assert await wa_store.whatsapp_customer_window_open(
            tenant_id=str(tenant_a), claimed=wa_claim,
        )
        assert not await wa_store.whatsapp_customer_window_open(
            tenant_id=str(tenant_b), claimed=wa_claim,
        )
        wrong_destination = wa_claim.delivery.model_copy(
            update={"destination_id": "15550009999"},
        )
        assert not await wa_store.whatsapp_customer_window_open(
            tenant_id=str(tenant_a),
            claimed=wa_claim.__class__(
                connection=wa_claim.connection, delivery=wrong_destination,
                user_id=wa_claim.user_id,
                external_conversation_id=wa_claim.external_conversation_id,
                claim_token=wa_claim.claim_token,
            ),
        )
        with pytest.raises(ChannelAdmissionDenied):
            await wa_store.admit_verified_inbound(
                connection=wa_account,
                event=InboundChannelEvent(
                    connection_id=wa_connection, external_event_id="wamid.future",
                    external_sender_id=wa_recipient,
                    external_conversation_id=wa_recipient,
                    message_kind="text", text="Bad clock",
                    provider_timestamp=int(
                        (datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()
                    ),
                ),
            )

        # A pre-migration webhook replay reuses the original receipt and
        # must never backfill an unaudited customer-window timestamp.
        legacy_event = InboundChannelEvent(
            connection_id=wa_connection,
            external_event_id="wamid.before-migration",
            external_sender_id=wa_recipient,
            external_conversation_id=wa_recipient,
            message_kind="text", text="Previously admitted",
            provider_timestamp=int(
                (datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp()
            ),
        )
        legacy_id = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id, tenant_id, connection_id, connection_revision,
                external_event_id, external_sender_id, external_conversation_id,
                message_kind, message_text, event_digest, binding_id, user_id)
               VALUES ($1, $2, $3, 1, $4, $5, $5, 'text', $6, $7, $8, $9)""",
            legacy_id, tenant_a, wa_connection, legacy_event.external_event_id,
            wa_recipient, legacy_event.text,
            module._event_digest(legacy_event.model_copy(
                update={"provider_timestamp": None},
            )),
            wa_binding, user,
        )
        replay = await wa_store.admit_verified_inbound(
            connection=wa_account, event=legacy_event,
        )
        assert replay.inserted is False
        assert replay.inbox_id == str(legacy_id)
        assert await raw.fetchval(
            "SELECT provider_event_at FROM public.channel_inbox WHERE inbox_id=$1",
            legacy_id,
        ) is None

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

        # Live SQL retirement snapshot is bounded, owner-only and read-only.
        # The stored deletion request is still pending; live channel work
        # and provider evidence remain separate, not a cleanup authorization.
        readiness = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        assert readiness == [{
            "connection_id": connection_id, "connection_revision": 1,
            "connection_enabled": True, "retirement_held": False,
            "active_consent": False,
            "unresolved_pairing": False, "provider_unlink_claim_recorded": False,
            "deletion_request_recorded": True,
            "credential_deletion_claim_recorded": False,
            "provider_revision_claims_correlated": False,
            "unverified_deletion_request": True, "inbox_not_completed": False,
            "outbound_not_confirmed": True,
        }]
        from ai_karen_engine.services.channels.consent_recovery import (
            assess_retirement_evidence_snapshot,
        )
        assessed_before = assess_retirement_evidence_snapshot(readiness[0])
        assert assessed_before["retirement_assessment"]["status"] == "blocked"
        assert assessed_before["retirement_assessment"]["cleanup_authorized"] is False
        assert "local_retirement_hold_missing" in (
            assessed_before["retirement_assessment"]["blocking_reasons"]
        )
        assert "provider_unlink_claim_missing" in (
            assessed_before["retirement_assessment"]["blocking_reasons"]
        )
        assert await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(another_user),
        ) == []
        assert await owner_repo.list_owned_personal_retirement_evidence(
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

        # A vendor claim is NOT independent verification. This real SQL
        # trigger must reject forged verified states and identity tampering.
        request_uuid = uuid.UUID(deletion["request_id"])
        with pytest.raises(asyncpg.CheckViolationError):
            await raw.execute(
                """UPDATE public.channel_personal_credential_deletions
                   SET status='verified', provider_receipt_id='forged-erasure'
                   WHERE tenant_id=$1 AND request_id=$2""",
                tenant_a, request_uuid,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await raw.execute(
                """UPDATE public.channel_personal_credential_deletions
                   SET credential_scope='other-session'
                   WHERE tenant_id=$1 AND request_id=$2""",
                tenant_a, request_uuid,
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await raw.execute(
                """INSERT INTO public.channel_personal_credential_deletions
                    (tenant_id,request_id,connection_id,provider_id,user_id,
                     connection_revision,session_reference,credential_scope,
                     idempotency_key,status,provider_receipt_id)
                    VALUES ($1,$2,$3,'retired-operator',$4,1,
                            'opaque-session','companion-credentials',
                            'forged-verification','verified','fabricated')""",
                tenant_a, uuid.uuid4(), connection_id, user,
            )

        assert await raw.execute(
            """UPDATE public.channel_personal_credential_deletions
               SET status='provider_pending', updated_at=clock_timestamp()
               WHERE tenant_id=$1 AND request_id=$2""",
            tenant_a, request_uuid,
        ) == "UPDATE 1"

        # Exercise the canonical repository's provider claim path. This
        # synthetic test receipt is NOT authentication of an actual vendor,
        # and the stored state must stop at provider_claimed.
        from ai_karen_engine.extensions.channels.contracts import (
            PersonalCredentialErasureReceipt,
        )
        claim = PersonalCredentialErasureReceipt(
            provider_id="retired-operator",
            connection_id=connection_id,
            connection_revision=1,
            session_reference="opaque-session",
            deletion_request_id=deletion["request_id"],
            provider_receipt_id="synthetic-test-claim",
            credential_scope="companion-credentials",
            erased_at=datetime.now(timezone.utc),
        )
        assert await owner_repo.record_personal_credential_deletion_claim(
            tenant_id=str(tenant_a), request_id=deletion["request_id"],
            connection_id=connection_id, user_id=str(user), receipt=claim,
        )
        assert await owner_repo.record_personal_credential_deletion_claim(
            tenant_id=str(tenant_a), request_id=deletion["request_id"],
            connection_id=connection_id, user_id=str(user), receipt=claim,
        )
        assert await raw.fetchval(
            """SELECT status FROM public.channel_personal_credential_deletions
               WHERE tenant_id=$1 AND request_id=$2""",
            tenant_a, request_uuid,
        ) == "provider_claimed"
        for altered_sql in (
            "SET status='verified'",
            "SET status='requested'",
            "SET provider_receipt_id='forged-later-receipt'",
            "SET provider_id='different-provider'",
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                await raw.execute(
                    "UPDATE public.channel_personal_credential_deletions "
                    + altered_sql
                    + " WHERE tenant_id=$1 AND request_id=$2",
                    tenant_a, request_uuid,
                )
        evidence_after_claim = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        assert evidence_after_claim[0]["unverified_deletion_request"] is True
        assert evidence_after_claim[0]["deletion_request_recorded"] is True
        assert evidence_after_claim[0]["credential_deletion_claim_recorded"] is True

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

        # Even when the callback has a valid owner, active consent,
        # matching revision and fresh event timestamp, a QR whose expiry
        # exceeds five minutes from source issuance must not consume the
        # first pairing sequence. Run this at the actual SQL admission path.
        from dataclasses import replace
        qr = pairing_event(
            1, PairingEvent.QR_ISSUED,
            expiry=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        received_at = datetime.now(timezone.utc)
        overlong_qr = replace(
            qr,
            observed_at=received_at - timedelta(minutes=4),
            qr_expires_at=received_at + timedelta(minutes=4),
        )
        with pytest.raises(PairingEvidenceDenied, match="QR"):
            await consent_repo.commit_personal_pairing_observation(
                observation=overlong_qr, user_id=str(user),
                provider_vetted_and_enabled=True,
            )
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2
                 AND provider_id='approved-managed-connector'""",
            tenant_a, connection_id,
        ) == 0
        # A correctly bounded event at the same sequence still wins the
        # normal serialized commit, without creating a synthetic QR.
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
        # The repository reducer must reject a stale, previously unseen
        # internal terminal event even when its sequence is next and the
        # connection owner/provider/revision all match.
        stale_disconnect = replace(
            pairing_event(3, PairingEvent.DISCONNECT_REQUESTED),
            observed_at=datetime.now(timezone.utc) - timedelta(minutes=6),
        )
        with pytest.raises(PairingEvidenceDenied):
            await SqlChannelRepository().commit_personal_pairing_observation(
                observation=stale_disconnect, user_id=str(user),
                provider_vetted_and_enabled=False,
            )
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == 2
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
            # Original claim fixture plus KWA-01C2's three customer
            # receipts and one WhatsApp outbox all belong to this tenant.
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_inbox"
            ) == 4
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_outbox"
            ) == 2
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

        # KWA-01B: status can beat the HTTP send receipt. Its signed evidence
        # must remain pending, never mark an unattempted outbox as delivered.
        from ai_karen_engine.extensions.channels.contracts import (
            ChannelConnection, ChannelProviderStatusEvent,
        )

        account = ChannelConnection(
            tenant_id=str(tenant_a), connection_id=connection_id,
            installation_id="whatsapp-cloud", provider_account_id="10987654321",
            credential_handle="vault://whatsapp-one", revision=1, enabled=True,
        )
        provider_id = "wamid.delayed-send-42"
        recipient_id = "15551234567"

        def signed_status(
            state: ChannelDeliveryState, *, recipient=recipient_id,
            message_id=provider_id, timestamp=1770000000,
        ) -> ChannelProviderStatusEvent:
            return ChannelProviderStatusEvent(
                connection_id=connection_id, provider_message_id=message_id,
                recipient_id=recipient, state=state,
                provider_timestamp=timestamp,
                provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                    provider_message_id=message_id,
                    recipient_id=recipient, state=state,
                    provider_timestamp=timestamp,
                ),
                error_code=(
                    "whatsapp_provider_failed"
                    if state is ChannelDeliveryState.FAILED else None
                ),
            )

        next_delivery = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                idempotency_key,message_kind,message_text)
               VALUES ($1,$2,$3,$4,'15551234567','status-receipt-test','text','answer')""",
            next_delivery, tenant_a, connection_id, inbox,
        )
        delivered_early = signed_status(ChannelDeliveryState.DELIVERED)
        assert await SqlChannelRepository().record_provider_status(
            connection=account, status=delivered_early,
        )
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            next_delivery,
        ) == "accepted"
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == 1

        new_claim = await SqlChannelRepository().claim_outbound(
            tenant_id=str(tenant_a), delivery_id=str(next_delivery),
            lease_seconds=90,
        )
        assert new_claim is not None
        assert await SqlChannelRepository().finalize_outbound_claim(
            tenant_id=str(tenant_a), claim_token=new_claim.claim_token,
            receipt=ChannelDeliveryReceipt(
                delivery_id=str(next_delivery),
                state=ChannelDeliveryState.SENT,
                provider_message_id=provider_id,
            ),
        )
        status_row = await raw.fetchrow(
            """SELECT status,provider_receipt_id,provider_message_id,attempt_count
               FROM public.channel_outbox WHERE delivery_id=$1""",
            next_delivery,
        )
        assert status_row["status"] == "delivered"
        assert status_row["provider_receipt_id"] == delivered_early.provider_receipt_id
        assert status_row["provider_message_id"] == provider_id
        assert status_row["attempt_count"] == 1

        # Replay is deduplicated, and out-of-order SENT and FAILED cannot
        # downgrade a delivered/read receipt or create another send.
        assert await SqlChannelRepository().record_provider_status(
            connection=account, status=delivered_early,
        )
        await SqlChannelRepository().record_provider_status(
            connection=account,
            status=signed_status(ChannelDeliveryState.SENT, timestamp=1770000010),
        )
        early_read = signed_status(ChannelDeliveryState.READ, timestamp=1769999999)
        assert await SqlChannelRepository().record_provider_status(
            connection=account, status=early_read,
        )
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            next_delivery,
        ) == "read"
        await SqlChannelRepository().record_provider_status(
            connection=account,
            status=signed_status(ChannelDeliveryState.FAILED, timestamp=1770000080),
        )
        await SqlChannelRepository().record_provider_status(
            connection=account, status=signed_status(
                ChannelDeliveryState.READ, recipient="19999999999",
            ),
        )
        await SqlChannelRepository().record_provider_status(
            connection=account, status=signed_status(
                ChannelDeliveryState.READ, message_id="wamid.other",
            ),
        )
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            next_delivery,
        ) == "read"
        assert await raw.fetchval(
            "SELECT attempt_count FROM public.channel_outbox WHERE delivery_id=$1",
            next_delivery,
        ) == 1

        # Connection revision and tenant cannot be selected by native sender.
        with pytest.raises(module.ChannelAdmissionDenied):
            await SqlChannelRepository().record_provider_status(
                connection=account.model_copy(update={"tenant_id": str(tenant_b)}),
                status=early_read,
            )
        with pytest.raises(module.ChannelAdmissionDenied):
            await SqlChannelRepository().record_provider_status(
                connection=account.model_copy(update={"revision": 2}),
                status=early_read,
            )

        # KWA-01C5C1: the original signed receipt SQL now admits a bounded
        # batch in one tenant-RLS transaction and one replay/prune lock.
        # This is a functional/transaction proof, not a latency claim.
        batch_repo = SqlChannelRepository()
        bulk_statuses = tuple(
            signed_status(
                ChannelDeliveryState.DELIVERED,
                message_id=f"wamid.bulk-proof-{index}",
            )
            for index in range(100)
        )
        before_bulk = await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        )
        assert await batch_repo.record_provider_status_batch(
            connection=account, statuses=bulk_statuses,
        ) == 100
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == before_bulk + 100
        assert await batch_repo.record_provider_status_batch(
            connection=account, statuses=bulk_statuses,
        ) == 100
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == before_bulk + 100
        new_event = signed_status(
            ChannelDeliveryState.READ,
            message_id="wamid.bulk-rollback-proof",
        )
        # A valid incoming receipt cannot change a digest derived from its
        # signed fields. The disposable DB owner seeds one deliberately corrupt
        # digest to prove the SQL collision and *transactional rollback*, not
        # merely Pydantic rejection before starting the transaction.
        conflicting_old = signed_status(
            ChannelDeliveryState.DELIVERED,
            message_id="wamid.bulk-existing-corrupt-digest",
        )
        await raw.execute(
            """INSERT INTO public.channel_provider_status_events (
                   tenant_id, connection_id, connection_revision,
                   provider_message_id, recipient_id, state,
                   provider_timestamp, receipt_id, event_digest, error_code
               ) VALUES ($1,$2,1,$3,$4,'delivered',$5,$6,$7,NULL)""",
            tenant_a, connection_id, conflicting_old.provider_message_id,
            conflicting_old.recipient_id, conflicting_old.provider_timestamp,
            conflicting_old.provider_receipt_id, "0" * 64,
        )
        with pytest.raises(module.ChannelAdmissionConflict, match="changed evidence"):
            await batch_repo.record_provider_status_batch(
                connection=account, statuses=(new_event, conflicting_old),
            )
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == before_bulk + 101
        await raw.execute(
            """DELETE FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2 AND receipt_id=$3""",
            tenant_a, connection_id, conflicting_old.provider_receipt_id,
        )
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == before_bulk + 100
        with pytest.raises(module.ChannelAdmissionDenied):
            await batch_repo.record_provider_status_batch(
                connection=account.model_copy(update={"revision": 2}),
                statuses=(new_event,),
            )
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        ) == before_bulk + 100

        # KWA-01C5C3: 100 signed statuses racing a destructive tenant-scoped
        # retention prune must converge to digest-only tombstones without
        # resurrecting the provider message IDs or recipient metadata.
        race_connection_id = f"wa-batch-prune-{uuid.uuid4().hex}"
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id, provider_account_id,
                credential_handle, enabled, revision)
               VALUES ($1,$2,'whatsapp-cloud','30987654321',
                       'vault://prune-race-disposable',true,1)""",
            race_connection_id, tenant_a,
        )
        race_account = ChannelConnection(
            tenant_id=str(tenant_a),
            connection_id=race_connection_id,
            installation_id="whatsapp-cloud",
            provider_account_id="30987654321",
            credential_handle="vault://prune-race-disposable",
            revision=1,
            enabled=True,
        )
        race_statuses = tuple(
            ChannelProviderStatusEvent(
                connection_id=race_connection_id,
                provider_message_id=f"wamid.prune-race-{index}",
                recipient_id="15551234567",
                state=ChannelDeliveryState.DELIVERED,
                provider_timestamp=1770000000,
                provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                    provider_message_id=f"wamid.prune-race-{index}",
                    recipient_id="15551234567",
                    state=ChannelDeliveryState.DELIVERED,
                    provider_timestamp=1770000000,
                ),
            )
            for index in range(100)
        )
        assert await batch_repo.record_provider_status_batch(
            connection=race_account, statuses=race_statuses,
        ) == 100
        # Only these explicitly disposable, unmatched receipts are aged.
        # The test never modifies a shared tenant's real provider records.
        assert await raw.execute(
            """UPDATE public.channel_provider_status_events
               SET created_at=clock_timestamp() - interval '120 days'
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == "UPDATE 100"
        replayed, pruned = await asyncio.gather(
            batch_repo.record_provider_status_batch(
                connection=race_account, statuses=race_statuses,
            ),
            batch_repo.prune_unmatched_provider_statuses(
                tenant_id=str(tenant_a), connection_id=race_connection_id,
                expected_revision=1, retention_days=90, limit=100,
                dry_run=False,
            ),
        )
        assert (replayed, pruned) == (100, 100)
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == 0
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_tombstones
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == 100

        # Parallel exact replays of an already-archived 100-receipt batch must
        # never rehydrate scrubbed PII or open an inbound/outbound chat path.
        repeated = await asyncio.gather(*[
            batch_repo.record_provider_status_batch(
                connection=race_account, statuses=race_statuses,
            )
            for _ in range(3)
        ])
        assert repeated == [100, 100, 100]
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == 0
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_tombstones
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == 100
        # Tombstones are immutable under the production trigger. To prove a
        # digest collision, insert one EXTRA deliberately inconsistent
        # disposable tombstone rather than modifying finalized evidence.
        poison_message_id = "wamid.prune-race-conflicting-receipt"
        poisoned_receipt = ChannelProviderStatusEvent(
            connection_id=race_connection_id,
            provider_message_id=poison_message_id,
            recipient_id="15551234567",
            state=ChannelDeliveryState.DELIVERED,
            provider_timestamp=1770000000,
            provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                provider_message_id=poison_message_id,
                recipient_id="15551234567",
                state=ChannelDeliveryState.DELIVERED,
                provider_timestamp=1770000000,
            ),
        )
        await raw.execute(
            """INSERT INTO public.channel_provider_status_tombstones
               (tenant_id, connection_id, receipt_id,
                event_digest, source_created_at)
               VALUES ($1,$2,$3,$4, clock_timestamp() - interval '120 days')""",
            tenant_a, race_connection_id,
            poisoned_receipt.provider_receipt_id, "0" * 64,
        )
        with pytest.raises(module.ChannelAdmissionConflict, match="Archived"):
            await batch_repo.record_provider_status_batch(
                connection=race_account,
                statuses=(*race_statuses[:99], poisoned_receipt),
            )
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, race_connection_id,
        ) == 0

        # KWA-01C3: a disabled WhatsApp connection can receive verified
        # status-only evidence for a *known previously finalized* send.
        # No new inbox admission, send, or connection reactivation follows.
        historical_id = f"wa-status-{uuid.uuid4().hex}"
        historical_binding, historical_inbox, historical_delivery = [
            uuid.uuid4() for _ in range(3)
        ]
        historical_msg = "wamid.historical-finalized"
        historical_recipient = "15550001234"
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id, tenant_id, installation_id, provider_account_id,
                credential_handle, enabled, revision)
               VALUES ($1,$2,'whatsapp-cloud','20987654321','vault://meta',
                       true,1)""",
            historical_id, tenant_a,
        )
        await raw.execute(
            """INSERT INTO public.channel_identity_bindings
               (binding_id,tenant_id,connection_id,external_sender_id,user_id,
                verified_at)
               VALUES ($1,$2,$3,$4,$5,now())""",
            historical_binding, tenant_a, historical_id, historical_recipient, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'status-before-deactivation',$4,$4,'text',
                       'customer question',$5,'completed',$6,$7)""",
            historical_inbox, tenant_a, historical_id,
            historical_recipient, "e" * 64, historical_binding, user,
        )
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                idempotency_key,message_kind,message_text,status,
                provider_message_id,attempt_count)
               VALUES ($1,$2,$3,$4,$5,'historical-unique','text','answer',
                       'sent',$6,1)""",
            historical_delivery, tenant_a, historical_id,
            historical_inbox, historical_recipient, historical_msg,
        )
        # Provider status may arrive before the HTTP send receipt, then
        # operator deactivation may occur before that receipt is finalized.
        pending_id = uuid.uuid4()
        pending_provider_id = "wamid.sent-before-disable"
        await raw.execute(
            """INSERT INTO public.channel_outbox
               (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                idempotency_key,message_kind,message_text)
               VALUES ($1,$2,$3,$4,$5,'pending-before-disable','text','Reply')""",
            pending_id, tenant_a, historical_id,
            historical_inbox, historical_recipient,
        )
        history_repo = SqlChannelRepository()
        pending_status = ChannelProviderStatusEvent(
            connection_id=historical_id,
            provider_message_id=pending_provider_id,
            recipient_id=historical_recipient,
            state=ChannelDeliveryState.DELIVERED,
            provider_timestamp=1770000009,
            provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                provider_message_id=pending_provider_id,
                recipient_id=historical_recipient,
                state=ChannelDeliveryState.DELIVERED,
                provider_timestamp=1770000009,
            ),
        )
        assert await history_repo.record_provider_status(
            connection=ChannelConnection(
                tenant_id=str(tenant_a), connection_id=historical_id,
                installation_id="whatsapp-cloud",
                provider_account_id="20987654321",
                credential_handle="vault://meta", revision=1, enabled=True,
            ),
            status=pending_status,
        )
        pending_claim = await history_repo.claim_outbound(
            tenant_id=str(tenant_a), delivery_id=str(pending_id),
            lease_seconds=90,
        )
        assert pending_claim is not None
        await raw.execute(
            """UPDATE public.channel_connections
               SET enabled=false,revision=2
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        )
        assert await history_repo.finalize_outbound_claim(
            tenant_id=str(tenant_a), claim_token=pending_claim.claim_token,
            receipt=ChannelDeliveryReceipt(
                delivery_id=str(pending_id), state=ChannelDeliveryState.SENT,
                provider_message_id=pending_provider_id,
            ),
        )
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            pending_id,
        ) == "delivered"
        history = ChannelConnection(
            tenant_id=str(tenant_a), connection_id=historical_id,
            installation_id="whatsapp-cloud", provider_account_id="20987654321",
            credential_handle="vault://meta", revision=2, enabled=False,
        )
        historical_status = ChannelProviderStatusEvent(
            connection_id=historical_id, provider_message_id=historical_msg,
            recipient_id=historical_recipient, state=ChannelDeliveryState.READ,
            provider_timestamp=1770000010,
            provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                provider_message_id=historical_msg,
                recipient_id=historical_recipient, state=ChannelDeliveryState.READ,
                provider_timestamp=1770000010,
            ),
        )
        assert await history_repo.record_deactivated_provider_status(
            connection=history, status=historical_status,
        )
        assert await history_repo.record_deactivated_provider_status(
            connection=history, status=historical_status,
        )
        assert await raw.fetchval(
            "SELECT status FROM public.channel_outbox WHERE delivery_id=$1",
            historical_delivery,
        ) == "read"
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        ) == 2
        assert await history_repo.get_enabled_connection(
            tenant_id=str(tenant_a), connection_id=historical_id,
        ) is None
        assert not await history_repo.record_deactivated_provider_status(
            connection=history,
            status=historical_status.model_copy(update={
                "recipient_id": "15559999999",
                "provider_receipt_id": ChannelProviderStatusEvent.receipt_for(
                    provider_message_id=historical_msg, recipient_id="15559999999",
                    state=ChannelDeliveryState.READ, provider_timestamp=1770000010,
                ),
            }),
        )
        assert not await history_repo.record_deactivated_provider_status(
            connection=history.model_copy(update={"tenant_id": str(tenant_b)}),
            status=historical_status,
        )
        assert not await history_repo.record_deactivated_provider_status(
            connection=history.model_copy(update={"revision": 3}),
            status=historical_status,
        )
        # Re-enabling (new revision) cannot silently reuse a disabled snapshot.
        await raw.execute(
            """UPDATE public.channel_connections
               SET enabled=true,revision=3
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        )
        assert not await history_repo.record_deactivated_provider_status(
            connection=history, status=historical_status,
        )
        # KWA-01C4: tombstone only *unmatched* old Meta status evidence.
        # Both known historical sends and their delivery/read proofs survive.
        retention_account = history.model_copy(update={
            "enabled": True, "revision": 3,
        })
        orphan_message = "wamid.unmatched-retention"
        orphan = ChannelProviderStatusEvent(
            connection_id=historical_id,
            provider_message_id=orphan_message,
            recipient_id=historical_recipient,
            state=ChannelDeliveryState.DELIVERED,
            provider_timestamp=1770000020,
            provider_receipt_id=ChannelProviderStatusEvent.receipt_for(
                provider_message_id=orphan_message,
                recipient_id=historical_recipient,
                state=ChannelDeliveryState.DELIVERED,
                provider_timestamp=1770000020,
            ),
        )
        assert await history_repo.record_provider_status(
            connection=retention_account, status=orphan,
        )
        await raw.execute(
            """UPDATE public.channel_provider_status_events
               SET created_at = clock_timestamp() - interval '100 days'
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        )
        candidates = await history_repo.prune_unmatched_provider_statuses(
            tenant_id=str(tenant_a), connection_id=historical_id,
            expected_revision=3, retention_days=90, limit=10,
            dry_run=True,
        )
        assert candidates == 1
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        ) == 3
        assert await history_repo.prune_unmatched_provider_statuses(
            tenant_id=str(tenant_b), connection_id=historical_id,
            expected_revision=3, retention_days=90, limit=10,
            dry_run=False,
        ) == 0
        assert await history_repo.prune_unmatched_provider_statuses(
            tenant_id=str(tenant_a), connection_id=historical_id,
            expected_revision=4, retention_days=90, limit=10,
            dry_run=False,
        ) == 0
        # Compete a signed replay against pruning while a separate
        # transaction holds the same scoped advisory lock. Regardless of who
        # runs first, replay cannot resurrect the scrubbed phone/message.
        async with raw.transaction():
            await raw.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"karen:channel-status:{tenant_a}:{historical_id}",
            )
            purge_task = asyncio.create_task(
                history_repo.prune_unmatched_provider_statuses(
                    tenant_id=str(tenant_a), connection_id=historical_id,
                    expected_revision=3, retention_days=90, limit=10,
                    dry_run=False,
                )
            )
            replay_task = asyncio.create_task(
                history_repo.record_provider_status(
                    connection=retention_account, status=orphan,
                )
            )
            await asyncio.sleep(0.05)
            assert not purge_task.done()
            assert not replay_task.done()
        removed, replayed = await asyncio.gather(purge_task, replay_task)
        assert removed == 1
        assert replayed is True
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        ) == 2
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_provider_status_tombstones
               WHERE tenant_id=$1 AND connection_id=$2
                 AND receipt_id=$3""",
            tenant_a, historical_id, orphan.provider_receipt_id,
        ) == 1
        assert await raw.fetchval(
            """SELECT event_digest FROM public.channel_provider_status_tombstones
               WHERE tenant_id=$1 AND connection_id=$2
                 AND receipt_id=$3""",
            tenant_a, historical_id, orphan.provider_receipt_id,
        ) == history_repo._status_event_digest(orphan)
        # A replay of the same signed orphan is acknowledged but cannot
        # restore either the provider ID or recipient phone number to storage.
        assert await history_repo.record_provider_status(
            connection=retention_account, status=orphan,
        )
        assert await raw.fetchval(
            """SELECT COUNT(*) FROM public.channel_provider_status_events
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, historical_id,
        ) == 2
        with pytest.raises(asyncpg.PostgresError):
            await raw.execute(
                """UPDATE public.channel_provider_status_tombstones
                   SET event_digest=$1 WHERE tenant_id=$2
                     AND connection_id=$3 AND receipt_id=$4""",
                "0" * 64, tenant_a, historical_id, orphan.provider_receipt_id,
            )
        # A non-superuser gets tenant-visible tombstones only. Even a
        # deliberately granted DELETE privilege cannot remove audit evidence
        # because migration 57 deliberately omits a DELETE RLS policy.
        await raw.execute("CREATE ROLE karen_status_retention_probe NOLOGIN")
        await raw.execute(
            "GRANT USAGE ON SCHEMA public TO karen_status_retention_probe"
        )
        await raw.execute(
            "GRANT SELECT, DELETE ON public.channel_provider_status_tombstones "
            "TO karen_status_retention_probe"
        )
        async with raw.transaction():
            await raw.execute("SET LOCAL ROLE karen_status_retention_probe")
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_a),
            )
            # Other disposable connections in this tenant may have their
            # own archived receipt evidence; assert the historical connection
            # only while retaining the real tenant-scoped RLS principal.
            assert await raw.fetchval(
                "SELECT COUNT(*) FROM public.channel_provider_status_tombstones "
                "WHERE connection_id=$1",
                historical_id,
            ) == 1
            assert await raw.execute(
                "DELETE FROM public.channel_provider_status_tombstones "
                "WHERE tenant_id=$1 AND connection_id=$2",
                tenant_a, historical_id,
            ) == "DELETE 0"
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_b),
            )
            assert await raw.fetchval(
                "SELECT COUNT(*) FROM public.channel_provider_status_tombstones "
                "WHERE connection_id=$1",
                historical_id,
            ) == 0
        await raw.execute(
            "REVOKE SELECT, DELETE ON public.channel_provider_status_tombstones "
            "FROM karen_status_retention_probe"
        )
        await raw.execute(
            "REVOKE USAGE ON SCHEMA public FROM karen_status_retention_probe"
        )
        await raw.execute("DROP ROLE karen_status_retention_probe")
        assert await history_repo.prune_unmatched_provider_statuses(
            tenant_id=str(tenant_a), connection_id=historical_id,
            expected_revision=3, retention_days=90, limit=10,
            dry_run=False,
        ) == 0

        # Remove isolated historical fixture so the test's pre-existing RLS
        # census remains exact, rather than weakening its assertions.
        await raw.execute(
            "DELETE FROM public.channel_connections "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_a, historical_id,
        )

        # Duplicate provider IDs for two outbox deliveries are forbidden:
        # receipt evidence must not ambiguously update multiple records.
        extra_inbox = uuid.uuid4()
        await raw.execute(
            """INSERT INTO public.channel_inbox
               (inbox_id,tenant_id,connection_id,connection_revision,
                external_event_id,external_sender_id,external_conversation_id,
                message_kind,message_text,event_digest,status,binding_id,user_id)
               VALUES ($1,$2,$3,1,'status-extra','sender','room','text','hello',
                       $4,'completed',$5,$6)""",
            extra_inbox, tenant_a, connection_id, "b" * 64, binding, user,
        )
        extra_delivery = uuid.uuid4()
        with pytest.raises(asyncpg.UniqueViolationError):
            await raw.execute(
                """INSERT INTO public.channel_outbox
                   (delivery_id,tenant_id,connection_id,inbox_id,destination_id,
                    idempotency_key,message_kind,message_text,
                    status,provider_message_id,attempt_count)
                   VALUES ($1,$2,$3,$4,'15551234567','duplicate-provider-id','text',
                           'answer','sent',$5,1)""",
                extra_delivery, tenant_a, connection_id, extra_inbox, provider_id,
            )

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
        await owner_repo.place_personal_retirement_hold(
            tenant_id=str(erase_tenant), connection_id=erase_connection,
            operator_user_id=str(erase_user), expected_revision=1,
            idempotency_key=str(uuid.uuid4()),
        )
        assert await raw.execute(
            "DELETE FROM public.tenants WHERE id=$1", erase_tenant,
        ) == "DELETE 1"
        for evidence_table in (
            "channel_connections", "channel_connection_owners",
            "channel_personal_pairing_consents", "channel_personal_pairing_state",
            "channel_personal_credential_deletions",
            "channel_personal_retirement_holds",
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
        # An owner-account privacy erasure removes the personal hold row
        # but never reopens the local connection revision fence.
        privacy_hold = await owner_repo.place_personal_retirement_hold(
            tenant_id=str(tenant_b), connection_id=personal_connection,
            operator_user_id=str(erase_principal), expected_revision=1,
            idempotency_key=str(uuid.uuid4()),
        )
        assert privacy_hold["created_new"] is True
        assert await raw.fetchval(
            "SELECT retirement_locked FROM public.channel_connections "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_b, personal_connection,
        ) is True
        assert await raw.execute(
            "DELETE FROM public.auth_users WHERE user_id=$1", erase_principal,
        ) == "DELETE 1"
        for personal_table in (
            "channel_connection_owners",
            "channel_personal_pairing_consents",
            "channel_personal_credential_deletions",
            "channel_personal_retirement_holds",
        ):
            assert await raw.fetchval(
                "SELECT count(*) FROM public." + personal_table
                + " WHERE tenant_id=$1 AND connection_id=$2",
                tenant_b, personal_connection,
            ) == 0
        assert await raw.fetchval(
            "SELECT retirement_locked FROM public.channel_connections "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_b, personal_connection,
        ) is True
        with pytest.raises(asyncpg.CheckViolationError):
            await raw.execute(
                "UPDATE public.channel_connections SET enabled=true "
                "WHERE tenant_id=$1 AND connection_id=$2",
                tenant_b, personal_connection,
            )
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

        # Explicit operator hold uses one tenant-row lock and a single SQL
        # transaction to disable, revision-fence and persist the hold.
        from ai_karen_engine.persistence.repositories.channel_repository import (
            ChannelAdmissionDenied,
            ChannelRetirementConflict,
        )
        hold_key = str(uuid.uuid4())
        args = dict(
            tenant_id=str(tenant_a), connection_id=connection_id,
            operator_user_id=str(another_user),
            expected_revision=1, idempotency_key=hold_key,
        )
        first = await owner_repo.place_personal_retirement_hold(**args)
        assert first["created_new"] is True
        assert first["connection_revision"] == 2
        assert first["hold_id"]
        replay = await owner_repo.place_personal_retirement_hold(**args)
        assert replay == {**first, "created_new": False}
        with pytest.raises(ChannelRetirementConflict):
            await owner_repo.place_personal_retirement_hold(
                **{**args, "idempotency_key": str(uuid.uuid4())},
            )
        with pytest.raises(ChannelRetirementConflict):
            await owner_repo.place_personal_retirement_hold(
                **{**args, "expected_revision": 2},
            )
        with pytest.raises(ChannelAdmissionDenied):
            await owner_repo.place_personal_retirement_hold(
                **{**args, "tenant_id": str(tenant_b)},
            )
        state = await raw.fetchrow(
            """SELECT enabled, revision, retirement_locked
               FROM public.channel_connections
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, connection_id,
        )
        assert state["enabled"] is False
        assert state["revision"] == 2
        assert state["retirement_locked"] is True
        hold_evidence = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        assert hold_evidence[0]["retirement_held"] is True
        assert hold_evidence[0]["connection_enabled"] is False
        assert hold_evidence[0]["connection_revision"] == 2
        assert hold_evidence[0]["unverified_deletion_request"] is True

        # No fresh pairing or risk-consent acceptance may be recorded after
        # the local retirement fence, even if a privileged actor directly
        # plants an otherwise valid consent for a new provider.
        assert not await owner_repo.acknowledge_personal_pairing_risk(
            tenant_id=str(tenant_a), connection_id=connection_id,
            user_id=str(user), provider_id="post-hold-provider",
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        await raw.execute(
            """INSERT INTO public.channel_personal_pairing_consents
               (tenant_id,connection_id,user_id,provider_id,policy_version)
               VALUES ($1,$2,$3,'post-hold-provider',$4)""",
            tenant_a, connection_id, user,
            PERSONAL_WHATSAPP_CONSENT_VERSION,
        )
        denied_pairing = PairingObservation(
            tenant_id=str(tenant_a), connection_id=connection_id,
            provider_id="post-hold-provider", connection_revision=2,
            sequence=1, event=PairingEvent.QR_ISSUED,
            observed_at=datetime.now(timezone.utc) - timedelta(seconds=2),
            authenticated=True,
            qr_expires_at=datetime.now(timezone.utc) + timedelta(seconds=90),
        )
        with pytest.raises(PairingEvidenceDenied):
            await owner_repo.commit_personal_pairing_observation(
                observation=denied_pairing, user_id=str(user),
                provider_vetted_and_enabled=True,
            )
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2
                 AND provider_id='post-hold-provider'""",
            tenant_a, connection_id,
        ) == 0
        for forbidden in (
            "enabled=true", "retirement_locked=false",
            "enabled=true, retirement_locked=false",
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                await raw.execute(
                    "UPDATE public.channel_connections SET " + forbidden
                    + " WHERE tenant_id=$1 AND connection_id=$2",
                    tenant_a, connection_id,
                )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with raw.transaction():
                await raw.execute(
                    "DELETE FROM public.channel_connections "
                    "WHERE tenant_id=$1 AND connection_id=$2",
                    tenant_a, connection_id,
                )
        assert await raw.fetchval(
            "SELECT count(*) FROM public.channel_personal_retirement_holds "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_a, connection_id,
        ) == 1
        assert await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_b), user_id=str(user),
        ) == []
        # Two operators racing with distinct idempotency keys must not
        # produce two holds or overwrite the first operator's audit record.
        race_connection = "race-" + uuid.uuid4().hex
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id,tenant_id,installation_id,provider_account_id,
                credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot',$3,'vault://race',true,1)""",
            race_connection, tenant_a, race_connection,
        )
        assert await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=race_connection,
            user_id=str(user),
        )
        async def attempt_hold(key):
            return await SqlChannelRepository().place_personal_retirement_hold(
                tenant_id=str(tenant_a), connection_id=race_connection,
                operator_user_id=str(another_user), expected_revision=1,
                idempotency_key=key,
            )
        race_results = await asyncio.gather(
            attempt_hold(str(uuid.uuid4())),
            attempt_hold(str(uuid.uuid4())),
            return_exceptions=True,
        )
        assert sum(isinstance(x, dict) and x["created_new"] for x in race_results) == 1
        assert sum(isinstance(x, ChannelRetirementConflict) for x in race_results) == 1
        assert await raw.fetchval(
            "SELECT count(*) FROM public.channel_personal_retirement_holds "
            "WHERE tenant_id=$1 AND connection_id=$2",
            tenant_a, race_connection,
        ) == 1

        # A non-owner role can read only its tenant's hold. Even with table
        # grants, RLS intentionally supplies no direct UPDATE/DELETE policy.
        await raw.execute("CREATE ROLE karen_retirement_hold_probe NOLOGIN")
        await raw.execute(
            "GRANT USAGE ON SCHEMA public TO karen_retirement_hold_probe"
        )
        await raw.execute(
            "GRANT SELECT, UPDATE, DELETE ON "
            "public.channel_personal_retirement_holds "
            "TO karen_retirement_hold_probe"
        )
        async with raw.transaction():
            await raw.execute("SET LOCAL ROLE karen_retirement_hold_probe")
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_a),
            )
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_retirement_holds"
            ) == 2
            assert await raw.execute(
                "UPDATE public.channel_personal_retirement_holds "
                "SET status='held' WHERE tenant_id=$1",
                tenant_a,
            ) == "UPDATE 0"
            assert await raw.execute(
                "DELETE FROM public.channel_personal_retirement_holds "
                "WHERE tenant_id=$1",
                tenant_a,
            ) == "DELETE 0"
            await raw.execute(
                "SELECT set_config('app.current_tenant_id', $1, true)",
                str(tenant_b),
            )
            assert await raw.fetchval(
                "SELECT count(*) FROM public.channel_personal_retirement_holds"
            ) == 0
        await raw.execute(
            "REVOKE SELECT, UPDATE, DELETE ON "
            "public.channel_personal_retirement_holds "
            "FROM karen_retirement_hold_probe"
        )
        await raw.execute(
            "REVOKE USAGE ON SCHEMA public FROM karen_retirement_hold_probe"
        )
        await raw.execute("DROP ROLE karen_retirement_hold_probe")

        # A real operator hold increments the local revision, but must still
        # accept strictly terminal, source-authenticated provider observations
        # for the ORIGINAL pre-hold session. No QR/link event can reopen it.
        terminal_connection = "terminal-" + uuid.uuid4().hex
        await raw.execute(
            """INSERT INTO public.channel_connections
               (connection_id,tenant_id,installation_id,provider_account_id,
                credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot',$3,'vault://terminal-test',true,1)""",
            terminal_connection, tenant_a, terminal_connection,
        )
        assert await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=terminal_connection,
            user_id=str(user),
        )
        await raw.execute(
            """INSERT INTO public.channel_personal_pairing_state
               (tenant_id, connection_id, provider_id, connection_revision,
                sequence, phase, provider_link_receipt_id)
               VALUES ($1,$2,'approved-managed-connector',1,2,'connected','linked-test')""",
            tenant_a, terminal_connection,
        )
        held = await owner_repo.place_personal_retirement_hold(
            tenant_id=str(tenant_a), connection_id=terminal_connection,
            operator_user_id=str(another_user), expected_revision=1,
            idempotency_key=str(uuid.uuid4()),
        )
        assert held["connection_revision"] == 2

        def terminal_observation(seq, event, *, revision=1, receipt=None):
            return PairingObservation(
                tenant_id=str(tenant_a),
                connection_id=terminal_connection,
                provider_id="approved-managed-connector",
                connection_revision=revision,
                sequence=seq, event=event,
                authenticated=True,
                observed_at=datetime.now(timezone.utc) - timedelta(seconds=2),
                provider_receipt_id=receipt,
                qr_expires_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=90)
                    if event is PairingEvent.QR_ISSUED else None
                ),
            )

        # Even synthetic source-authenticated events may not create another
        # pairing. Actual production ingress authenticates callbacks in host.
        with pytest.raises(PairingEvidenceDenied):
            await owner_repo.commit_personal_pairing_observation(
                observation=terminal_observation(3, PairingEvent.QR_ISSUED),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        with pytest.raises(PairingEvidenceDenied):
            await owner_repo.commit_personal_pairing_observation(
                observation=terminal_observation(
                    3, PairingEvent.UNLINK_CONFIRMED, revision=2,
                    receipt="foreign-revision",
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        disconnect = await owner_repo.commit_personal_pairing_observation(
            observation=terminal_observation(3, PairingEvent.DISCONNECT_REQUESTED),
            user_id=str(user), provider_vetted_and_enabled=True,
        )
        assert disconnect.phase is PairingPhase.DISCONNECT_PENDING
        with pytest.raises(PairingEvidenceDenied):
            await owner_repo.commit_personal_pairing_observation(
                observation=terminal_observation(
                    3, PairingEvent.DISCONNECT_REQUESTED,
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        unlink = await owner_repo.commit_personal_pairing_observation(
            observation=terminal_observation(
                4, PairingEvent.UNLINK_CONFIRMED, receipt="terminal-vendor-claim",
            ),
            user_id=str(user), provider_vetted_and_enabled=True,
        )
        assert unlink.phase is PairingPhase.DISCONNECTED
        assert unlink.provider_unlink_receipt_id == "terminal-vendor-claim"
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, terminal_connection,
        ) == 4

        # Credential deletion intent can be issued after the local hold for
        # the original pre-hold revision. A later vendor response is recorded
        # as provider_claimed ONLY, not independently verified erasure.
        # A vendor deletion claim from a different provider on the same
        # held connection must never count as one correlated unlink/erasure
        # evidence pair, even if the separate claim flags are true.
        foreign_args = dict(
            tenant_id=str(tenant_a), connection_id=terminal_connection,
            user_id=str(user), provider_id="foreign-test-provider",
            connection_revision=1, session_reference="foreign-session",
            credential_scope="companion-credentials",
            idempotency_key="foreign-" + uuid.uuid4().hex,
        )
        foreign_request = await owner_repo.request_personal_credential_deletion(
            **foreign_args,
        )
        from ai_karen_engine.extensions.channels.contracts import (
            PersonalCredentialErasureReceipt,
        )
        foreign_receipt = PersonalCredentialErasureReceipt(
            provider_id=foreign_args["provider_id"],
            connection_id=terminal_connection,
            connection_revision=1,
            session_reference=foreign_args["session_reference"],
            deletion_request_id=foreign_request["request_id"],
            provider_receipt_id="foreign-claim-test-only",
            credential_scope="companion-credentials",
            erased_at=datetime.now(timezone.utc),
        )
        assert await owner_repo.record_personal_credential_deletion_claim(
            tenant_id=str(tenant_a),
            request_id=foreign_request["request_id"],
            connection_id=terminal_connection,
            user_id=str(user), receipt=foreign_receipt,
        )
        uncorrelated = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        observed_foreign = next(
            entry for entry in uncorrelated
            if entry["connection_id"] == terminal_connection
        )
        assert observed_foreign["provider_unlink_claim_recorded"] is True
        assert observed_foreign["credential_deletion_claim_recorded"] is True
        assert observed_foreign["provider_revision_claims_correlated"] is False
        from ai_karen_engine.services.channels.consent_recovery import (
            assess_retirement_evidence_snapshot,
        )
        blocked_reasons = assess_retirement_evidence_snapshot(
            observed_foreign
        )["retirement_assessment"]["blocking_reasons"]
        assert "provider_revision_claims_mismatched" in blocked_reasons
        assert "provider_unlink_independent_verification_unavailable" in blocked_reasons

        deletion_idempotency = "terminal-" + uuid.uuid4().hex
        deletion_args = dict(
            tenant_id=str(tenant_a), connection_id=terminal_connection,
            user_id=str(user), provider_id="approved-managed-connector",
            connection_revision=1, session_reference="terminal-session",
            credential_scope="companion-credentials",
            idempotency_key=deletion_idempotency,
        )
        deletion_intent = await owner_repo.request_personal_credential_deletion(
            **deletion_args,
        )
        assert deletion_intent["status"] == "requested"
        assert await owner_repo.request_personal_credential_deletion(
            **deletion_args,
        ) == deletion_intent
        with pytest.raises(ValueError, match="owner or revision"):
            await owner_repo.request_personal_credential_deletion(
                **{**deletion_args, "connection_revision": 2},
            )
        from ai_karen_engine.extensions.channels.contracts import (
            PersonalCredentialErasureReceipt,
        )
        vendor_claim = PersonalCredentialErasureReceipt(
            provider_id="approved-managed-connector",
            connection_id=terminal_connection,
            connection_revision=1,
            session_reference="terminal-session",
            deletion_request_id=deletion_intent["request_id"],
            provider_receipt_id="terminal-deletion-vendor-claim",
            credential_scope="companion-credentials",
            erased_at=datetime.now(timezone.utc),
        )
        assert await owner_repo.record_personal_credential_deletion_claim(
            tenant_id=str(tenant_a),
            request_id=deletion_intent["request_id"],
            connection_id=terminal_connection,
            user_id=str(user), receipt=vendor_claim,
        )
        assert await owner_repo.record_personal_credential_deletion_claim(
            tenant_id=str(tenant_a),
            request_id=deletion_intent["request_id"],
            connection_id=terminal_connection,
            user_id=str(user), receipt=vendor_claim,
        )
        assert await raw.fetchval(
            """SELECT status FROM public.channel_personal_credential_deletions
               WHERE tenant_id=$1 AND request_id=$2""",
            tenant_a, uuid.UUID(deletion_intent["request_id"]),
        ) == "provider_claimed"
        terminal_evidence = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        matching = [
            entry for entry in terminal_evidence
            if entry["connection_id"] == terminal_connection
        ]
        assert len(matching) == 1
        assert matching[0]["retirement_held"] is True
        assert matching[0]["provider_unlink_claim_recorded"] is True
        assert matching[0]["unresolved_pairing"] is False
        assert matching[0]["deletion_request_recorded"] is True
        assert matching[0]["credential_deletion_claim_recorded"] is True
        assert matching[0]["provider_revision_claims_correlated"] is True

        # The older pairing-state schema permits non-null whitespace receipt
        # IDs. A malformed or imported historical row must never be counted
        # as a provider unlink claim or as correlated retirement evidence.
        for malformed_receipt in ("   ", "\t\n "):
            assert await raw.execute(
                """UPDATE public.channel_personal_pairing_state
                   SET provider_unlink_receipt_id=$3
                   WHERE tenant_id=$1 AND connection_id=$2
                     AND provider_id='approved-managed-connector'""",
                tenant_a, terminal_connection, malformed_receipt,
            ) == "UPDATE 1"
            blank_rows = await owner_repo.list_owned_personal_retirement_evidence(
                tenant_id=str(tenant_a), user_id=str(user),
            )
            blank = next(
                entry for entry in blank_rows
                if entry["connection_id"] == terminal_connection
            )
            assert blank["provider_unlink_claim_recorded"] is False
            assert blank["credential_deletion_claim_recorded"] is True
            assert blank["provider_revision_claims_correlated"] is False
            blank_assessment = assess_retirement_evidence_snapshot(blank)[
                "retirement_assessment"
            ]
            assert "provider_unlink_claim_missing" in blank_assessment["blocking_reasons"]
            assert blank_assessment["cleanup_authorized"] is False
        assert await raw.execute(
            """UPDATE public.channel_personal_pairing_state
               SET provider_unlink_receipt_id='terminal-vendor-claim'
               WHERE tenant_id=$1 AND connection_id=$2
                 AND provider_id='approved-managed-connector'""",
            tenant_a, terminal_connection,
        ) == "UPDATE 1"
        restored = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        assert next(
            entry for entry in restored
            if entry["connection_id"] == terminal_connection
        )["provider_revision_claims_correlated"] is True
        assert matching[0]["unverified_deletion_request"] is True
        assessment = assess_retirement_evidence_snapshot(matching[0])[
            "retirement_assessment"
        ]
        assert assessment["cleanup_authorized"] is False
        assert assessment["provider_unlink_independently_verified"] is False
        assert assessment["credential_erasure_independently_verified"] is False
        assert assessment["retention_scope_verified"] is False
        assert "provider_unlink_claim_missing" not in assessment["blocking_reasons"]
        assert "credential_deletion_claim_missing" not in assessment["blocking_reasons"]
        assert "provider_unlink_independent_verification_unavailable" in (
            assessment["blocking_reasons"]
        )
        assert "credential_erasure_independent_verification_unavailable" in (
            assessment["blocking_reasons"]
        )
        assert matching[0]["connection_enabled"] is False
        assert await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_b), user_id=str(user),
        ) == []
        # Sending is not delivery confirmation: outbox 'sent' must remain
        # a retirement blocker until a delivered/read provider receipt.
        assert await raw.execute(
            "UPDATE public.channel_outbox SET status='sent' WHERE "
            "tenant_id=$1 AND delivery_id=$2",
            tenant_a, delivery,
        ) == "UPDATE 1"
        sent_outbound_evidence = await owner_repo.list_owned_personal_retirement_evidence(
            tenant_id=str(tenant_a), user_id=str(user),
        )
        sent_main = next(
            entry for entry in sent_outbound_evidence
            if entry["connection_id"] == connection_id
        )
        assert sent_main["outbound_not_confirmed"] is True
        assert "outbound_delivery_unconfirmed" in (
            assess_retirement_evidence_snapshot(sent_main)
            ["retirement_assessment"]["blocking_reasons"]
        )
        # A disabled, non-retired owned connection may retain consent
        # and a valid provider signature, but cannot create a QR or link.
        # Use real SQL and owner/RLS checks, not a mocked repository result.
        disabled_id = "disabled-" + uuid.uuid4().hex
        await raw.execute(
            """INSERT INTO public.channel_connections
                 (connection_id,tenant_id,installation_id,
                  provider_account_id,credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot','disabled-provider',
                       'vault://disabled-test',false,1)""",
            disabled_id, tenant_a,
        )
        assert await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=disabled_id,
            user_id=str(user),
        )
        assert await owner_repo.acknowledge_personal_pairing_risk(
            tenant_id=str(tenant_a), connection_id=disabled_id,
            user_id=str(user), provider_id="approved-managed-connector",
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )

        def disabled_event(sequence, kind, revision, *, receipt=None):
            return PairingObservation(
                tenant_id=str(tenant_a),
                connection_id=disabled_id,
                provider_id="approved-managed-connector",
                connection_revision=revision,
                sequence=sequence, event=kind,
                observed_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                authenticated=True,
                provider_receipt_id=receipt,
                qr_expires_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=90)
                    if kind is PairingEvent.QR_ISSUED else None
                ),
            )

        with pytest.raises(PairingEvidenceDenied, match="Disabled connection"):
            await owner_repo.commit_personal_pairing_observation(
                observation=disabled_event(1, PairingEvent.QR_ISSUED, 1),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, disabled_id,
        ) == 0

        # Activate through the canonical revision-fenced owner. Then emulate
        # historical direct SQL disabling at the *same* revision to prove
        # that even a correct next-sequence link receipt cannot bypass the
        # row's current enabled flag; normal lifecycle also bumps revision.
        active = await owner_repo.set_connection_enabled(
            tenant_id=str(tenant_a), connection_id=disabled_id,
            expected_revision=1, enabled=True,
        )
        assert active is not None and active.revision == 2
        qr_state = await owner_repo.commit_personal_pairing_observation(
            observation=disabled_event(1, PairingEvent.QR_ISSUED, 2),
            user_id=str(user), provider_vetted_and_enabled=True,
        )
        assert qr_state.phase is PairingPhase.QR_AVAILABLE
        assert await raw.execute(
            """UPDATE public.channel_connections SET enabled=false
               WHERE tenant_id=$1 AND connection_id=$2 AND revision=2""",
            tenant_a, disabled_id,
        ) == "UPDATE 1"
        with pytest.raises(PairingEvidenceDenied, match="Disabled connection"):
            await owner_repo.commit_personal_pairing_observation(
                observation=disabled_event(
                    2, PairingEvent.LINK_CONFIRMED, 2,
                    receipt="not-an-accepted-link",
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        disabled_state = await raw.fetchrow(
            """SELECT phase, sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, disabled_id,
        )
        assert disabled_state["phase"] == "qr_available"
        assert disabled_state["sequence"] == 1

        # Personal owner verification is mutable after initial assignment
        # and after risk consent. It must be checked again under the pairing
        # transaction, rather than trusting the historical owner row.
        owner_status_id = "owner-status-" + uuid.uuid4().hex
        await raw.execute(
            """INSERT INTO public.channel_connections
                 (connection_id,tenant_id,installation_id,
                  provider_account_id,credential_handle,enabled,revision)
               VALUES ($1,$2,'telegram-bot','owner-status-provider',
                       'vault://owner-status-test',true,1)""",
            owner_status_id, tenant_a,
        )
        assert await owner_repo.assign_personal_connection_owner(
            tenant_id=str(tenant_a), connection_id=owner_status_id,
            user_id=str(user),
        )
        assert await owner_repo.acknowledge_personal_pairing_risk(
            tenant_id=str(tenant_a), connection_id=owner_status_id,
            user_id=str(user), provider_id="approved-managed-connector",
            policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        )

        def owner_status_event(sequence, kind, *, receipt=None):
            return PairingObservation(
                tenant_id=str(tenant_a),
                connection_id=owner_status_id,
                provider_id="approved-managed-connector",
                connection_revision=1, sequence=sequence, event=kind,
                observed_at=datetime.now(timezone.utc) - timedelta(seconds=1),
                authenticated=True,
                provider_receipt_id=receipt,
                qr_expires_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=90)
                    if kind is PairingEvent.QR_ISSUED else None
                ),
            )

        # Race against account deactivation: a pending pairing commit must
        # wait for the owner row lock and then observe the *new* status.
        async with raw.transaction():
            await raw.fetchrow(
                """SELECT user_id FROM public.auth_users
                   WHERE user_id=$1 FOR UPDATE""", user,
            )
            delayed_qr = asyncio.create_task(
                owner_repo.commit_personal_pairing_observation(
                    observation=owner_status_event(1, PairingEvent.QR_ISSUED),
                    user_id=str(user), provider_vetted_and_enabled=True,
                )
            )
            await asyncio.sleep(0.1)
            assert not delayed_qr.done()
            assert await raw.execute(
                "UPDATE public.auth_users SET is_active=false WHERE user_id=$1",
                user,
            ) == "UPDATE 1"
        with pytest.raises(PairingEvidenceDenied, match="Inactive or unverified"):
            await delayed_qr
        assert await raw.fetchval(
            """SELECT count(*) FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, owner_status_id,
        ) == 0

        assert await raw.execute(
            """UPDATE public.auth_users
               SET is_active=true, is_verified=false WHERE user_id=$1""",
            user,
        ) == "UPDATE 1"
        with pytest.raises(PairingEvidenceDenied, match="Inactive or unverified"):
            await owner_repo.commit_personal_pairing_observation(
                observation=owner_status_event(1, PairingEvent.QR_ISSUED),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        assert await raw.execute(
            "UPDATE public.auth_users SET is_verified=true WHERE user_id=$1",
            user,
        ) == "UPDATE 1"
        assert (await owner_repo.commit_personal_pairing_observation(
            observation=owner_status_event(1, PairingEvent.QR_ISSUED),
            user_id=str(user), provider_vetted_and_enabled=True,
        )).phase is PairingPhase.QR_AVAILABLE
        assert await raw.execute(
            "UPDATE public.auth_users SET is_active=false WHERE user_id=$1",
            user,
        ) == "UPDATE 1"
        with pytest.raises(PairingEvidenceDenied, match="Inactive or unverified"):
            await owner_repo.commit_personal_pairing_observation(
                observation=owner_status_event(
                    2, PairingEvent.LINK_CONFIRMED,
                    receipt="unaccepted-owner-link",
                ),
                user_id=str(user), provider_vetted_and_enabled=True,
            )
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, owner_status_id,
        ) == 1
        assert await raw.execute(
            "UPDATE public.auth_users SET is_active=true WHERE user_id=$1",
            user,
        ) == "UPDATE 1"
        assert (await owner_repo.commit_personal_pairing_observation(
            observation=owner_status_event(
                2, PairingEvent.LINK_CONFIRMED, receipt="accepted-owner-link",
            ),
            user_id=str(user), provider_vetted_and_enabled=True,
        )).phase is PairingPhase.CONNECTED

        # Inactive owners must still allow authenticated terminal teardown,
        # otherwise deactivation could strand an existing remote session.
        assert await raw.execute(
            "UPDATE public.auth_users SET is_active=false WHERE user_id=$1",
            user,
        ) == "UPDATE 1"
        assert (await owner_repo.commit_personal_pairing_observation(
            observation=owner_status_event(3, PairingEvent.DISCONNECT_REQUESTED),
            user_id=str(user), provider_vetted_and_enabled=False,
        )).phase is PairingPhase.DISCONNECT_PENDING
        assert (await owner_repo.commit_personal_pairing_observation(
            observation=owner_status_event(
                4, PairingEvent.UNLINK_CONFIRMED,
                receipt="unlinked-owner-session-claim",
            ),
            user_id=str(user), provider_vetted_and_enabled=False,
        )).phase is PairingPhase.DISCONNECTED
        assert await raw.fetchval(
            """SELECT sequence FROM public.channel_personal_pairing_state
               WHERE tenant_id=$1 AND connection_id=$2""",
            tenant_a, owner_status_id,
        ) == 4

    finally:
        if engine is not None:
            await engine.dispose()
        await raw.close()
