"""Real NeuroVault -> PostgreSQL -> NeuroRecall persona lifecycle proof."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import delete, select

from ai_karen_engine.core.memory.protocols import VaultContext
from ai_karen_engine.core.memory.retrieval.neuro_recall import NeuroRecall, RecallRequest
from ai_karen_engine.core.memory.types import (
    MemoryEntry, MemoryMetadata, MemoryNamespace, MemoryType,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope
from ai_karen_engine.platform.memory.postgres.ledger_models import (
    ConsentScope, MemoryAssertion, MemoryEvent,
)
from ai_karen_engine.platform.memory.postgres.recall_retriever import PostgresRecallRetriever
from ai_karen_engine.platform.memory.postgres.vault import PostgresNeuroVault

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("KAREN_TEST_POSTGRES_MEMORY") != "1",
        reason="requires disposable PostgreSQL memory database",
    ),
]


async def test_vault_to_recall_persona_filter_and_revocation():
    tenant, user = uuid.uuid4(), uuid.uuid4()
    consent_id = uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(3)]
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-proof", is_granted=True,
            ))

        vault = PostgresNeuroVault()
        context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            actor_id=str(user), policy_context={"memory_write_authorized": True},
        )
        # A persona label is not a write grant. Verify real NeuroVault
        # denies an otherwise well-scoped entry with no policy capability.
        from ai_karen_engine.platform.memory.postgres.vault import NeuroVaultAuthorizationError
        denied_entry = MemoryEntry(
            id=str(uuid.uuid4()), content="Unauthorized persona write",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user),
                source="chat_user",
                custom={"persona_id": "assistant", "consent_scope": "persona-proof"},
            ),
        )
        denied_context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            policy_context={},
        )
        with pytest.raises(NeuroVaultAuthorizationError):
            await vault.persist(denied_entry, context=denied_context)

        for memory_id, persona in zip(ids, ("assistant", "expert", None)):
            custom = {"consent_scope": "persona-proof"}
            if persona:
                custom["persona_id"] = persona
            entry = MemoryEntry(
                id=str(memory_id), content="Persona durable lifecycle proof",
                memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
                metadata=MemoryMetadata(
                    tenant_id=str(tenant), user_id=str(user),
                    source="chat_user", custom=custom,
                ),
            )
            receipt = await vault.persist(entry, context=context)
            assert receipt.persisted

        recall = NeuroRecall(retriever=PostgresRecallRetriever())
        base = dict(query="Persona durable lifecycle proof",
                    tenant_id=str(tenant), user_id=str(user), top_k=10)
        unfiltered = await recall.recall(RecallRequest(**base))
        assert {str(item.id) for item in unfiltered.memories} == {str(i) for i in ids}

        assistant = await recall.recall(RecallRequest(
            **base, metadata={"persona_filter": "assistant"},
        ))
        assert {str(item.id) for item in assistant.memories} == {str(ids[0]), str(ids[2])}

        expert = await recall.recall(RecallRequest(
            **base, metadata={"persona_filter": "expert"},
        ))
        assert {str(item.id) for item in expert.memories} == {str(ids[1]), str(ids[2])}

        other_tenant = await recall.recall(RecallRequest(
            query=base["query"], tenant_id=str(uuid.uuid4()),
            user_id=str(user), top_k=10,
        ))
        assert not other_tenant.memories

        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(
                select(ConsentScope).where(ConsentScope.scope_id == consent_id)
            )).scalar_one()
            scope.is_granted = False
        revoked = await recall.recall(RecallRequest(**base))
        assert not revoked.memories
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event_ids = (await session.execute(
                select(MemoryAssertion.event_id).where(
                    MemoryAssertion.assertion_id.in_(ids)
                )
            )).scalars().all()
            await session.execute(delete(MemoryAssertion).where(MemoryAssertion.assertion_id.in_(ids)))
            if event_ids:
                await session.execute(delete(MemoryEvent).where(MemoryEvent.event_id.in_(event_ids)))
            await session.execute(delete(ConsentScope).where(ConsentScope.scope_id == consent_id))


async def test_admitted_migration_replay_identity_is_idempotent_in_real_vault():
    """Exercise real ledger duplicate handling without importing legacy rows."""
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        LegacyMigrationWriteAuthority, admit_legacy_migration,
        derive_legacy_migration_replay_identity,
    )
    from ai_karen_engine.core.memory.legacy_persona_preflight import LegacyMigrationPreflight

    tenant, user = uuid.uuid4(), uuid.uuid4()
    consent_id = uuid.uuid4()
    admission = admit_legacy_migration(
        LegacyMigrationPreflight(True, ()),
        LegacyMigrationWriteAuthority(
            tenant_id=str(tenant), user_id=str(user),
            authorized_tenant_id=str(tenant), authorized_user_id=str(user),
            capability="memory.write", policy_decision_id=str(uuid.uuid4()),
            explicitly_granted=True,
        ),
    )
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_recovery import (
        LegacyReplayRecoveryDecision,
    )
    source_id = str(uuid.uuid4())
    write_authority = LegacyMigrationWriteAuthority(
        tenant_id=str(tenant), user_id=str(user),
        authorized_tenant_id=str(tenant), authorized_user_id=str(user),
        capability="memory.write", policy_decision_id=str(uuid.uuid4()),
        explicitly_granted=True,
    )
    replay = prepare_legacy_migration_retry(
        preflight=LegacyMigrationPreflight(True, ()),
        authority=write_authority,
        recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
        source_record_id=source_id,
    )
    assert replay == derive_legacy_migration_replay_identity(
        admission=admission, tenant_id=str(tenant),
        user_id=str(user), source_record_id=source_id,
    )
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-replay-proof", is_granted=True,
            ))
        entry = MemoryEntry(
            id=replay.memory_id, content="Synthetic idempotent migration proof",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "persona-replay-proof"},
            ),
        )
        context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=replay.request_id, correlation_id=str(uuid.uuid4()),
            actor_id=str(user), policy_context={"memory_write_authorized": True},
        )
        vault = PostgresNeuroVault()
        first = await vault.persist(entry, context=context)
        second = await vault.persist(entry, context=context)
        assert first.persisted and second.persisted
        assert first.memory_id == second.memory_id
        from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
            lookup_legacy_replay_receipt,
        )
        from ai_karen_engine.core.memory.legacy_persona_recovery import (
            reconcile_legacy_replay,
        )
        evidence = await lookup_legacy_replay_receipt(
            tenant_id=str(tenant), user_id=str(user),
            expected_memory_id=replay.memory_id, expected_request_id=replay.request_id,
        )
        decision = reconcile_legacy_replay(evidence)
        assert decision.already_persisted and not decision.safe_to_retry
        mismatch = await lookup_legacy_replay_receipt(
            tenant_id=str(tenant), user_id=str(user),
            expected_memory_id=replay.memory_id, expected_request_id=str(uuid.uuid4()),
        )
        assert not reconcile_legacy_replay(mismatch).already_persisted
        unrelated = await lookup_legacy_replay_receipt(
            tenant_id=str(uuid.uuid4()), user_id=str(user),
            expected_memory_id=replay.memory_id, expected_request_id=replay.request_id,
        )
        assert not reconcile_legacy_replay(unrelated).already_persisted
        # Consent is checked before the idempotency lookup. A retry after
        # revocation must not yield a successful cached write receipt.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            scope = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))).scalar_one()
            scope.is_granted = False
        from ai_karen_engine.platform.memory.postgres.vault import NeuroVaultAuthorizationError
        with pytest.raises(NeuroVaultAuthorizationError):
            await vault.persist(entry, context=context)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            events = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.tenant_id == tenant, MemoryEvent.user_id == user,
            ))).scalars().all()
            assert len(events) == 1
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            event_ids = (await session.execute(
                select(MemoryAssertion.event_id).where(
                    MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id)
                )
            )).scalars().all()
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id)
            ))
            if event_ids:
                await session.execute(delete(MemoryEvent).where(
                    MemoryEvent.event_id.in_(event_ids)
                ))
            await session.execute(delete(ConsentScope).where(ConsentScope.scope_id == consent_id))


async def test_historical_migration_requires_explicit_current_consent():
    from ai_karen_engine.platform.memory.postgres.legacy_persona_consent import (
        verify_legacy_migration_consent,
    )
    tenant, user, scope_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    kwargs = dict(tenant_id=str(tenant), user_id=str(user),
                  consent_scope="persona-memory-migration")
    try:
        assert not await verify_legacy_migration_consent(**kwargs)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name="persona-memory-migration", is_granted=True,
            ))
        assert await verify_legacy_migration_consent(**kwargs)
        assert not await verify_legacy_migration_consent(
            **{**kwargs, "tenant_id": str(uuid.uuid4())}
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            grant = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id
            ))).scalar_one()
            grant.is_granted = False
        assert not await verify_legacy_migration_consent(**kwargs)
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id
            ))


async def test_consented_retry_preparation_uses_current_postgres_grant():
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        LegacyMigrationWriteAuthority, prepare_consented_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_preflight import LegacyMigrationPreflight
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision

    tenant, user, scope_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    authority = LegacyMigrationWriteAuthority(
        tenant_id=str(tenant), user_id=str(user),
        authorized_tenant_id=str(tenant), authorized_user_id=str(user),
        capability="memory.write", policy_decision_id=str(uuid.uuid4()),
        explicitly_granted=True,
    )
    options = dict(
        preflight=LegacyMigrationPreflight(True, ()),
        authority=authority,
        recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
        source_record_id=str(uuid.uuid4()),
    )
    with pytest.raises(ValueError, match="explicit historical migration consent"):
        await prepare_consented_legacy_migration_retry(**options)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=scope_id, tenant_id=tenant, user_id=user,
                scope_name="persona-memory-migration", is_granted=True,
            ))
        replay = await prepare_consented_legacy_migration_retry(**options)
        assert replay.memory_id and replay.request_id
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            grant = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == scope_id
            ))).scalar_one()
            grant.is_granted = False
        with pytest.raises(ValueError, match="explicit historical migration consent"):
            await prepare_consented_legacy_migration_retry(**options)
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == scope_id
            ))


async def test_runtime_policy_and_explicit_consent_both_required_for_retry():
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_runtime_authorized_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_preflight import LegacyMigrationPreflight
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )

    tenant, user, consent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    policy = RuntimePolicyEnforcer()
    request = PolicyEvaluationRequest(
        tenant_id=str(tenant), user_id=str(user),
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    options = dict(
        authenticated_request=request, runtime_policy=policy,
        preflight=LegacyMigrationPreflight(True, ()),
        recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
        source_record_id=str(uuid.uuid4()),
    )
    with pytest.raises(ValueError, match="explicit historical migration consent"):
        await prepare_runtime_authorized_legacy_migration_retry(**options)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-memory-migration", is_granted=True,
            ))
        replay = await prepare_runtime_authorized_legacy_migration_retry(**options)
        assert replay.memory_id and replay.request_id
        denied = PolicyEvaluationRequest(
            tenant_id=str(tenant), user_id=str(user),
            action="legacy_persona_memory_migration",
            permissions=[], requested_capabilities=["memory.write"],
        )
        with pytest.raises(ValueError, match="current migration authorization"):
            await prepare_runtime_authorized_legacy_migration_retry(
                **{**options, "authenticated_request": denied}
            )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            grant = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))).scalar_one()
            grant.is_granted = False
        with pytest.raises(ValueError, match="explicit historical migration consent"):
            await prepare_runtime_authorized_legacy_migration_retry(**options)
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))


async def test_legacy_source_presence_is_scoped_in_real_postgres():
    """Disposable synthetic source only; no historical content is imported."""
    from sqlalchemy import text
    from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
        verify_legacy_persona_source,
    )

    tenant, user = str(uuid.uuid4()), str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    try:
        async with async_transaction_scope(tenant_id=tenant) as session:
            await session.execute(text(
                "INSERT INTO public.persona_memory_entries "
                "(id, tenant_id, user_id, content) "
                "VALUES (:id, :tenant, :user, :content)"
            ), {"id": source_id, "tenant": tenant, "user": user,
                "content": "Synthetic source proof"})
        assert await verify_legacy_persona_source(
            tenant_id=tenant, user_id=user, source_record_id=source_id,
        )
        assert not await verify_legacy_persona_source(
            tenant_id=str(uuid.uuid4()), user_id=user, source_record_id=source_id,
        )
        assert not await verify_legacy_persona_source(
            tenant_id=tenant, user_id=str(uuid.uuid4()), source_record_id=source_id,
        )
        assert not await verify_legacy_persona_source(
            tenant_id=tenant, user_id=user, source_record_id=str(uuid.uuid4()),
        )
    finally:
        async with async_transaction_scope(tenant_id=tenant) as session:
            await session.execute(text(
                "DELETE FROM public.persona_memory_entries "
                "WHERE id = :id AND tenant_id = :tenant AND user_id = :user"
            ), {"id": source_id, "tenant": tenant, "user": user})


async def test_source_consent_and_runtime_policy_joint_preparation():
    """Synthetic legacy row requires all three authorities, with no import."""
    from sqlalchemy import text
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_source_verified_legacy_migration_retry,
    )
    from ai_karen_engine.core.memory.legacy_persona_preflight import LegacyMigrationPreflight
    from ai_karen_engine.core.memory.legacy_persona_recovery import LegacyReplayRecoveryDecision
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest, RuntimePolicyEnforcer,
    )

    tenant, user, source_id, consent_id = (uuid.uuid4() for _ in range(4))
    request = PolicyEvaluationRequest(
        tenant_id=str(tenant), user_id=str(user),
        action="legacy_persona_memory_migration",
        permissions=["memory.write"], requested_capabilities=["memory.write"],
    )
    options = dict(
        authenticated_request=request,
        runtime_policy=RuntimePolicyEnforcer(),
        preflight=LegacyMigrationPreflight(True, ()),
        recovery=LegacyReplayRecoveryDecision(False, True, "no_prior_receipt"),
        source_record_id=str(source_id),
    )
    try:
        with pytest.raises(ValueError, match="matching nonempty legacy source"):
            await prepare_source_verified_legacy_migration_retry(**options)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "INSERT INTO public.persona_memory_entries "
                "(id, tenant_id, user_id, content) "
                "VALUES (:id, :tenant, :user, :content)"
            ), {"id": str(source_id), "tenant": str(tenant),
                "user": str(user), "content": "Synthetic source for admission proof"})
        with pytest.raises(ValueError, match="explicit historical migration consent"):
            await prepare_source_verified_legacy_migration_retry(**options)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-memory-migration", is_granted=True,
            ))
        prepared = await prepare_source_verified_legacy_migration_retry(**options)
        assert prepared.memory_id and prepared.request_id
        untrusted = PolicyEvaluationRequest(
            tenant_id=str(tenant), user_id=str(user),
            action="legacy_persona_memory_migration",
            requested_capabilities=["memory.write"], permissions=[],
        )
        with pytest.raises(ValueError, match="current migration authorization"):
            await prepare_source_verified_legacy_migration_retry(
                **{**options, "authenticated_request": untrusted}
            )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "DELETE FROM public.persona_memory_entries "
                "WHERE id = :id AND tenant_id = :tenant AND user_id = :user"
            ), {"id": str(source_id), "tenant": str(tenant), "user": str(user)})
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))


async def test_retention_source_metadata_and_policy_from_disposable_postgres():
    """Use the existing canonical ledger schema and a synthetic source row."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
        read_legacy_persona_source_retention_metadata,
    )
    from ai_karen_engine.platform.memory.postgres.legacy_persona_retention import (
        verify_legacy_migration_retention,
    )
    from ai_karen_engine.platform.memory.postgres.ledger_models import RetentionPolicy

    tenant, user, source, policy_id = (uuid.uuid4() for _ in range(4))
    created = datetime.now(timezone.utc) - timedelta(days=2)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "INSERT INTO public.persona_memory_entries "
                "(id, tenant_id, user_id, content, memory_type, created_at) "
                "VALUES (:id, :tenant, :user, :content, :kind, :created)"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic retention record", "kind": "semantic",
                "created": created.replace(tzinfo=None)})
            session.add(RetentionPolicy(
                policy_id=policy_id, tenant_id=tenant,
                memory_class="semantic", ttl_days=30,
            ))
        metadata = await read_legacy_persona_source_retention_metadata(
            tenant_id=str(tenant), user_id=str(user),
            source_record_id=str(source),
        )
        assert metadata is not None
        assert metadata[1] == "semantic"
        assert await verify_legacy_migration_retention(
            tenant_id=str(tenant), created_at=metadata[0], memory_class=metadata[1],
        )
        assert await read_legacy_persona_source_retention_metadata(
            tenant_id=str(uuid.uuid4()), user_id=str(user),
            source_record_id=str(source),
        ) is None
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            policy = (await session.execute(select(RetentionPolicy).where(
                RetentionPolicy.policy_id == policy_id
            ))).scalar_one()
            policy.ttl_days = 1
        assert not await verify_legacy_migration_retention(
            tenant_id=str(tenant), created_at=metadata[0], memory_class=metadata[1],
        )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "DELETE FROM public.persona_memory_entries "
                "WHERE id = :id AND tenant_id = :tenant AND user_id = :user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
            await session.execute(delete(RetentionPolicy).where(
                RetentionPolicy.policy_id == policy_id
            ))


