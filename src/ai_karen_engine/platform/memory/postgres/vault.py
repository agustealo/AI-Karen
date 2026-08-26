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
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()
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

    async def persist(
        self,
        entry: MemoryEntry,
        *,
        context: VaultContext,
    ) -> VaultWriteReceipt:
        self._require_capability(context, self.WRITE_CAPABILITY)
        self._validate_entry_scope(entry, context)

        tenant_uuid = self._uuid(context.tenant_id, field_name="tenant_id")
        user_uuid = self._uuid(context.user_id, field_name="user_id")
        metadata = entry.metadata
        assert metadata is not None
        custom = dict(metadata.custom or {})
        consent_scope = str(custom.get("consent_scope") or "memory.write")
        sensitivity = str(custom.get("sensitivity_class") or "normal")
        source_type = str(custom.get("source_type") or metadata.source or "runtime")
        source_ref = str(
            custom.get("source_ref")
            or context.conversation_id
            or context.session_id
            or context.request_id
        )

        session_factory = self._resolve_session_factory()
        async with session_factory() as session:
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
            session.add(event)
            session.add(assertion)
            try:
                await session.commit()
            except IntegrityError:
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
                return VaultWriteReceipt(
                    memory_id=(
                        str(existing_assertion.assertion_id)
                        if existing_assertion is not None
                        else str(entry.id)
                    ),
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
