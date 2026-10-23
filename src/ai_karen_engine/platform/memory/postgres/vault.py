"""PostgreSQL NeuroVault adapter for governed durable memory.

This module implements the canonical ``VaultPort`` for PostgreSQL. It owns only
backend-specific durable mutations and integrity/export operations. It does not
perform recall ranking, signal extraction, prompt construction, provider/model
selection, projections, or background synthesis.

Every mutation fails closed unless the supplied ``VaultContext`` carries an
explicit RuntimePolicy authorization signal.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from ai_karen_engine.core.memory.protocols import (
    VaultContext,
    VaultPort,
    VaultWriteReceipt,
)
from ai_karen_engine.core.memory.types import (
    MemoryEntry,
    MemoryMetadata,
    MemoryNamespace,
    MemoryStatus,
    MemoryType,
)

from .ledger_models import (
    ConsentScope,
    MemoryAssertion,
    MemoryEvent,
    RetentionPolicy,
)


class NeuroVaultAuthorizationError(PermissionError):
    """Raised when durable memory access lacks explicit RuntimePolicy authority."""


class NeuroVaultScopeError(ValueError):
    """Raised when durable memory scope or identity is invalid."""


class _HistoricalTransactionCapability:
    """Opaque, one-use transaction authority, not a policy decision.

    Only the trusted runtime executor may eventually request issuance. Issuance
    remains disabled until the complete authenticated write path is integrated.
    """

    __slots__ = ("_nonce", "_session", "_tenant", "_user", "_memory_id", "_transaction_id", "_policy_decision_id", "_used")

    def __init__(self, *, nonce: object, session: Any, tenant: str,
                 user: str, memory_id: str, transaction_id: int,
                 policy_decision_id: str) -> None:
        self._nonce = nonce
        self._session = session
        self._tenant = tenant
        self._user = user
        self._memory_id = memory_id
        self._transaction_id = transaction_id
        self._policy_decision_id = policy_decision_id
        self._used = False


# Private witness is deliberately not exported as a runtime permission.
_HISTORICAL_CAPABILITY_WITNESS = object()


def _verify_historical_transaction_capability(
    capability: Any, *, session: Any, context: VaultContext,
    entry: MemoryEntry, transaction_id: int,
    policy_decision_id: str, consume: bool = False,
) -> bool:
    """Fail closed for forged, reused, detached or mismatched authorities.

    Validation alone never permits persistence: the canonical Vault historical
    gates stay closed until runtime issuance and end-to-end tests are complete.
    """
    if (
        type(capability) is not _HistoricalTransactionCapability
        or capability._nonce is not _HISTORICAL_CAPABILITY_WITNESS
        or capability._used
        or capability._session is not session
        or capability._tenant != context.tenant_id
        or capability._user != context.user_id
        or capability._memory_id != str(entry.id)
        or not isinstance(transaction_id, int)
        or transaction_id <= 0
        or capability._transaction_id != transaction_id
        or not isinstance(policy_decision_id, str)
        or not policy_decision_id.strip()
        or capability._policy_decision_id != policy_decision_id
        or not getattr(session, "in_transaction", lambda: False)()
    ):
        return False
    if consume:
        capability._used = True
    return True


async def _verify_historical_capability_against_database(
    capability: Any, *, session: Any, context: VaultContext,
    entry: MemoryEntry, policy_decision_id: str,
    consume: bool = False,
) -> bool:
    """Read actual transaction identity; never trust a claimed transaction ID.

    Deliberately does not issue authority or enable historical writes.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    if not isinstance(session, AsyncSession) or not session.in_transaction():
        return False
    if (
        type(capability) is not _HistoricalTransactionCapability
        or capability._nonce is not _HISTORICAL_CAPABILITY_WITNESS
        or capability._used
        or capability._session is not session
        or capability._tenant != context.tenant_id
        or capability._user != context.user_id
        or capability._memory_id != str(entry.id)
        or capability._policy_decision_id != policy_decision_id
    ):
        return False
    actual = (await session.execute(text(
        "SELECT current_setting('app.current_tenant_id', true), "
        "current_setting('app.tenant_id', true), "
        "current_setting('app.current_user_id', true), txid_current()"
    ))).one()
    if actual[:3] != (context.tenant_id, context.tenant_id, context.user_id):
        return False
    return _verify_historical_transaction_capability(
        capability, session=session, context=context, entry=entry,
        transaction_id=actual[3], policy_decision_id=policy_decision_id,
        consume=consume,
    )