async def test_canonical_identity_requires_active_verified_same_tenant_user():
    """Disposable auth fixture matches canonical baseline columns, no legacy import."""
    from sqlalchemy import text
    from ai_karen_engine.platform.memory.postgres.legacy_persona_identity import (
        verify_legacy_persona_identity,
    )

    assert os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") == "1"
    tenant, user = uuid.uuid4(), uuid.uuid4()
    # The memory-only disposable schema lacks the unrelated application auth
    # tables; create the minimal canonical columns strictly in disposable CI.
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS public.auth_users ("
            "user_id UUID PRIMARY KEY, tenant_id TEXT, "
            "is_active BOOLEAN DEFAULT TRUE, is_verified BOOLEAN DEFAULT FALSE)"
        ))
        await session.execute(text(
            "INSERT INTO public.auth_users "
            "(user_id, tenant_id, is_active, is_verified) "
            "VALUES (:user_id, :tenant_id, TRUE, TRUE)"
        ), {"user_id": str(user), "tenant_id": str(tenant)})
    try:
        assert await verify_legacy_persona_identity(
            tenant_id=str(tenant), user_id=str(user),
        )
        assert not await verify_legacy_persona_identity(
            tenant_id=str(uuid.uuid4()), user_id=str(user),
        )
        assert not await verify_legacy_persona_identity(
            tenant_id=str(tenant), user_id=str(uuid.uuid4()),
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.auth_users SET is_active=FALSE "
                "WHERE user_id=:user AND tenant_id=:tenant"
            ), {"user": str(user), "tenant": str(tenant)})
        assert not await verify_legacy_persona_identity(
            tenant_id=str(tenant), user_id=str(user),
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.auth_users SET is_active=TRUE, is_verified=FALSE "
                "WHERE user_id=:user AND tenant_id=:tenant"
            ), {"user": str(user), "tenant": str(tenant)})
        assert not await verify_legacy_persona_identity(
            tenant_id=str(tenant), user_id=str(user),
        )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "DELETE FROM public.auth_users "
                "WHERE user_id=:user AND tenant_id=:tenant"
            ), {"user": str(user), "tenant": str(tenant)})


