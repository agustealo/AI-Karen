"""Durable privacy request, export, and erasure authority.

Privacy lifecycle state is migration-owned PostgreSQL data. Authenticated user and
 tenant scope must be supplied by the API boundary. This service never fabricates
success counts, never stores raw verification tokens, and never treats retired
vector stores or caches as deletion authorities.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient

try:
    from ai_karen_engine.services.audit.audit_logging import get_audit_logger
except ImportError:
    from ai_karen_engine.services.audit.audit_logger import get_audit_logger

logger = logging.getLogger(__name__)


class DataExportFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    XML = "xml"


class ErasureType(str, Enum):
    SOFT_DELETE = "soft_delete"
    HARD_DELETE = "hard_delete"
    ANONYMIZE = "anonymize"


class PrivacyRequestStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PrivacyRequest:
    request_id: str
    request_type: str
    user_id: str
    tenant_id: str
    status: PrivacyRequestStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    data_types: Optional[List[str]] = None
    export_format: Optional[DataExportFormat] = None
    erasure_type: Optional[ErasureType] = None
    verification_token: Optional[str] = None
    result_metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    correlation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["created_at"] = self.created_at.isoformat()
        if self.completed_at:
            payload["completed_at"] = self.completed_at.isoformat()
        if self.export_format:
            payload["export_format"] = self.export_format.value
        if self.erasure_type:
            payload["erasure_type"] = self.erasure_type.value
        return payload


class PIIDetector:
    """Deterministic PII detector used for safe previews and redacted exports."""

    def __init__(self) -> None:
        self.pii_patterns = {
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
            "phone": r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
            "ssn": r"\b\d{3}-?\d{2}-?\d{4}\b",
            "credit_card": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
            "ip_address": r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
        }

    def detect_pii(self, value: str) -> Dict[str, List[str]]:
        found: Dict[str, List[str]] = {}
        for pii_type, pattern in self.pii_patterns.items():
            matches = re.findall(pattern, value or "", re.IGNORECASE)
            if matches:
                found[pii_type] = list(matches)
        return found

    def anonymize_text(self, value: str) -> str:
        result = value or ""
        for pii_type, pattern in self.pii_patterns.items():
            result = re.sub(
                pattern,
                f"[{pii_type.upper()}_ANONYMIZED]",
                result,
                flags=re.IGNORECASE,
            )
        return result

    def extract_safe_metadata(self, value: str) -> Dict[str, Any]:
        pii = self.detect_pii(value or "")
        return {
            "text_length": len(value or ""),
            "word_count": len((value or "").split()),
            "contains_pii": bool(pii),
            "pii_types": sorted(pii),
            "pii_count": sum(len(matches) for matches in pii.values()),
        }


async def _set_request_scope(session: Any, *, tenant_id: str, user_id: str) -> None:
    """Set fail-closed PostgreSQL RLS identity for the current transaction."""
    await session.execute(
        text(
            "SELECT "
            "set_config('app.current_tenant_id', :tenant_id, true), "
            "set_config('app.current_user_id', :user_id, true)"
        ),
        {"tenant_id": tenant_id, "user_id": user_id},
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_count(result: Any) -> int:
    try:
        return max(int(result.rowcount or 0), 0)
    except (TypeError, ValueError):
        return 0


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _count_export_section(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        return sum(len(item) for item in value.values() if isinstance(item, list))
    return 0


class DataExporter:
    """Truthful PostgreSQL-backed export of the user's supported data."""

    SUPPORTED_DATA_TYPES = frozenset(
        {"memories", "conversations", "analytics", "audit_logs"}
    )

    _MEMORY_EXPORT_QUERIES: tuple[tuple[str, str], ...] = (
        (
            "memory_items",
            "SELECT memory_id, source, scope, kind, content, metadata, created_at, "
            "updated_at, expires_at FROM memory_items WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_event",
            "SELECT * FROM memory_event WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_assertion",
            "SELECT * FROM memory_assertion WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_episode",
            "SELECT * FROM memory_episode WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "profile_fact",
            "SELECT * FROM profile_fact WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_entity",
            "SELECT * FROM memory_entity WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_entity_alias",
            "SELECT * FROM memory_entity_alias WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_relation",
            "SELECT * FROM memory_relation WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "memory_procedure",
            "SELECT * FROM memory_procedure WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at",
        ),
        (
            "consent_scope",
            "SELECT * FROM consent_scope WHERE tenant_id = CAST(:tenant_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) ORDER BY granted_at",
        ),
    )

    def __init__(self, db_client: Optional[MultiTenantPostgresClient] = None) -> None:
        self.db_client = db_client or MultiTenantPostgresClient()
        self.pii_detector = PIIDetector()

    @classmethod
    def normalize_data_types(cls, data_types: Optional[List[str]]) -> List[str]:
        requested = [
            str(item).strip().lower()
            for item in (data_types or ["all"])
            if str(item).strip()
        ]
        if not requested or "all" in requested:
            return ["memories", "conversations", "analytics", "audit_logs"]
        unsupported = sorted(set(requested) - cls.SUPPORTED_DATA_TYPES)
        if unsupported:
            raise ValueError("Unsupported export data types: " + ", ".join(unsupported))
        return list(dict.fromkeys(requested))

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.pii_detector.anonymize_text(value)
        if isinstance(value, dict):
            return {str(key): self._redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    async def export_user_data(
        self,
        user_id: str,
        tenant_id: str,
        data_types: Optional[List[str]] = None,
        export_format: DataExportFormat = DataExportFormat.JSON,
        include_pii: bool = False,
    ) -> Dict[str, Any]:
        if export_format != DataExportFormat.JSON:
            raise ValueError("Only JSON privacy exports are currently implemented")
        selected = self.normalize_data_types(data_types)
        payload: Dict[str, Any] = {
            "export_metadata": {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "export_date": datetime.utcnow().isoformat(),
                "export_format": export_format.value,
                "data_types": selected,
                "includes_pii": include_pii,
            },
            "data": {},
        }

        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            if "memories" in selected:
                payload["data"]["memories"] = await self._export_memories(
                    session, user_id, tenant_id, include_pii
                )
            if "conversations" in selected:
                payload["data"]["conversations"] = await self._export_conversations(
                    session, user_id, tenant_id, include_pii
                )
            if "analytics" in selected:
                payload["data"]["analytics"] = await self._export_analytics(
                    session, user_id, tenant_id
                )
            if "audit_logs" in selected:
                payload["data"]["audit_logs"] = await self._export_audit_logs(
                    session, user_id, tenant_id, include_pii
                )
        return payload

    async def _export_memories(
        self, session: Any, user_id: str, tenant_id: str, include_pii: bool
    ) -> Dict[str, List[Dict[str, Any]]]:
        params = {"tenant_id": tenant_id, "user_id": user_id}
        export: Dict[str, List[Dict[str, Any]]] = {}
        for name, query in self._MEMORY_EXPORT_QUERIES:
            result = await session.execute(text(query), params)
            records = [_jsonable(dict(row)) for row in result.mappings().all()]
            export[name] = records if include_pii else self._redact(records)
        return export

    async def _export_conversations(
        self, session: Any, user_id: str, tenant_id: str, include_pii: bool
    ) -> List[Dict[str, Any]]:
        params = {"tenant_id": tenant_id, "user_id": user_id}
        conversations_result = await session.execute(
            text(
                "SELECT conversation_id, title, conversation_metadata, is_active, "
                "created_at, updated_at, session_id, summary, tags "
                "FROM conversations WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at"
            ),
            params,
        )
        messages_result = await session.execute(
            text(
                "SELECT m.message_id, m.conversation_id, m.role, m.content, "
                "m.message_metadata, m.created_at FROM messages m "
                "JOIN conversations c ON c.conversation_id = m.conversation_id "
                "WHERE c.tenant_id = CAST(:tenant_id AS uuid) "
                "AND c.user_id = CAST(:user_id AS uuid) ORDER BY m.created_at"
            ),
            params,
        )
        by_conversation: Dict[str, List[Dict[str, Any]]] = {}
        for row in messages_result.mappings().all():
            message = _jsonable(dict(row))
            if not include_pii:
                message = self._redact(message)
            key = str(message.get("conversation_id"))
            by_conversation.setdefault(key, []).append(message)

        conversations: List[Dict[str, Any]] = []
        for row in conversations_result.mappings().all():
            conversation = _jsonable(dict(row))
            if not include_pii:
                conversation = self._redact(conversation)
            key = str(conversation.get("conversation_id"))
            conversation["messages"] = by_conversation.get(key, [])
            conversations.append(conversation)
        return conversations

    async def _export_analytics(
        self, session: Any, user_id: str, tenant_id: str
    ) -> Dict[str, int]:
        result = await session.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM memory_items WHERE tenant_id = CAST(:tenant_id AS uuid) "
                " AND user_id = CAST(:user_id AS uuid)) AS memory_items, "
                "(SELECT count(*) FROM memory_event WHERE tenant_id = CAST(:tenant_id AS uuid) "
                " AND user_id = CAST(:user_id AS uuid)) AS memory_events, "
                "(SELECT count(*) FROM conversations WHERE tenant_id = CAST(:tenant_id AS uuid) "
                " AND user_id = CAST(:user_id AS uuid)) AS conversations, "
                "(SELECT count(*) FROM messages m JOIN conversations c "
                " ON c.conversation_id = m.conversation_id "
                " WHERE c.tenant_id = CAST(:tenant_id AS uuid) "
                " AND c.user_id = CAST(:user_id AS uuid)) AS messages"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        row = result.mappings().one()
        return {key: int(value or 0) for key, value in row.items()}

    async def _export_audit_logs(
        self, session: Any, user_id: str, tenant_id: str, include_pii: bool
    ) -> List[Dict[str, Any]]:
        result = await session.execute(
            text(
                "SELECT event_id, actor_type, action, resource_type, resource_id, details, created_at "
                "FROM audit_log WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid) ORDER BY created_at"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        records = [_jsonable(dict(row)) for row in result.mappings().all()]
        if not include_pii:
            for record in records:
                record["details"] = {"redacted": True}
        return records


class DataEraser:
    """Hard-delete only, using canonical PostgreSQL rows and real command counts."""

    SUPPORTED_DATA_TYPES = frozenset({"memories", "conversations"})

    def __init__(self, db_client: Optional[MultiTenantPostgresClient] = None) -> None:
        self.db_client = db_client or MultiTenantPostgresClient()

    @classmethod
    def normalize_data_types(cls, data_types: Optional[List[str]]) -> List[str]:
        requested = [
            str(item).strip().lower()
            for item in (data_types or ["all"])
            if str(item).strip()
        ]
        if not requested or "all" in requested:
            return ["memories", "conversations"]
        unsupported = sorted(set(requested) - cls.SUPPORTED_DATA_TYPES)
        if unsupported:
            raise ValueError(
                "Unsupported erasure data types: "
                + ", ".join(unsupported)
                + ". Supported: memories, conversations. Cache and audit retention are not silently claimed."
            )
        return list(dict.fromkeys(requested))

    async def erase_user_data(
        self,
        user_id: str,
        tenant_id: str,
        erasure_type: ErasureType,
        data_types: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if erasure_type != ErasureType.HARD_DELETE:
            raise ValueError(
                "Only hard_delete is implemented. soft_delete and anonymize fail closed until canonical support exists."
            )
        selected = self.normalize_data_types(data_types)
        results: Dict[str, Any] = {}
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            if "memories" in selected:
                results["memories"] = await self._erase_memories(
                    session, user_id=user_id, tenant_id=tenant_id
                )
            if "conversations" in selected:
                results["conversations"] = await self._erase_conversations(
                    session, user_id=user_id, tenant_id=tenant_id
                )
            await session.commit()

        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "erasure_type": erasure_type.value,
            "data_types": selected,
            "results": results,
            "completed_at": datetime.utcnow().isoformat(),
            "correlation_id": correlation_id,
            "retained": {
                "audit_logs": "retained for security/compliance; not advertised as erased",
                "cache": "not claimed erased because no canonical user-wide cache ownership contract exists",
            },
        }

    async def _erase_memories(
        self, session: Any, *, user_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        params = {"tenant_id": tenant_id, "user_id": user_id}
        counts: Dict[str, int] = {}
        operations: tuple[tuple[str, str], ...] = (
            (
                "reinforcement_event",
                "DELETE FROM reinforcement_event WHERE target_assertion_id IN ("
                "SELECT assertion_id FROM memory_assertion WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid))",
            ),
            (
                "contradiction_event",
                "DELETE FROM contradiction_event WHERE source_assertion_id IN ("
                "SELECT assertion_id FROM memory_assertion WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)) OR target_assertion_id IN ("
                "SELECT assertion_id FROM memory_assertion WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid))",
            ),
            (
                "memory_relation",
                "DELETE FROM memory_relation WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
            (
                "memory_entity_alias",
                "DELETE FROM memory_entity_alias WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
            (
                "memory_entity",
                "DELETE FROM memory_entity WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
            (
                "consent_scope",
                "DELETE FROM consent_scope WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
            (
                "memory_items",
                "DELETE FROM memory_items WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
            (
                "memory_event",
                "DELETE FROM memory_event WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)",
            ),
        )
        for table, statement in operations:
            counts[table] = _row_count(await session.execute(text(statement), params))

        return {
            "action": "hard_delete",
            "directly_deleted_records": sum(counts.values()),
            "by_table": counts,
            "cascade_includes": [
                "memory_assertion",
                "memory_episode",
                "profile_fact",
                "projection_status",
                "memory_procedure",
            ],
            "note": "memory_items deletion includes canonical pgvector embeddings",
        }

    async def _erase_conversations(
        self, session: Any, *, user_id: str, tenant_id: str
    ) -> Dict[str, Any]:
        params = {"tenant_id": tenant_id, "user_id": user_id}
        message_count_result = await session.execute(
            text(
                "SELECT count(*) FROM messages m JOIN conversations c "
                "ON c.conversation_id = m.conversation_id "
                "WHERE c.tenant_id = CAST(:tenant_id AS uuid) "
                "AND c.user_id = CAST(:user_id AS uuid)"
            ),
            params,
        )
        message_count = int(message_count_result.scalar_one() or 0)
        delete_result = await session.execute(
            text(
                "DELETE FROM conversations WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "AND user_id = CAST(:user_id AS uuid)"
            ),
            params,
        )
        conversation_count = _row_count(delete_result)
        return {
            "action": "hard_delete",
            "affected_records": conversation_count,
            "cascaded_messages": message_count,
            "cascade_includes": ["messages", "message_tools"],
        }


class PrivacyComplianceService:
    """Canonical durable privacy lifecycle service."""

    def __init__(self, db_client: Optional[MultiTenantPostgresClient] = None) -> None:
        self.db_client = db_client or MultiTenantPostgresClient()
        self.data_exporter = DataExporter(self.db_client)
        self.data_eraser = DataEraser(self.db_client)
        self.pii_detector = PIIDetector()
        self.audit_logger = get_audit_logger()

    async def create_privacy_request(
        self,
        *,
        request_type: str,
        user_id: str,
        tenant_id: str,
        data_types: Optional[List[str]] = None,
        export_format: Optional[DataExportFormat] = None,
        erasure_type: Optional[ErasureType] = None,
        correlation_id: Optional[str] = None,
    ) -> PrivacyRequest:
        request_type = request_type.strip().lower()
        if request_type not in {"export", "erasure"}:
            raise ValueError(f"Unsupported privacy request type: {request_type}")

        if request_type == "export":
            selected = self.data_exporter.normalize_data_types(data_types)
            selected_export_format = export_format or DataExportFormat.JSON
            if selected_export_format != DataExportFormat.JSON:
                raise ValueError("Only JSON privacy exports are currently implemented")
            selected_erasure_type: Optional[ErasureType] = None
        else:
            selected = self.data_eraser.normalize_data_types(data_types)
            selected_export_format = None
            selected_erasure_type = erasure_type or ErasureType.HARD_DELETE
            if selected_erasure_type != ErasureType.HARD_DELETE:
                raise ValueError(
                    "Only hard_delete erasure is currently implemented; unsupported modes fail closed"
                )

        request_id = str(uuid.uuid4())
        verification_token = secrets.token_urlsafe(32)
        token_hash = _token_hash(verification_token)
        created_at = datetime.utcnow()

        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            await session.execute(
                text(
                    "INSERT INTO privacy_requests ("
                    "request_id, tenant_id, user_id, request_type, status, data_types, "
                    "export_format, erasure_type, verification_token_hash, correlation_id, created_at, updated_at"
                    ") VALUES ("
                    "CAST(:request_id AS uuid), CAST(:tenant_id AS uuid), CAST(:user_id AS uuid), "
                    ":request_type, 'pending', CAST(:data_types AS jsonb), :export_format, :erasure_type, "
                    ":token_hash, :correlation_id, :created_at, :created_at)"
                ),
                {
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "request_type": request_type,
                    "data_types": json.dumps(selected),
                    "export_format": selected_export_format.value if selected_export_format else None,
                    "erasure_type": selected_erasure_type.value if selected_erasure_type else None,
                    "token_hash": token_hash,
                    "correlation_id": correlation_id,
                    "created_at": created_at,
                },
            )
            await session.commit()

        logger.info(
            "privacy.request.created",
            extra={
                "request_id": request_id,
                "request_type": request_type,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
            },
        )
        return PrivacyRequest(
            request_id=request_id,
            request_type=request_type,
            user_id=user_id,
            tenant_id=tenant_id,
            status=PrivacyRequestStatus.PENDING,
            created_at=created_at,
            data_types=selected,
            export_format=selected_export_format,
            erasure_type=selected_erasure_type,
            verification_token=verification_token,
            result_metadata={},
            correlation_id=correlation_id,
        )

    async def get_privacy_request_status(
        self, request_id: str, *, user_id: str, tenant_id: str
    ) -> Optional[PrivacyRequest]:
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            result = await session.execute(
                text(
                    "SELECT request_id, request_type, user_id, tenant_id, status, data_types, "
                    "export_format, erasure_type, result_metadata, error_message, correlation_id, "
                    "created_at, completed_at FROM privacy_requests "
                    "WHERE request_id = CAST(:request_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid)"
                ),
                {"request_id": request_id, "tenant_id": tenant_id, "user_id": user_id},
            )
            row = result.mappings().first()
        return self._request_from_row(row) if row else None

    async def process_privacy_request(
        self,
        request_id: str,
        *,
        verification_token: str,
        user_id: str,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        include_pii: bool = False,
    ) -> Dict[str, Any]:
        request, stored_hash = await self._load_for_processing(
            request_id=request_id, user_id=user_id, tenant_id=tenant_id
        )
        if request is None or stored_hash is None:
            raise KeyError("Privacy request not found")
        if not hmac.compare_digest(stored_hash, _token_hash(verification_token)):
            raise PermissionError("Invalid verification token")
        if request.status != PrivacyRequestStatus.PENDING:
            raise RuntimeError(f"Privacy request is not pending: {request.status.value}")

        claimed = await self._claim_request(
            request_id=request_id,
            user_id=user_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        )
        if not claimed:
            raise RuntimeError("Privacy request was already claimed or is no longer pending")

        try:
            if request.request_type == "export":
                result = await self.data_exporter.export_user_data(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    data_types=request.data_types,
                    export_format=request.export_format or DataExportFormat.JSON,
                    include_pii=include_pii,
                )
                result_metadata = {
                    "export_format": (request.export_format or DataExportFormat.JSON).value,
                    "data_types": request.data_types or [],
                    "record_counts": {
                        key: _count_export_section(value)
                        for key, value in result.get("data", {}).items()
                    },
                }
            elif request.request_type == "erasure":
                result = await self.data_eraser.erase_user_data(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    erasure_type=request.erasure_type or ErasureType.HARD_DELETE,
                    data_types=request.data_types,
                    correlation_id=correlation_id,
                )
                result_metadata = {
                    "erasure_type": (request.erasure_type or ErasureType.HARD_DELETE).value,
                    "data_types": request.data_types or [],
                    "results": result.get("results", {}),
                    "retained": result.get("retained", {}),
                }
            else:
                raise ValueError(f"Unsupported privacy request type: {request.request_type}")

            await self._complete_request(
                request_id=request_id,
                user_id=user_id,
                tenant_id=tenant_id,
                result_metadata=result_metadata,
            )
            self._audit(outcome="success", request=request, correlation_id=correlation_id)
            return result
        except Exception as exc:
            await self._fail_request(
                request_id=request_id,
                user_id=user_id,
                tenant_id=tenant_id,
                error_message=str(exc),
            )
            self._audit(
                outcome="failure",
                request=request,
                correlation_id=correlation_id,
                error_message=str(exc),
            )
            raise

    async def process_data_export_request(
        self,
        request_id: str,
        *,
        verification_token: str,
        user_id: str,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        include_pii: bool = False,
    ) -> Dict[str, Any]:
        return await self.process_privacy_request(
            request_id,
            verification_token=verification_token,
            user_id=user_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            include_pii=include_pii,
        )

    async def process_data_erasure_request(
        self,
        request_id: str,
        *,
        verification_token: str,
        user_id: str,
        tenant_id: str,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self.process_privacy_request(
            request_id,
            verification_token=verification_token,
            user_id=user_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
        )

    async def _load_for_processing(
        self, *, request_id: str, user_id: str, tenant_id: str
    ) -> tuple[Optional[PrivacyRequest], Optional[str]]:
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            result = await session.execute(
                text(
                    "SELECT request_id, request_type, user_id, tenant_id, status, data_types, "
                    "export_format, erasure_type, result_metadata, error_message, correlation_id, "
                    "created_at, completed_at, verification_token_hash FROM privacy_requests "
                    "WHERE request_id = CAST(:request_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid)"
                ),
                {"request_id": request_id, "tenant_id": tenant_id, "user_id": user_id},
            )
            row = result.mappings().first()
        if not row:
            return None, None
        return self._request_from_row(row), str(row["verification_token_hash"])

    async def _claim_request(
        self,
        *,
        request_id: str,
        user_id: str,
        tenant_id: str,
        correlation_id: Optional[str],
    ) -> bool:
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            result = await session.execute(
                text(
                    "UPDATE privacy_requests SET status = 'in_progress', verification_used_at = now(), "
                    "updated_at = now(), correlation_id = COALESCE(:correlation_id, correlation_id) "
                    "WHERE request_id = CAST(:request_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid) AND status = 'pending'"
                ),
                {
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                },
            )
            await session.commit()
            return _row_count(result) == 1

    async def _complete_request(
        self,
        *,
        request_id: str,
        user_id: str,
        tenant_id: str,
        result_metadata: Dict[str, Any],
    ) -> None:
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            result = await session.execute(
                text(
                    "UPDATE privacy_requests SET status = 'completed', completed_at = now(), updated_at = now(), "
                    "result_metadata = CAST(:result_metadata AS jsonb), error_message = NULL "
                    "WHERE request_id = CAST(:request_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid) AND status = 'in_progress'"
                ),
                {
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "result_metadata": json.dumps(_jsonable(result_metadata)),
                },
            )
            if _row_count(result) != 1:
                raise RuntimeError("Failed to persist completed privacy request state")
            await session.commit()

    async def _fail_request(
        self,
        *,
        request_id: str,
        user_id: str,
        tenant_id: str,
        error_message: str,
    ) -> None:
        safe_error = (error_message or "privacy processing failed")[:1000]
        async with self.db_client.get_async_session() as session:
            await _set_request_scope(session, tenant_id=tenant_id, user_id=user_id)
            await session.execute(
                text(
                    "UPDATE privacy_requests SET status = 'failed', completed_at = now(), updated_at = now(), "
                    "error_message = :error_message WHERE request_id = CAST(:request_id AS uuid) "
                    "AND tenant_id = CAST(:tenant_id AS uuid) "
                    "AND user_id = CAST(:user_id AS uuid) AND status = 'in_progress'"
                ),
                {
                    "request_id": request_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "error_message": safe_error,
                },
            )
            await session.commit()

    @staticmethod
    def _request_from_row(row: Any) -> PrivacyRequest:
        data_types = row.get("data_types") or []
        if isinstance(data_types, str):
            data_types = json.loads(data_types)
        result_metadata = row.get("result_metadata") or {}
        if isinstance(result_metadata, str):
            result_metadata = json.loads(result_metadata)
        return PrivacyRequest(
            request_id=str(row["request_id"]),
            request_type=str(row["request_type"]),
            user_id=str(row["user_id"]),
            tenant_id=str(row["tenant_id"]),
            status=PrivacyRequestStatus(str(row["status"])),
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
            data_types=list(data_types),
            export_format=(
                DataExportFormat(str(row["export_format"]))
                if row.get("export_format")
                else None
            ),
            erasure_type=(
                ErasureType(str(row["erasure_type"]))
                if row.get("erasure_type")
                else None
            ),
            result_metadata=dict(result_metadata),
            error_message=row.get("error_message"),
            correlation_id=row.get("correlation_id"),
        )

    def _audit(
        self,
        *,
        outcome: str,
        request: PrivacyRequest,
        correlation_id: Optional[str],
        error_message: Optional[str] = None,
    ) -> None:
        payload = {
            "event_type": "privacy_request_processed",
            "severity": "info" if outcome == "success" else "error",
            "message": f"privacy_{request.request_type}_{outcome}",
            "user_id": request.user_id,
            "tenant_id": request.tenant_id,
            "correlation_id": correlation_id,
            "metadata": {
                "request_id": request.request_id,
                "request_type": request.request_type,
                "data_types": request.data_types,
                "outcome": outcome,
                **({"error_message": error_message[:500]} if error_message else {}),
            },
        }
        try:
            self.audit_logger.log_audit_event(payload)
        except Exception:
            logger.exception(
                "privacy.audit.emit_failed", extra={"request_id": request.request_id}
            )

    async def health(self) -> Dict[str, Any]:
        try:
            async with self.db_client.get_async_session() as session:
                await session.execute(text("SELECT 1 FROM privacy_requests LIMIT 1"))
            database_ready = True
        except Exception as exc:
            logger.warning("Privacy lifecycle database preflight failed: %s", exc)
            database_ready = False
        return {
            "status": "healthy" if database_ready else "unavailable",
            "database_ready": database_ready,
            "durable_requests": database_ready,
            "self_service": True,
            "supported_export_formats": [DataExportFormat.JSON.value],
            "supported_erasure_types": [ErasureType.HARD_DELETE.value],
            "supported_erasure_data_types": sorted(DataEraser.SUPPORTED_DATA_TYPES),
            "cache_erasure": False,
            "audit_log_erasure": False,
        }

    def sanitize_content_for_ui(self, content: str, max_length: int = 100) -> str:
        if not content:
            return ""
        metadata = self.pii_detector.extract_safe_metadata(content)
        if metadata["contains_pii"]:
            return (
                f"[Content contains PII - {metadata['word_count']} words, "
                f"{metadata['text_length']} chars]"
            )
        return content if len(content) <= max_length else content[:max_length] + "..."

    def create_safe_content_preview(
        self, content: str, max_length: int = 100
    ) -> Dict[str, Any]:
        metadata = self.pii_detector.extract_safe_metadata(content)
        return {
            "safe_preview": self.sanitize_content_for_ui(content, max_length=max_length),
            "metadata": metadata,
            "full_content_available": True,
            "pii_protection_applied": metadata["contains_pii"],
        }


_privacy_service: Optional[PrivacyComplianceService] = None


def get_privacy_compliance_service() -> PrivacyComplianceService:
    global _privacy_service
    if _privacy_service is None:
        _privacy_service = PrivacyComplianceService()
    return _privacy_service


__all__ = [
    "PrivacyComplianceService",
    "DataExporter",
    "DataEraser",
    "PIIDetector",
    "PrivacyRequest",
    "DataExportFormat",
    "ErasureType",
    "PrivacyRequestStatus",
    "get_privacy_compliance_service",
]