async def _inspect_historical_migration_write_authority(
    *, capability: Any, session: Any, context: VaultContext,
    entry: MemoryEntry, policy_decision_id: str,
) -> None:
    """Verify candidate authority while keeping both historical gates closed.

    This function cannot issue or consume write authority. The runtime must
    prove eligible source, active consent, current policy and replay under
    the same transaction before a future executor can use it.
    """
    if not await _verify_historical_capability_against_database(
        capability, session=session, context=context, entry=entry,
        policy_decision_id=policy_decision_id,
    ):
        raise NeuroVaultAuthorizationError(
            "valid transaction-bound historical migration authority required"
        )
    # Verified inspection alone never licenses a historical write.
    PostgresNeuroVault._require_non_historical_write(entry)


class PostgresNeuroVault(VaultPort):
    """Governed PostgreSQL durable-memory adapter."""

    WRITE_CAPABILITY = "memory.write"
    DELETE_CAPABILITY = "memory.delete"
    READ_CAPABILITY = "memory.read"

    def __init__(self, session_factory: Callable[..., Any] | None = None) -> None:
        self._session_factory = session_factory

    def _resolve_session_factory(self) -> Callable[..., Any]:
        if self._session_factory is not None:
            return self._session_factory

        from ai_karen_engine.database.client import db_client

        factory = getattr(db_client, "get_async_session", None)
        if factory is None:
            raise RuntimeError("PostgreSQL async session factory is unavailable")
        self._session_factory = factory
        return factory

    @staticmethod
    def _uuid(value: str, *, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise NeuroVaultScopeError(f"{field_name} must be a valid UUID") from exc

    @classmethod
    def _require_capability(cls, context: VaultContext, capability: str) -> None:
        context.validate()
        policy = dict(context.policy_context or {})
        if policy.get("denied") is True:
            raise NeuroVaultAuthorizationError("RuntimePolicy denied durable memory operation")

        explicit_flag = {
            cls.WRITE_CAPABILITY: "memory_write_authorized",
            cls.DELETE_CAPABILITY: "memory_delete_authorized",
            cls.READ_CAPABILITY: "memory_read_authorized",
        }.get(capability)
        if explicit_flag and policy.get(explicit_flag) is True:
            return

        allowed = {
            str(value).strip()
            for value in policy.get("allowed_capabilities", ())
            if str(value).strip()
        }
        if "*" in allowed or capability in allowed:
            return
        raise NeuroVaultAuthorizationError(
            f"durable memory operation requires explicit capability: {capability}"
        )

    @classmethod
    def _validate_entry_scope(cls, entry: MemoryEntry, context: VaultContext) -> None:
        context.validate()
        metadata = entry.metadata
        if metadata is None:
            raise NeuroVaultScopeError("durable memory entry requires MemoryMetadata")
        if str(metadata.tenant_id or "") != context.tenant_id:
            raise NeuroVaultScopeError("memory entry tenant_id does not match VaultContext")
        if str(metadata.user_id or "") != context.user_id:
            raise NeuroVaultScopeError("memory entry user_id does not match VaultContext")
        if not str(entry.content or "").strip():
            raise NeuroVaultScopeError("durable memory entry content must not be empty")

    @staticmethod
    def _payload_hash(entry: MemoryEntry) -> str:
        raw = "|".join(
            (
                str(entry.id),
                str(entry.version),
                entry.content,
                entry.memory_type.value,
                entry.namespace.value,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _idempotency_key(entry: MemoryEntry, context: VaultContext) -> str:
        raw = "|".join(
            (
                context.tenant_id,
                context.user_id,
                str(entry.id),
                str(entry.version),
                context.request_id,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _naive_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    async def _consent_granted(
        self,
        session: Any,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        scope_name: str,
    ) -> bool:
        stmt = (
            select(ConsentScope)
            .where(
                ConsentScope.tenant_id == tenant_id,
                ConsentScope.user_id == user_id,
                ConsentScope.scope_name == scope_name,
            )
            .order_by(ConsentScope.granted_at.desc())
            .limit(1)
            .with_for_update()
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None and scope_name == "persona-memory-migration":
            return False
        return True if record is None else bool(record.is_granted)

    async def _retention_deadline(
        self,
        session: Any,
        *,
        tenant_id: uuid.UUID,
        entry: MemoryEntry,
    ) -> datetime | None:
        if entry.expires_at is not None:
            return self._naive_utc(entry.expires_at)
        if entry.ttl_seconds is not None:
            created = self._naive_utc(entry.created_at) or datetime.utcnow()
            return created + timedelta(seconds=float(entry.ttl_seconds))

        memory_class = entry.memory_type.value
        tenant_stmt = (
            select(RetentionPolicy)
            .where(
                RetentionPolicy.tenant_id == tenant_id,
                RetentionPolicy.memory_class == memory_class,
            )
            .order_by(RetentionPolicy.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(tenant_stmt)
        policy = result.scalar_one_or_none()
        if policy is None:
            global_stmt = (
                select(RetentionPolicy)
                .where(
                    RetentionPolicy.tenant_id.is_(None),
                    RetentionPolicy.memory_class == memory_class,
                )
                .order_by(RetentionPolicy.updated_at.desc())
                .limit(1)
            )
            result = await session.execute(global_stmt)
            policy = result.scalar_one_or_none()

        if policy is None or policy.ttl_days is None:
            return None
        created = self._naive_utc(entry.created_at) or datetime.utcnow()
        return created + timedelta(days=int(policy.ttl_days))

    def _validate_persist_authority(
        self, entry: MemoryEntry, context: VaultContext,
    ) -> None:
        """One canonical pre-database gate for memory write authorization.

        Both public entrypoints invoke this before opening or inspecting a
        database session. The shared ledger implementation does not duplicate
        policy evaluation; the runtime retains responsibility for decisions.
        """
        self._require_capability(context, self.WRITE_CAPABILITY)
        self._validate_entry_scope(entry, context)

    @staticmethod
    def _is_historical_write(entry: MemoryEntry) -> bool:
        """Canonical historical source classification, shared by both gates."""
        metadata = entry.metadata
        custom = dict(metadata.custom or {}) if metadata else {}
        def canonical(value: Any) -> str:
            return value.strip().lower() if isinstance(value, str) else ""

        return (
            canonical(custom.get("consent_scope")) == "persona-memory-migration"
            or canonical(custom.get("source_type")) == "legacy_persona"
            or canonical(metadata.source if metadata is not None else None)
            == "legacy_persona"
        )

    @classmethod
    def _require_non_historical_write(cls, entry: MemoryEntry) -> None:
        """Fail closed before canonical ledger persistence."""
        if cls._is_historical_write(entry):
            raise NeuroVaultAuthorizationError(
                "historical migration persistence is disabled pending trusted runtime authorization"
            )

    async def persist(
        self, entry: MemoryEntry, *, context: VaultContext,
    ) -> VaultWriteReceipt:
        """Canonical standalone write. Owns and commits its PostgreSQL session."""
        self._validate_persist_authority(entry, context)
        # Standalone writes cannot inherit transaction-scoped runtime authority.
        # Reject migration data before opening any database connection.
        self._require_non_historical_write(entry)
        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            return await self._persist_with_session(
                entry, context=context, session=session, commit=True,
            )

    @staticmethod
    async def _rollback_caller_transaction(session: Any) -> None:
        """Reuse the canonical PostgreSQL cancellation-safe rollback owner."""
        from ai_karen_engine.persistence.postgres.transactions import (
            rollback_async_transaction,
        )
        await rollback_async_transaction(session)

    async def persist_in_transaction(
        self, entry: MemoryEntry, *, context: VaultContext, session: Any,
        historical_inspection: Any = None,
    ) -> VaultWriteReceipt:
        """Stage a governed write in a caller-owned transaction.

        The caller must commit or roll back. Integrity collisions propagate
        so the entire caller transaction fails closed; no success receipt
        implies a commit. Historical migration remains blocked.
        """
        # Validate policy capability and principal scope before any database
        # query, including transaction-local tenant introspection.
        self._validate_persist_authority(entry, context)
        # Ordinary caller-owned transactions must never probe database scope
        # with a historical payload. A read-only inspection can be validated
        # separately, but it remains incapable of granting persistence.
        if historical_inspection is None:
            self._require_non_historical_write(entry)
        if session is None:
            raise ValueError("caller-owned active PostgreSQL session required")
        # Never accept a raw, unscoped session for a governed mutation.
        # The caller must own an active transaction; tenant enforcement still
        # comes from the canonical context and the database's tenant RLS.
        from sqlalchemy.ext.asyncio import AsyncSession

        if not isinstance(session, AsyncSession) or not session.in_transaction():
            raise NeuroVaultAuthorizationError(
                "active caller-owned PostgreSQL transaction required"
            )
        if historical_inspection is not None:
            # Inspection is not a write grant. Never trust duck-typed,
            # serialized or caller-forged authority objects.
            from ai_karen_engine.core.memory.legacy_persona_admission import (
                LegacyMigrationTransactionAuthority,
            )
            if type(historical_inspection) is not LegacyMigrationTransactionAuthority:
                raise NeuroVaultAuthorizationError(
                    "canonical migration transaction inspection required"
                )
            if (
                not self._is_historical_write(entry)
                or historical_inspection.tenant_id != context.tenant_id
                or historical_inspection.user_id != context.user_id
            ):
                raise NeuroVaultAuthorizationError(
                    "migration inspection scope does not match historical write"
                )
            try:
                await historical_inspection.verify_active(session=session)
            except PermissionError as exc:
                raise NeuroVaultAuthorizationError(
                    "migration inspection transaction is not active"
                ) from exc
            # Keep historical writes disabled, including when inspection
            # provenance appears valid. A verified snapshot is forgeable and
            # cannot replace a runtime-issued executable capability.
            self._require_non_historical_write(entry)
        # Verify the database-local RLS scope, not just caller-supplied
        # VaultContext claims. Both canonical and compatibility settings
        # are established by the existing transaction manager.
        from sqlalchemy import text
        scope = (await session.execute(text(
            "SELECT current_setting('app.current_tenant_id', true), "
            "current_setting('app.tenant_id', true)"
        ))).one()
        if (
            scope[0] != str(self._uuid(context.tenant_id, field_name="tenant_id"))
            or scope[1] != str(self._uuid(context.tenant_id, field_name="tenant_id"))
        ):
            raise NeuroVaultAuthorizationError(
                "caller transaction tenant scope does not match authenticated context"
            )
        # Confirm the RLS-scoped authenticated principal when provided by
        # the runtime transaction. The database principal must never differ
        # from the entry's canonical VaultContext.
        principal = (await session.execute(text(
            "SELECT current_setting('app.current_user_id', true)"
        ))).scalar_one()
        if self._is_historical_write(entry) and not principal:
            raise NeuroVaultAuthorizationError(
                "historical migration requires authenticated transaction principal"
            )
        if principal and principal != str(self._uuid(context.user_id, field_name="user_id")):
            raise NeuroVaultAuthorizationError(
                "caller transaction user scope does not match authenticated context"
            )
        # Recheck the tenant scope after database reads to guard against
        # transaction-local settings changing during authorization.
        final_scope = (await session.execute(text(
            "SELECT current_setting('app.current_tenant_id', true), "
            "current_setting('app.tenant_id', true), "
            "current_setting('app.current_user_id', true)"
        ))).one()
        if final_scope[0] != scope[0] or final_scope[1] != scope[1]:
            raise NeuroVaultAuthorizationError(
                "caller transaction tenant scope changed during authorization"
            )
        if final_scope[2] != principal:
            raise NeuroVaultAuthorizationError(
                "caller transaction principal changed during authorization"
            )
        # Historical migration remains disabled even when the runtime has
        # performed read-only transaction inspection. Block it before the
        # canonical ledger writer and before any staged assertion.
        self._require_non_historical_write(entry)
        # A typed inspection result or a caller-provided policy decision ID
        # is never a transferable write grant. Runtime-only historical
        # authorization must be implemented as a separate trusted contract.
        from dataclasses import replace

        try:
            receipt = await self._persist_with_session(
                entry, context=context, session=session, commit=False,
            )
        except BaseException:
            # Including asyncio.CancelledError: a cancelled ledger write
            # must not leave a caller-owned transaction committable.
            # A failed ledger/consent write invalidates the caller's entire
            # transaction. Do not rely on the caller to propagate the error:
            # a swallowed IntegrityError must never permit a partial commit.
            await self._rollback_caller_transaction(session)
            raise
        # A caller-owned transaction may have executed additional SQL inside
        # the writer. Never return staged success if its authenticated scope
        # drifted during ledger/consent writes.
        try:
            post_write_scope = (await session.execute(text(
                "SELECT current_setting('app.current_tenant_id', true), "
                "current_setting('app.tenant_id', true), "
                "current_setting('app.current_user_id', true)"
            ))).one()
        except BaseException:
            # Cancellation during the final scope read also invalidates the
            # caller-owned transaction after the ledger has been staged.
            # The ledger is already staged. An unavailable final scope read
            # must invalidate the transaction even if the caller swallows
            # the database exception and tries to commit.
            await self._rollback_caller_transaction(session)
            raise
        if post_write_scope != final_scope:
            # No staged ledger may survive a rejected principal/tenant.
            # The caller's entire transaction is invalid after this point.
            await self._rollback_caller_transaction(session)
            raise NeuroVaultAuthorizationError(
                "caller transaction scope changed during persistence"
            )
        return replace(
            receipt, persisted=False,
            metadata={**receipt.metadata, "pending_commit": True},
        )

    async def _persist_with_session(
        self, entry: MemoryEntry, *, context: VaultContext,
        session: Any, commit: bool,
    ) -> VaultWriteReceipt:
        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        metadata = entry.metadata
        assert metadata is not None
        custom = dict(metadata.custom or {})
        consent_scope = str(custom.get("consent_scope") or "memory.write")
        source_type = str(custom.get("source_type") or metadata.source or "runtime")
        self._require_non_historical_write(entry)
        sensitivity = str(custom.get("sensitivity_class") or "normal")
        source_ref = str(
            custom.get("source_ref")
            or context.conversation_id
            or context.session_id
            or context.request_id
        )

        if not await self._consent_granted(
            session,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            scope_name=consent_scope,
        ):
            raise NeuroVaultAuthorizationError(
                f"memory consent scope is revoked: {consent_scope}"
            )

        valid_to = await self._retention_deadline(
            session,
            tenant_id=tenant_uuid,
            entry=entry,
        )
        event_id = uuid.uuid4()
        assertion_id = self._entry_uuid(entry.id)
        payload = entry.to_dict()
        payload.setdefault("vault", {})
        payload["vault"] = {
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "actor_id": context.actor_id,
            "consent_scope": consent_scope,
        }

        event = MemoryEvent(
            event_id=event_id,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            source_type=source_type,
            source_ref=source_ref,
            payload_hash=self._payload_hash(entry),
            idempotency_key=self._idempotency_key(entry, context),
            confidence=float(entry.confidence),
            scope=str(custom.get("scope") or "user"),
            sensitivity_class=sensitivity,
            consent_state="granted",
            valid_from=self._naive_utc(entry.created_at),
            valid_to=valid_to,
            supersedes=self._optional_uuid(entry.parent_id),
            event_type="memory_persisted",
            payload=payload,
        )
        assertion = MemoryAssertion(
            assertion_id=assertion_id,
            event_id=event_id,
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            content=entry.content,
            confidence=float(entry.confidence),
            scope=str(custom.get("scope") or "user"),
            sensitivity_class=sensitivity,
            consent_state="granted",
            valid_from=self._naive_utc(entry.created_at),
            valid_to=valid_to,
            supersedes=self._optional_uuid(entry.parent_id),
        )
        try:
            # Explicitly flush the parent row before inserting the child.
            # Independent ORM objects without relationship wiring are not
            # guaranteed to flush in FK dependency order.
            session.add(event)
            await session.flush()
            session.add(assertion)
            await session.flush()
            if commit:
                await session.commit()
        except IntegrityError:
            if not commit:
                raise
            await session.rollback()
            existing = await self._find_by_idempotency(
                session,
                self._idempotency_key(entry, context),
            )
            if existing is None:
                raise
            assertion_stmt = select(MemoryAssertion).where(
                MemoryAssertion.event_id == existing.event_id
            )
            result = await session.execute(assertion_stmt)
            existing_assertion = result.scalar_one_or_none()
            # A unique-key collision is only an idempotent replay when
            # the original event and assertion match this exact request.
            # Never report another principal's write, a partial ledger
            # event, or changed content as successfully persisted.
            if (
                existing.tenant_id != tenant_uuid
                or existing.user_id != user_uuid
                or existing.event_type != "memory_persisted"
                or not isinstance(existing.payload, dict)
                or not isinstance(existing.payload.get("vault"), dict)
                or existing.payload["vault"].get("request_id") != context.request_id
                or existing.payload["vault"].get("consent_scope") != consent_scope
                or existing.source_type != source_type
                or existing.payload_hash != self._payload_hash(entry)
                or existing.idempotency_key != self._idempotency_key(entry, context)
                or existing_assertion is None
                or existing_assertion.assertion_id != assertion_id
                or existing_assertion.tenant_id != tenant_uuid
                or existing_assertion.user_id != user_uuid
                or existing_assertion.event_id != existing.event_id
                or existing_assertion.content != entry.content
                or existing_assertion.consent_state != "granted"
                or (existing_assertion.valid_to is not None
                    and existing_assertion.valid_to <= datetime.utcnow())
            ):
                raise NeuroVaultAuthorizationError(
                    "idempotency collision does not match canonical memory write"
                )
            return VaultWriteReceipt(
                memory_id=str(existing_assertion.assertion_id),
                persisted=True,
                version=entry.version,
                metadata={
                    "event_id": str(existing.event_id),
                    "idempotent_replay": True,
                },
            )

        return VaultWriteReceipt(
            memory_id=str(assertion_id),
            persisted=True,
            version=entry.version,
            metadata={
                "event_id": str(event_id),
                "source_store": "postgres",
                "retention_deadline": valid_to.isoformat() if valid_to else None,
                "consent_scope": consent_scope,
            },
        )

    async def tombstone(
        self,
        memory_id: str,
        *,
        reason: str,
        context: VaultContext,
    ) -> VaultWriteReceipt:
        self._require_capability(context, self.DELETE_CAPABILITY)
        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        assertion_uuid = self._uuid(memory_id, field_name="memory_id")
        now = datetime.utcnow()

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            assertion = await self._scoped_assertion(
                session,
                assertion_uuid,
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
            )
            if assertion is None:
                return VaultWriteReceipt(memory_id=memory_id, persisted=False, tombstoned=False)
            assertion.valid_to = now
            source_event = await self._scoped_event(
                session,
                assertion.event_id,
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
            )
            if source_event is not None:
                source_event.valid_to = now
                source_event.updated_at = now
            event = self._mutation_event(
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
                event_type="memory_tombstoned",
                memory_id=memory_id,
                reason=reason,
                context=context,
            )
            session.add(event)
            await session.commit()
            return VaultWriteReceipt(
                memory_id=memory_id,
                persisted=True,
                tombstoned=True,
                metadata={"event_id": str(event.event_id), "reason": reason},
            )

    async def delete(
        self,
        memory_id: str,
        *,
        reason: str,
        context: VaultContext,
    ) -> VaultWriteReceipt:
        self._require_capability(context, self.DELETE_CAPABILITY)
        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        assertion_uuid = self._uuid(memory_id, field_name="memory_id")

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            assertion = await self._scoped_assertion(
                session,
                assertion_uuid,
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
            )
            if assertion is None:
                return VaultWriteReceipt(memory_id=memory_id, persisted=False)

            source_event = await self._scoped_event(
                session,
                assertion.event_id,
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
            )
            if source_event is not None:
                source_event.valid_to = datetime.utcnow()
                source_event.updated_at = datetime.utcnow()

            event = self._mutation_event(
                tenant_uuid=tenant_uuid,
                user_uuid=user_uuid,
                event_type="memory_deleted",
                memory_id=memory_id,
                reason=reason,
                context=context,
            )
            session.add(event)
            await session.execute(
                sa_delete(MemoryAssertion).where(
                    MemoryAssertion.assertion_id == assertion_uuid,
                    MemoryAssertion.tenant_id == tenant_uuid,
                    MemoryAssertion.user_id == user_uuid,
                )
            )
            await session.commit()
            return VaultWriteReceipt(
                memory_id=memory_id,
                persisted=True,
                metadata={"event_id": str(event.event_id), "reason": reason},
            )

    async def export(
        self,
        memory_ids: Sequence[str],
        *,
        context: VaultContext,
    ) -> list[MemoryEntry]:
        self._require_capability(context, self.READ_CAPABILITY)
        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        ids = [self._uuid(value, field_name="memory_id") for value in memory_ids]
        if not ids:
            return []

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(MemoryAssertion).where(
                MemoryAssertion.assertion_id.in_(ids),
                MemoryAssertion.tenant_id == tenant_uuid,
                MemoryAssertion.user_id == user_uuid,
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [self._to_entry(row) for row in rows]

    async def verify_integrity(
        self,
        memory_ids: Sequence[str],
        *,
        context: VaultContext,
    ) -> Mapping[str, bool]:
        self._require_capability(context, self.READ_CAPABILITY)
        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        ids = [self._uuid(value, field_name="memory_id") for value in memory_ids]
        if not ids:
            return {}

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
            stmt = select(MemoryAssertion).where(
                MemoryAssertion.assertion_id.in_(ids),
                MemoryAssertion.tenant_id == tenant_uuid,
                MemoryAssertion.user_id == user_uuid,
            )
            result = await session.execute(stmt)
            present = {str(row.assertion_id) for row in result.scalars().all()}
        return {str(value): str(value) in present for value in memory_ids}

    @staticmethod
    def _entry_uuid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return uuid.uuid5(uuid.NAMESPACE_URL, f"ai-karen-memory:{value}")

    @staticmethod
    def _optional_uuid(value: str | None) -> uuid.UUID | None:
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return uuid.uuid5(uuid.NAMESPACE_URL, f"ai-karen-memory:{value}")

    @staticmethod
    async def _find_by_idempotency(session: Any, key: str) -> MemoryEvent | None:
        stmt = select(MemoryEvent).where(MemoryEvent.idempotency_key == key).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _scoped_event(
        session: Any,
        event_id: uuid.UUID,
        *,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
    ) -> MemoryEvent | None:
        stmt = select(MemoryEvent).where(
            MemoryEvent.event_id == event_id,
            MemoryEvent.tenant_id == tenant_uuid,
            MemoryEvent.user_id == user_uuid,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def _scoped_assertion(
        session: Any,
        assertion_id: uuid.UUID,
        *,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
    ) -> MemoryAssertion | None:
        stmt = select(MemoryAssertion).where(
            MemoryAssertion.assertion_id == assertion_id,
            MemoryAssertion.tenant_id == tenant_uuid,
            MemoryAssertion.user_id == user_uuid,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _mutation_event(
        *,
        tenant_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_type: str,
        memory_id: str,
        reason: str,
        context: VaultContext,
    ) -> MemoryEvent:
        payload = {
            "memory_id": memory_id,
            "reason": reason,
            "request_id": context.request_id,
            "correlation_id": context.correlation_id,
            "actor_id": context.actor_id,
        }
        payload_hash = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
        return MemoryEvent(
            event_id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            user_id=user_uuid,
            source_type="neuro_vault",
            source_ref=context.request_id,
            payload_hash=payload_hash,
            idempotency_key=hashlib.sha256(
                f"{event_type}|{context.request_id}|{memory_id}".encode("utf-8")
            ).hexdigest(),
            confidence=1.0,
            scope="user",
            sensitivity_class="normal",
            consent_state="granted",
            event_type=event_type,
            payload=payload,
        )

    @staticmethod
    def _to_entry(row: MemoryAssertion) -> MemoryEntry:
        created_at = row.created_at or datetime.utcnow()
        metadata = MemoryMetadata(
            tenant_id=str(row.tenant_id),
            user_id=str(row.user_id),
            source="postgres_neuro_vault",
            custom={
                "source_store": "postgres",
                "event_id": str(row.event_id),
                "scope": row.scope,
                "consent_state": row.consent_state,
                "sensitivity_class": row.sensitivity_class,
            },
        )
        return MemoryEntry(
            id=str(row.assertion_id),
            content=str(row.content or ""),
            memory_type=MemoryType.SEMANTIC,
            namespace=MemoryNamespace.LONG_TERM,
            status=(
                MemoryStatus.ARCHIVED
                if row.valid_to is not None and row.valid_to <= datetime.utcnow()
                else MemoryStatus.ACTIVE
            ),
            timestamp=created_at,
            created_at=created_at,
            updated_at=row.updated_at or created_at,
            expires_at=row.valid_to,
            confidence=float(row.confidence or 0.0),
            metadata=metadata,
        )


__all__ = [
    "NeuroVaultAuthorizationError",
    "NeuroVaultScopeError",
    "PostgresNeuroVault",
]