async def test_governed_migration_assembly_disposable_postgres_recovery():
    """Real read-only assembly, revocation and replay proof; never import source."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from ai_karen_engine.core.memory.legacy_persona_admission import (
        prepare_governed_legacy_migration_retry,
    )
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer
    from ai_karen_engine.platform.memory.postgres.ledger_models import RetentionPolicy

    assert os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") == "1"
    tenant, user, source, consent_id, retention_id = (uuid.uuid4() for _ in range(5))
    context = ChatExecutionContext(
        tenant_id=str(tenant), user_id=str(user), session_id="kp03-postgres-proof",
        request_id=str(uuid.uuid4()), permissions=["memory.write"],
    )
    base = dict(context=context, runtime_policy=RuntimePolicyEnforcer(),
                source_record_id=str(source))
    created = datetime.now(timezone.utc) - timedelta(days=1)
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "CREATE TABLE IF NOT EXISTS public.auth_users ("
                "user_id UUID PRIMARY KEY, tenant_id TEXT, "
                "is_active BOOLEAN DEFAULT TRUE, is_verified BOOLEAN DEFAULT FALSE)"
            ))
            await session.execute(text(
                "INSERT INTO public.auth_users (user_id, tenant_id, is_active, is_verified) "
                "VALUES (:user, :tenant, TRUE, TRUE)"
            ), {"user": str(user), "tenant": str(tenant)})
            await session.execute(text(
                "INSERT INTO public.persona_memory_entries "
                "(id, tenant_id, user_id, content, memory_type, created_at) "
                "VALUES (:id, :tenant, :user, :content, :kind, :created)"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic read-only assembly proof",
                "kind": "semantic", "created": created.replace(tzinfo=None)})
            session.add(RetentionPolicy(
                policy_id=retention_id, tenant_id=tenant,
                memory_class="semantic", ttl_days=30,
            ))
            session.add(ConsentScope(
                scope_id=consent_id, tenant_id=tenant, user_id=user,
                scope_name="persona-memory-migration", is_granted=True,
            ))
        # Canonical source classification must remain valid independently of
        # caller-provided source IDs or retention policy names.
        from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
            read_legacy_persona_source_retention_metadata,
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET memory_type=' ' "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
        assert await read_legacy_persona_source_retention_metadata(
            tenant_id=str(tenant), user_id=str(user), source_record_id=str(source),
        ) is None
        with pytest.raises(ValueError, match="verified historical retention metadata required"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET memory_type='semantic' "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
        # A source that becomes empty after a previous eligibility check
        # cannot be admitted on the next attempt.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET content='   ' "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
        with pytest.raises(ValueError, match="verified historical retention metadata required"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET content=:content "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic read-only assembly proof"})
        from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
            lock_legacy_migration_evidence,
        )
        locked_evidence = await lock_legacy_migration_evidence(
            tenant_id=str(tenant), user_id=str(user), source_record_id=str(source),
        )
        assert locked_evidence is not None
        assert locked_evidence[1] == "semantic"
        # Caller-owned transaction retains the evidence locks until exit.
        from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
            verify_locked_legacy_migration_evidence,
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            inside = await verify_locked_legacy_migration_evidence(
                session=session, tenant_id=str(tenant), user_id=str(user),
                source_record_id=str(source),
            )
            assert inside == locked_evidence
            assert await verify_locked_legacy_migration_evidence(
                session=session, tenant_id=str(uuid.uuid4()), user_id=str(user),
                source_record_id=str(source),
            ) is None
        assert await lock_legacy_migration_evidence(
            tenant_id=str(uuid.uuid4()), user_id=str(user),
            source_record_id=str(source),
        ) is None
        replay = await prepare_governed_legacy_migration_retry(**base)
        # A prepared replay identity is not valid after source deletion.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "DELETE FROM public.persona_memory_entries "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
        with pytest.raises(ValueError, match="verified historical retention metadata required"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "INSERT INTO public.persona_memory_entries "
                "(id, tenant_id, user_id, content, memory_type, created_at) "
                "VALUES (:id, :tenant, :user, :content, :kind, :created)"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic read-only assembly proof",
                "kind": "semantic", "created": created.replace(tzinfo=None)})
        # Exercise authenticated ingress with an actual signed access JWT,
        # the existing middleware decoder, and real PostgreSQL evidence.
        import jwt
        from starlette.requests import Request
        from ai_karen_engine.auth import auth_middleware
        from ai_karen_engine.core.security.auth_config import auth_config
        from ai_karen_engine.core.memory.legacy_persona_admission import (
            prepare_authenticated_http_legacy_migration_retry,
        )

        class HealthyRevocationStore:
            def ping(self):
                return True

            def exists(self, key):
                return 0

        middleware = auth_middleware.SecureAuthMiddleware.__new__(
            auth_middleware.SecureAuthMiddleware
        )
        middleware.jwt_secret = "kp03-disposable-postgres-only"
        middleware.jwt_algorithm = "HS256"
        middleware.redis_client = HealthyRevocationStore()
        claims = {
            "sub": str(user), "tenant_id": str(tenant), "token_id": "kp03-live",
            "roles": ["admin"], "permissions": ["memory.write"],
            "iss": "ai-karen", "aud": "ai-karen-users",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        signed = jwt.encode(claims, middleware.jwt_secret, algorithm="HS256")
        http_request = Request({
            "type": "http", "method": "POST", "path": "/internal",
            "headers": [(b"authorization", ("Bearer " + signed).encode())],
            "query_string": b"",
        })
        from pytest import MonkeyPatch
        with MonkeyPatch.context() as patch:
            patch.setattr(auth_config, "should_bypass_auth", lambda: False)
            patch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
            authenticated_replay = await prepare_authenticated_http_legacy_migration_retry(
                request=http_request, request_id=str(uuid.uuid4()),
                correlation_id=str(uuid.uuid4()), source_record_id=str(source),
                runtime_policy=RuntimePolicyEnforcer(),
            )
            assert authenticated_replay == replay
            from ai_karen_engine.core.memory.legacy_persona_admission import (
                inspect_authenticated_legacy_migration_transaction,
            )
            integrated_replay, integrated_receipt = (
                await inspect_authenticated_legacy_migration_transaction(
                    request=http_request, request_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4()),
                    source_record_id=str(source),
                    runtime_policy=RuntimePolicyEnforcer(),
                )
            )
            assert integrated_replay == replay
            assert not integrated_receipt.persisted
            # RuntimePolicy may be revoked after initial admission but
            # before the locked transaction exits. Final re-evaluation
            # must deny without producing a migration receipt.
            import dataclasses
            from ai_karen_engine.core.memory import legacy_persona_admission as admission_module
            original_evaluate = admission_module.evaluate_migration_write_authority
            decision_count = 0

            async def revoking_decision(**kwargs):
                nonlocal decision_count
                decision_count += 1
                first = await original_evaluate(**kwargs)
                return (
                    dataclasses.replace(first, explicitly_granted=False)
                    if decision_count == 2 else first
                )

            with MonkeyPatch.context() as revoke_patch:
                revoke_patch.setattr(
                    admission_module, "evaluate_migration_write_authority",
                    revoking_decision,
                )
                with pytest.raises(PermissionError, match="revoked during inspection"):
                    await inspect_authenticated_legacy_migration_transaction(
                        request=http_request, request_id=str(uuid.uuid4()),
                        correlation_id=str(uuid.uuid4()), source_record_id=str(source),
                        runtime_policy=RuntimePolicyEnforcer(),
                    )
            assert decision_count == 2
            # A correctly signed token for another tenant cannot inspect
            # the source or receive its replay evidence.
            foreign_claims = {**claims, "tenant_id": str(uuid.uuid4())}
            foreign_token = jwt.encode(
                foreign_claims, middleware.jwt_secret, algorithm="HS256",
            )
            foreign_request = Request({
                "type": "http", "method": "POST", "path": "/internal",
                "headers": [(b"authorization", ("Bearer " + foreign_token).encode())],
                "query_string": b"",
            })
            with pytest.raises(PermissionError, match="canonical migration evidence"):
                await inspect_authenticated_legacy_migration_transaction(
                    request=foreign_request, request_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4()),
                    source_record_id=str(source),
                    runtime_policy=RuntimePolicyEnforcer(),
                )
            # A forged signature must not reach the otherwise eligible source.
            forged = jwt.encode(claims, "wrong-signing-key", algorithm="HS256")
            forged_request = Request({
                "type": "http", "method": "POST", "path": "/internal",
                "headers": [(b"authorization", ("Bearer " + forged).encode())],
                "query_string": b"",
            })
            with pytest.raises(PermissionError):
                await prepare_authenticated_http_legacy_migration_retry(
                    request=forged_request, request_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4()), source_record_id=str(source),
                    runtime_policy=RuntimePolicyEnforcer(),
                )
        assert replay == await prepare_governed_legacy_migration_retry(**base)
        # Historical writes are disabled even after successful preflight,
        # explicit consent, and a caller-provided capability flag.
        blocked_migration_entry = MemoryEntry(
            id=str(uuid.uuid4()), content="Forbidden historical write",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "persona-memory-migration"},
            ),
        )
        from ai_karen_engine.platform.memory.postgres.vault import NeuroVaultAuthorizationError
        with pytest.raises(NeuroVaultAuthorizationError, match="historical migration persistence is disabled"):
            await PostgresNeuroVault().persist(
                blocked_migration_entry, context=VaultContext(
                    tenant_id=str(tenant), user_id=str(user),
                    request_id=replay.request_id, correlation_id=str(uuid.uuid4()),
                    actor_id=str(user),
                    policy_context={"memory_write_authorized": True},
                ),
            )
        synthetic_entry = MemoryEntry(
            id=replay.memory_id, content="Synthetic canonical replay receipt",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "memory.write"},
            ),
        )
        vault_context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=replay.request_id, correlation_id=str(uuid.uuid4()),
            actor_id=str(user), policy_context={"memory_write_authorized": True},
        )
        assert (await PostgresNeuroVault().persist(
            synthetic_entry, context=vault_context,
        )).persisted
        # Same idempotency key with changed content is a collision, not a
        # successful replay. Vault must never claim it persisted the new text.
        changed_entry = MemoryEntry(
            id=replay.memory_id, content="Conflicting canonical replay content",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "memory.write"},
            ),
        )
        with pytest.raises(NeuroVaultAuthorizationError, match="idempotency collision"):
            await PostgresNeuroVault().persist(
                changed_entry, context=vault_context,
            )
        # An identical request remains a legitimate idempotent replay.
        identical_retry = await PostgresNeuroVault().persist(
            synthetic_entry, context=vault_context,
        )
        assert identical_retry.persisted
        assert identical_retry.memory_id == replay.memory_id
        assert identical_retry.metadata["idempotent_replay"] is True
        # Even identical content must not replay under a forged or stale
        # canonical event consent provenance.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            original_event = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.idempotency_key == PostgresNeuroVault._idempotency_key(
                    synthetic_entry, vault_context,
                ),
            ))).scalar_one()
            original_payload = dict(original_event.payload)
            original_event.payload = {
                **original_payload,
                "vault": {**original_payload["vault"], "consent_scope": "different-scope"},
            }
        try:
            with pytest.raises(NeuroVaultAuthorizationError, match="idempotency collision"):
                await PostgresNeuroVault().persist(synthetic_entry, context=vault_context)
        finally:
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                original_event = (await session.execute(select(MemoryEvent).where(
                    MemoryEvent.idempotency_key == PostgresNeuroVault._idempotency_key(
                        synthetic_entry, vault_context,
                    ),
                ))).scalar_one()
                original_event.payload = original_payload
        import asyncio
        # Competing canonical NeuroVault retries must resolve through the
        # same durable assertion: identical content replays successfully,
        # conflicting content fails closed without changing stored content.
        async def retry_identical():
            return await PostgresNeuroVault().persist(
                synthetic_entry, context=vault_context,
            )

        async def retry_conflicting():
            with pytest.raises(
                NeuroVaultAuthorizationError, match="idempotency collision",
            ):
                await PostgresNeuroVault().persist(
                    changed_entry, context=vault_context,
                )

        concurrent_retry, _ = await asyncio.gather(
            retry_identical(), retry_conflicting(),
        )
        assert concurrent_retry.persisted
        assert concurrent_retry.memory_id == replay.memory_id
        assert concurrent_retry.metadata["idempotent_replay"] is True
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            stored = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id),
                MemoryAssertion.tenant_id == tenant,
                MemoryAssertion.user_id == user,
            ))).scalar_one()
            assert stored.content == synthetic_entry.content
        # Caller-owned vault writes stage both ledger rows but never commit.
        # The canonical transaction manager owns rollback on failure.
        staged_id = str(uuid.uuid4())
        staged_entry = MemoryEntry(
            id=staged_id, content="Synthetic transaction staging proof",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "memory.write"},
            ),
        )
        with pytest.raises(RuntimeError, match="caller rollback"):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                staged = await PostgresNeuroVault().persist_in_transaction(
                    staged_entry, context=VaultContext(
                        tenant_id=str(tenant), user_id=str(user),
                        request_id=str(uuid.uuid4()),
                        correlation_id=str(uuid.uuid4()), actor_id=str(user),
                        policy_context={"memory_write_authorized": True},
                    ), session=session,
                )
                assert not staged.persisted
                assert staged.metadata["pending_commit"] is True
                assert (await session.execute(select(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == uuid.UUID(staged_id),
                ))).scalar_one_or_none() is not None
                raise RuntimeError("caller rollback")
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(staged_id),
            ))).scalar_one_or_none() is None
        # A successful caller-owned commit becomes visible only after the
        # canonical transaction manager exits cleanly.
        committed_id = str(uuid.uuid4())
        committed_entry = MemoryEntry(
            id=committed_id, content="Synthetic committed transaction proof",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "memory.write"},
            ),
        )
        committed_context = VaultContext(
            tenant_id=str(tenant), user_id=str(user),
            request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
            actor_id=str(user), policy_context={"memory_write_authorized": True},
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            pending = await PostgresNeuroVault().persist_in_transaction(
                committed_entry, context=committed_context, session=session,
            )
            assert not pending.persisted
            assert pending.metadata["pending_commit"] is True
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            committed_assertion = (await session.execute(
                select(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == uuid.UUID(committed_id),
                )
            )).scalar_one()
            assert committed_assertion.content == committed_entry.content
            # A replay collision within a caller-owned transaction propagates
            # and must not commit a second canonical event or assertion.
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await PostgresNeuroVault().persist_in_transaction(
                    committed_entry, context=committed_context, session=session,
                )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert len((await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(committed_id),
            ))).scalars().all()) == 1
            await session.execute(
                text("DELETE FROM public.memory_event WHERE event_id=:event"),
                {"event": str(committed_assertion.event_id)},
            )
        # The same assertion with different operation provenance must never
        # be accepted as a completed migration or as a safe retry.
        from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
            lookup_legacy_replay_receipt,
        )
        from ai_karen_engine.core.memory.legacy_persona_recovery import (
            reconcile_legacy_replay,
        )
        from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
            lookup_locked_legacy_replay_receipt,
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            same_transaction_receipt = await lookup_locked_legacy_replay_receipt(
                session=session, tenant_id=str(tenant), user_id=str(user),
                expected_memory_id=replay.memory_id,
                expected_request_id=replay.request_id,
            )
            # A ledger row is not proof of legitimate migration provenance.
            assert not same_transaction_receipt.persisted
            assert same_transaction_receipt.persisted_memory_id == replay.memory_id
            assert same_transaction_receipt == await lookup_legacy_replay_receipt(
                tenant_id=str(tenant), user_id=str(user),
                expected_memory_id=replay.memory_id,
                expected_request_id=replay.request_id,
            )
        from ai_karen_engine.platform.memory.postgres.legacy_persona_source import (
            inspect_locked_legacy_migration_preparation,
        )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            inspected = await inspect_locked_legacy_migration_preparation(
                session=session, tenant_id=str(tenant), user_id=str(user),
                source_record_id=str(source),
                expected_memory_id=replay.memory_id,
                expected_request_id=replay.request_id,
            )
            assert inspected is not None
            assert inspected[0][1] == "semantic"
            assert inspected[1].persisted
            assert await inspect_locked_legacy_migration_preparation(
                session=session, tenant_id=str(uuid.uuid4()), user_id=str(user),
                source_record_id=str(source),
                expected_memory_id=replay.memory_id,
                expected_request_id=replay.request_id,
            ) is None
        mismatched = await lookup_legacy_replay_receipt(
            tenant_id=str(tenant), user_id=str(user),
            expected_memory_id=replay.memory_id,
            expected_request_id=str(uuid.uuid4()),
        )
        mismatch_decision = reconcile_legacy_replay(mismatched)
        assert not mismatch_decision.already_persisted
        assert not mismatch_decision.safe_to_retry
        assert mismatch_decision.reason == "receipt_not_persisted"
        # The authenticated unified transaction must also reject a completed
        # canonical replay, not only the older preparation entrypoint.
        from pytest import MonkeyPatch
        with MonkeyPatch.context() as patch:
            patch.setattr(auth_config, "should_bypass_auth", lambda: False)
            patch.setattr(auth_middleware, "get_auth_middleware", lambda: middleware)
            with pytest.raises(PermissionError, match="replay not eligible"):
                await inspect_authenticated_legacy_migration_transaction(
                    request=http_request, request_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4()),
                    source_record_id=str(source),
                    runtime_policy=RuntimePolicyEnforcer(),
                )
        with pytest.raises(ValueError, match="migration recovery does not allow retry"):
            await prepare_governed_legacy_migration_retry(**base)
        with pytest.raises(ValueError, match="migration recovery does not allow retry"):
            await prepare_governed_legacy_migration_retry(
                **{**base, "runtime_policy": RuntimePolicyEnforcer()}
            )
        # Verify the ledger's parent event and child assertion disappear
        # together on a failed transaction, not just an unreferenced event.
        rolled_back_pair_event, rolled_back_pair_assertion = uuid.uuid4(), uuid.uuid4()
        with pytest.raises(RuntimeError, match="rollback parent and child"):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=rolled_back_pair_event, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", consent_state="granted",
                    payload={"vault": {"request_id": str(uuid.uuid4())}},
                ))
                await session.flush()
                session.add(MemoryAssertion(
                    assertion_id=rolled_back_pair_assertion,
                    event_id=rolled_back_pair_event, tenant_id=tenant, user_id=user,
                    content="Transaction rollback proof", confidence=1.0,
                    scope="user", sensitivity_class="normal",
                    consent_state="granted",
                ))
                await session.flush()
                raise RuntimeError("rollback parent and child")
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == rolled_back_pair_event
            ))).scalar_one_or_none() is None
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == rolled_back_pair_assertion
            ))).scalar_one_or_none() is None
        # The same PostgreSQL lock discipline must serialize consent and
        # retention mutations. These are DB primitive proofs only; no
        # historical migration writer is enabled.
        import asyncio
        for model, row_id, field, revoked, restored, error in (
            (ConsentScope, consent_id, "is_granted", False, True,
             "explicit historical migration consent"),
            (RetentionPolicy, retention_id, "ttl_days", 0, 30,
             "historical memory retention not authorized"),
        ):
            locked = asyncio.Event()
            release = asyncio.Event()
            changed = asyncio.Event()

            async def hold_policy_row():
                async with async_transaction_scope(tenant_id=str(tenant)) as session:
                    row = (await session.execute(
                        select(model).where(
                            (model.scope_id if model is ConsentScope else model.policy_id)
                            == row_id
                        ).with_for_update()
                    )).scalar_one()
                    assert row is not None
                    locked.set()
                    await release.wait()

            async def change_policy_row():
                async with async_transaction_scope(tenant_id=str(tenant)) as session:
                    row = (await session.execute(
                        select(model).where(
                            (model.scope_id if model is ConsentScope else model.policy_id)
                            == row_id
                        ).with_for_update()
                    )).scalar_one()
                    setattr(row, field, revoked)
                changed.set()

            holding = asyncio.create_task(hold_policy_row())
            contender = None
            try:
                await asyncio.wait_for(locked.wait(), timeout=10)
                contender = asyncio.create_task(change_policy_row())
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(changed.wait()), timeout=0.2)
            finally:
                release.set()
                tasks = [holding] + ([contender] if contender is not None else [])
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert changed.is_set()
            with pytest.raises(ValueError, match=error):
                await prepare_governed_legacy_migration_retry(**base)
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                row = (await session.execute(
                    select(model).where(
                        (model.scope_id if model is ConsentScope else model.policy_id)
                        == row_id
                    )
                )).scalar_one()
                setattr(row, field, restored)
        # PostgreSQL row locks serialize withdrawal behind a verification
        # transaction. This is a database primitive proof, not an enabled writer.
        import asyncio
        source_locked = asyncio.Event()
        release_source = asyncio.Event()
        withdrawal_finished = asyncio.Event()

        async def hold_source_lock():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                locked = await session.execute(text(
                    "SELECT id FROM public.persona_memory_entries "
                    "WHERE id=:id AND tenant_id=:tenant AND user_id=:user FOR UPDATE"
                ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
                assert locked.scalar_one() == str(source)
                source_locked.set()
                await release_source.wait()

        async def withdraw_after_lock():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await session.execute(text(
                    "UPDATE public.persona_memory_entries SET content=' ' "
                    "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
                ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
            withdrawal_finished.set()

        holder = asyncio.create_task(hold_source_lock())
        await asyncio.wait_for(source_locked.wait(), timeout=10)
        contender = asyncio.create_task(withdraw_after_lock())
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(withdrawal_finished.wait()), timeout=0.2,
                )
        finally:
            release_source.set()
            await asyncio.wait_for(asyncio.gather(holder, contender), timeout=10)
        assert withdrawal_finished.is_set()
        with pytest.raises(ValueError, match="verified historical retention metadata required"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET content=:content "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic read-only assembly proof"})
        # Concurrent withdrawal must not be confused with an eligible source.
        # Commit the withdrawal in a separate transaction, then re-run the
        # canonical preparation against the fresh database state.
        import asyncio
        withdrawal_committed = asyncio.Event()
        async def withdraw_source():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await session.execute(text(
                    "UPDATE public.persona_memory_entries SET content=' ' "
                    "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
                ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
            withdrawal_committed.set()
        withdrawal = asyncio.create_task(withdraw_source())
        await withdrawal_committed.wait()
        await withdrawal
        with pytest.raises(ValueError, match="verified historical retention metadata required"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "UPDATE public.persona_memory_entries SET content=:content "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user),
                "content": "Synthetic read-only assembly proof"})
        # Canonical idempotency uniqueness must reject a second event with
        # the same key, even across independent committed transactions.
        from sqlalchemy.exc import IntegrityError
        collision_key = "kp03-" + uuid.uuid4().hex
        first_collision_event = uuid.uuid4()
        second_collision_event = uuid.uuid4()
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(MemoryEvent(
                event_id=first_collision_event, tenant_id=tenant, user_id=user,
                source_type="chat_user", payload_hash=uuid.uuid4().hex,
                idempotency_key=collision_key, event_type="memory_persisted",
                consent_state="granted", payload={"vault": {"test": "collision"}},
            ))
        with pytest.raises(IntegrityError):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=second_collision_event, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    idempotency_key=collision_key, event_type="memory_persisted",
                    consent_state="granted", payload={"vault": {"test": "collision"}},
                ))
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryEvent).where(
                MemoryEvent.idempotency_key == collision_key,
            ))).scalars().all().__len__() == 1
            await session.execute(
                text("DELETE FROM public.memory_event WHERE event_id=:event"),
                {"event": str(first_collision_event)},
            )
        # Two simultaneous writers for one canonical idempotency key must
        # serialize at PostgreSQL's unique index. The losing transaction
        # rolls back without leaving a partial event.
        collision_ready = asyncio.Event()
        release_collision = asyncio.Event()
        simultaneous_key = "kp03-concurrent-" + uuid.uuid4().hex
        winner_id, loser_id = uuid.uuid4(), uuid.uuid4()

        async def first_inserter():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=winner_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    idempotency_key=simultaneous_key,
                    event_type="memory_persisted", consent_state="granted",
                    payload={"vault": {"test": "concurrent-winner"}},
                ))
                await session.flush()
                collision_ready.set()
                await release_collision.wait()

        async def second_inserter():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=loser_id, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    idempotency_key=simultaneous_key,
                    event_type="memory_persisted", consent_state="granted",
                    payload={"vault": {"test": "concurrent-loser"}},
                ))
                await session.flush()

        winning = asyncio.create_task(first_inserter())
        losing = None
        try:
            await asyncio.wait_for(collision_ready.wait(), timeout=10)
            losing = asyncio.create_task(second_inserter())
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(losing), timeout=0.2)
        finally:
            release_collision.set()
            await asyncio.wait_for(winning, timeout=10)
        assert losing is not None
        with pytest.raises(IntegrityError):
            await asyncio.wait_for(losing, timeout=10)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            recorded = (await session.execute(select(MemoryEvent).where(
                MemoryEvent.idempotency_key == simultaneous_key,
            ))).scalars().all()
            assert len(recorded) == 1
            assert recorded[0].event_id == winner_id
            # A conflicting idempotency key is not a completed migration
            # receipt for the losing deterministic assertion identity.
            from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
                lookup_locked_legacy_replay_receipt,
            )
            from ai_karen_engine.core.memory.legacy_persona_recovery import (
                reconcile_legacy_replay,
            )
            losing_receipt = await lookup_locked_legacy_replay_receipt(
                session=session, tenant_id=str(tenant), user_id=str(user),
                expected_memory_id=str(loser_id),
                expected_request_id=str(uuid.uuid4()),
            )
            assert not losing_receipt.persisted
            losing_recovery = reconcile_legacy_replay(losing_receipt)
            assert losing_recovery.reason == "no_prior_receipt"
            assert losing_recovery.safe_to_retry
            # The failed insert cannot leave its own event behind.
            assert (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == loser_id,
            ))).scalar_one_or_none() is None
            # No matching assertion can turn a failed event into a replay
            # receipt, even if the idempotency key collided.
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.event_id == loser_id,
            ))).scalar_one_or_none() is None
            await session.execute(
                text("DELETE FROM public.memory_event WHERE event_id=:event"),
                {"event": str(winner_id)},
            )
        # Missing-receipt inspection must serialize contenders using the
        # deterministic transaction advisory lock, not merely row locks.
        from ai_karen_engine.platform.memory.postgres.legacy_persona_receipts import (
            lookup_locked_legacy_replay_receipt,
        )
        first_lookup_ready = asyncio.Event()
        release_first_lookup = asyncio.Event()
        second_lookup_finished = asyncio.Event()
        absent_memory_id, absent_request_id = str(uuid.uuid4()), str(uuid.uuid4())

        async def hold_missing_receipt_slot():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                receipt = await lookup_locked_legacy_replay_receipt(
                    session=session, tenant_id=str(tenant), user_id=str(user),
                    expected_memory_id=absent_memory_id,
                    expected_request_id=absent_request_id,
                )
                assert receipt.persisted_memory_id is None
                first_lookup_ready.set()
                await release_first_lookup.wait()

        async def inspect_same_missing_slot():
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                await lookup_locked_legacy_replay_receipt(
                    session=session, tenant_id=str(tenant), user_id=str(user),
                    expected_memory_id=absent_memory_id,
                    expected_request_id=absent_request_id,
                )
            second_lookup_finished.set()

        first_lookup = asyncio.create_task(hold_missing_receipt_slot())
        second_lookup = None
        try:
            await asyncio.wait_for(first_lookup_ready.wait(), timeout=10)
            second_lookup = asyncio.create_task(inspect_same_missing_slot())
            # An unrelated tenant must not contend on this replay slot.
            # The lookup is still tenant-scoped and returns no foreign data.
            unrelated_tenant = str(uuid.uuid4())
            async with async_transaction_scope(tenant_id=unrelated_tenant) as separate:
                unrelated = await asyncio.wait_for(
                    lookup_locked_legacy_replay_receipt(
                        session=separate, tenant_id=unrelated_tenant,
                        user_id=str(user), expected_memory_id=absent_memory_id,
                        expected_request_id=absent_request_id,
                    ), timeout=5,
                )
                assert not unrelated.persisted
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(second_lookup_finished.wait()), timeout=0.2,
                )
        finally:
            release_first_lookup.set()
            await asyncio.wait_for(first_lookup, timeout=10)
        assert second_lookup is not None
        await asyncio.wait_for(second_lookup, timeout=10)
        assert second_lookup_finished.is_set()
        # Force a transaction rollback after a speculative ledger event.
        # Reopening the transaction must show no durable partial receipt.
        rolled_back_event = uuid.uuid4()
        with pytest.raises(RuntimeError, match="forced migration rollback"):
            async with async_transaction_scope(tenant_id=str(tenant)) as session:
                session.add(MemoryEvent(
                    event_id=rolled_back_event, tenant_id=tenant, user_id=user,
                    source_type="chat_user", payload_hash=uuid.uuid4().hex,
                    event_type="memory_persisted", consent_state="granted",
                    payload={"vault": {"request_id": str(uuid.uuid4())}},
                ))
                await session.flush()
                raise RuntimeError("forced migration rollback")
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryEvent).where(
                MemoryEvent.event_id == rolled_back_event
            ))).scalar_one_or_none() is None
        # Eligibility is not durable: a subsequent retention-policy change
        # must invalidate an earlier successful read-only preparation.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            policy_row = (await session.execute(select(RetentionPolicy).where(
                RetentionPolicy.policy_id == retention_id
            ))).scalar_one()
            policy_row.ttl_days = 0
        with pytest.raises(ValueError, match="historical memory retention not authorized"):
            await prepare_governed_legacy_migration_retry(**base)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            policy_row = (await session.execute(select(RetentionPolicy).where(
                RetentionPolicy.policy_id == retention_id
            ))).scalar_one()
            policy_row.ttl_days = 30
        # The vault independently rejects expired historical retention even
        # when the caller carries an old, affirmative capability flag.
        from ai_karen_engine.platform.memory.postgres.vault import (
            NeuroVaultAuthorizationError,
        )
        expired_entry = MemoryEntry(
            id=str(uuid.uuid4()), content="Expired migration must not persist",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "persona-memory-migration"},
            ),
        )
        with pytest.raises(NeuroVaultAuthorizationError, match="historical migration persistence is disabled"):
            await PostgresNeuroVault().persist(
                expired_entry, context=VaultContext(
                    tenant_id=str(tenant), user_id=str(user),
                    request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
                    actor_id=str(user),
                    policy_context={"memory_write_authorized": True},
                ),
            )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(expired_entry.id)
            ))).scalar_one_or_none() is None
        # Runtime permissions must also be reassessed for every preparation.
        no_write_context = ChatExecutionContext(
            tenant_id=str(tenant), user_id=str(user),
            session_id="kp03-postgres-proof", request_id=str(uuid.uuid4()),
            permissions=["memory.read"],
        )
        with pytest.raises(ValueError, match="current migration authorization required"):
            await prepare_governed_legacy_migration_retry(
                **{**base, "context": no_write_context}
            )
        # A caller cannot reuse one tenant's historical source under another tenant.
        wrong_scope = ChatExecutionContext(
            tenant_id=str(uuid.uuid4()), user_id=str(user),
            session_id="kp03-postgres-proof", request_id=str(uuid.uuid4()),
            permissions=["memory.write"],
        )
        with pytest.raises(ValueError, match="identity not verified"):
            await prepare_governed_legacy_migration_retry(
                **{**base, "context": wrong_scope}
            )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            consent = (await session.execute(select(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))).scalar_one()
            consent.is_granted = False
        with pytest.raises(ValueError, match="explicit historical migration consent"):
            await prepare_governed_legacy_migration_retry(**base)
        # A previously prepared replay ID is not consent or permission.
        # NeuroVault must reject persistence after revocation, even when the
        # caller still possesses the old policy context and replay identifiers.
        from ai_karen_engine.platform.memory.postgres.vault import (
            NeuroVaultAuthorizationError,
        )
        revoked_entry = MemoryEntry(
            id=str(uuid.uuid4()), content="Never persist after revocation",
            memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
            metadata=MemoryMetadata(
                tenant_id=str(tenant), user_id=str(user), source="chat_user",
                custom={"consent_scope": "persona-memory-migration"},
            ),
        )
        with pytest.raises(NeuroVaultAuthorizationError):
            await PostgresNeuroVault().persist(
                revoked_entry, context=VaultContext(
                    tenant_id=str(tenant), user_id=str(user),
                    request_id=replay.request_id,
                    correlation_id=str(uuid.uuid4()), actor_id=str(user),
                    policy_context={"memory_write_authorized": True},
                ),
            )
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(revoked_entry.id)
            ))).scalar_one_or_none() is None
        # The only assertion was created by the explicit synthetic vault write.
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            result = await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id)
            ))
            assert result.scalar_one_or_none() is not None
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            if "replay" in locals():
                event_ids = (await session.execute(
                    select(MemoryAssertion.event_id).where(
                        MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id)
                    )
                )).scalars().all()
                await session.execute(delete(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == uuid.UUID(replay.memory_id)
                ))
                if event_ids:
                    await session.execute(delete(MemoryEvent).where(
                        MemoryEvent.event_id.in_(event_ids)
                    ))
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(text(
                "DELETE FROM public.persona_memory_entries "
                "WHERE id=:id AND tenant_id=:tenant AND user_id=:user"
            ), {"id": str(source), "tenant": str(tenant), "user": str(user)})
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id
            ))
            await session.execute(delete(RetentionPolicy).where(
                RetentionPolicy.policy_id == retention_id
            ))
            await session.execute(text(
                "DELETE FROM public.auth_users WHERE user_id=:user AND tenant_id=:tenant"
            ), {"user": str(user), "tenant": str(tenant)})


async def test_vault_caller_transaction_serializes_consent_revocation():
    """Real vault stage holds its consent row lock until caller commit."""
    import asyncio
    from sqlalchemy import update
    from ai_karen_engine.platform.memory.postgres.vault import NeuroVaultAuthorizationError

    assert os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") == "1"
    tenant, user, grant_id, memory_id = (uuid.uuid4() for _ in range(4))
    entered = asyncio.Event()
    release = asyncio.Event()
    revoked = asyncio.Event()
    entry = MemoryEntry(
        id=str(memory_id), content="Disposable consent contention proof",
        memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
        metadata=MemoryMetadata(
            tenant_id=str(tenant), user_id=str(user), source="chat_user",
            custom={"consent_scope": "kp03-revocation-proof"},
        ),
    )
    context = VaultContext(
        tenant_id=str(tenant), user_id=str(user),
        request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
        actor_id=str(user), policy_context={"memory_write_authorized": True},
    )

    async def stage_under_lock():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            receipt = await PostgresNeuroVault().persist_in_transaction(
                entry, context=context, session=session,
            )
            assert not receipt.persisted
            entered.set()
            await release.wait()

    async def revoke_after_stage():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                update(ConsentScope)
                .where(ConsentScope.scope_id == grant_id)
                .values(is_granted=False)
            )
        revoked.set()

    writer = None
    revoker = None
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            session.add(ConsentScope(
                scope_id=grant_id, tenant_id=tenant, user_id=user,
                scope_name="kp03-revocation-proof", is_granted=True,
            ))
        writer = asyncio.create_task(stage_under_lock())
        await asyncio.wait_for(entered.wait(), timeout=10)
        revoker = asyncio.create_task(revoke_after_stage())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(revoked.wait()), timeout=0.2)
        release.set()
        await asyncio.wait_for(asyncio.gather(writer, revoker), timeout=10)
        assert revoked.is_set()
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assert (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == memory_id,
            ))).scalar_one_or_none() is not None
        with pytest.raises(NeuroVaultAuthorizationError, match="revoked"):
            await PostgresNeuroVault().persist(
                MemoryEntry(
                    id=str(uuid.uuid4()), content="Must fail after revocation",
                    memory_type=MemoryType.SEMANTIC,
                    namespace=MemoryNamespace.LONG_TERM,
                    metadata=entry.metadata,
                ),
                context=context,
            )
    finally:
        release.set()
        tasks = [task for task in (writer, revoker) if task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            events = (await session.execute(
                select(MemoryAssertion.event_id).where(
                    MemoryAssertion.assertion_id == memory_id,
                )
            )).scalars().all()
            await session.execute(delete(MemoryAssertion).where(
                MemoryAssertion.assertion_id == memory_id,
            ))
            if events:
                await session.execute(delete(MemoryEvent).where(
                    MemoryEvent.event_id.in_(events),
                ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == grant_id,
            ))


async def test_vault_caller_transaction_serializes_consent_revocation():
    """An actual staged NeuroVault write holds consent until commit."""
    import asyncio
    from sqlalchemy import update
    from ai_karen_engine.platform.memory.postgres.vault import (
        NeuroVaultAuthorizationError,
    )

    assert os.getenv("KAREN_TEST_DISPOSABLE_DATABASE") == "1"
    tenant, user, consent_id, memory_id = (uuid.uuid4() for _ in range(4))
    entered = asyncio.Event()
    release = asyncio.Event()
    revoked = asyncio.Event()
    entry = MemoryEntry(
        id=str(memory_id), content="Consent lock commit-order proof",
        memory_type=MemoryType.SEMANTIC, namespace=MemoryNamespace.LONG_TERM,
        metadata=MemoryMetadata(
            tenant_id=str(tenant), user_id=str(user), source="chat_user",
            custom={"consent_scope": "vault-lock-proof"},
        ),
    )
    context = VaultContext(
        tenant_id=str(tenant), user_id=str(user),
        request_id=str(uuid.uuid4()), correlation_id=str(uuid.uuid4()),
        actor_id=str(user), policy_context={"memory_write_authorized": True},
    )
    async with async_transaction_scope(tenant_id=str(tenant)) as session:
        session.add(ConsentScope(
            scope_id=consent_id, tenant_id=tenant, user_id=user,
            scope_name="vault-lock-proof", is_granted=True,
        ))

    async def stage_and_commit():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            receipt = await PostgresNeuroVault().persist_in_transaction(
                entry, context=context, session=session,
            )
            assert not receipt.persisted
            assert receipt.metadata["pending_commit"] is True
            entered.set()
            await release.wait()

    async def revoke_consent():
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            await session.execute(
                update(ConsentScope).where(
                    ConsentScope.scope_id == consent_id,
                ).values(is_granted=False)
            )
        revoked.set()

    writer = asyncio.create_task(stage_and_commit())
    revoker = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        revoker = asyncio.create_task(revoke_consent())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(revoked.wait()), timeout=0.2)
    finally:
        release.set()
        await asyncio.wait_for(writer, timeout=10)
    assert revoker is not None
    await asyncio.wait_for(revoker, timeout=10)
    assert revoked.is_set()
    try:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assertion = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == memory_id,
            ))).scalar_one()
            assert assertion.content == entry.content
        with pytest.raises(NeuroVaultAuthorizationError, match="consent scope is revoked"):
            await PostgresNeuroVault().persist(
                MemoryEntry(
                    id=str(uuid.uuid4()), content="Must not persist after revocation",
                    memory_type=MemoryType.SEMANTIC,
                    namespace=MemoryNamespace.LONG_TERM,
                    metadata=entry.metadata,
                ), context=VaultContext(
                    tenant_id=str(tenant), user_id=str(user),
                    request_id=str(uuid.uuid4()),
                    correlation_id=str(uuid.uuid4()), actor_id=str(user),
                    policy_context={"memory_write_authorized": True},
                ),
            )
    finally:
        async with async_transaction_scope(tenant_id=str(tenant)) as session:
            assertion = (await session.execute(select(MemoryAssertion).where(
                MemoryAssertion.assertion_id == memory_id,
            ))).scalar_one_or_none()
            if assertion is not None:
                await session.delete(assertion)
                await session.flush()
                await session.execute(delete(MemoryEvent).where(
                    MemoryEvent.event_id == assertion.event_id,
                ))
            await session.execute(delete(ConsentScope).where(
                ConsentScope.scope_id == consent_id,
            ))
