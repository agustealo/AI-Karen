from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/services/privacy_compliance.py"
ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/privacy.py"
MIGRATION = ROOT / "supabase/migrations/20260920010000_15_privacy_request_lifecycle.sql"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_source(path: Path, class_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Class {class_name} not found in {path}")


def _function_node(path: Path, function_name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(_source(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f"Function {function_name} not found in {path}")


def _parameter_annotation(path: Path, function_name: str, parameter_name: str) -> str:
    function = _function_node(path, function_name)
    for argument in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
        if argument.arg == parameter_name:
            assert argument.annotation is not None
            return ast.unparse(argument.annotation)
    raise AssertionError(
        f"Parameter {parameter_name} not found in function {function_name} in {path}"
    )


def _parameter_names(path: Path, function_name: str) -> set[str]:
    function = _function_node(path, function_name)
    return {
        argument.arg
        for argument in [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ]
    }


def test_privacy_requests_are_migration_owned_and_self_scoped() -> None:
    migration = _source(MIGRATION)

    assert "CREATE TABLE IF NOT EXISTS public.privacy_requests" in migration
    assert "verification_token_hash char(64) NOT NULL" in migration
    assert "verification_used_at" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "app.current_tenant_id" in migration
    assert "app.current_user_id" in migration
    assert "verification_token text" not in migration.lower()


def test_consumer_privacy_routes_derive_identity_from_auth_context() -> None:
    route = _source(ROUTE)
    export_model = _class_source(ROUTE, "DataExportRequest")
    erasure_model = _class_source(ROUTE, "DataErasureRequest")

    assert "Depends(get_current_user)" in route
    assert "check_scope" not in route
    assert "admin:read" not in route
    assert "admin:write" not in route
    assert "user_id" not in export_model
    assert "tenant_id" not in export_model
    assert "user_id" not in erasure_model
    assert "tenant_id" not in erasure_model
    assert 'estimated_completion="24-48 hours"' not in route


def test_privacy_request_ids_are_uuid_validated_at_fastapi_ingress() -> None:
    assert (
        _parameter_annotation(ROUTE, "get_privacy_request_status", "request_id")
        == "uuid.UUID"
    )
    assert (
        _parameter_annotation(ROUTE, "process_privacy_request", "request_id")
        == "uuid.UUID"
    )

    route = _source(ROUTE)
    assert "get_privacy_request_status(\n            str(request_id)," in route
    assert "process_privacy_request(\n            str(request_id)," in route


def test_sensitive_sanitizer_content_is_request_body_only() -> None:
    sanitize_model = _class_source(ROUTE, "ContentSanitizeRequest")
    parameters = _parameter_names(ROUTE, "sanitize_content")

    assert "class ContentSanitizeRequest(BaseModel)" in sanitize_model
    assert "content: str = Field(..., min_length=1)" in sanitize_model
    assert "max_length: int = Field(default=100, ge=1)" in sanitize_model
    assert _parameter_annotation(ROUTE, "sanitize_content", "request_data") == (
        "ContentSanitizeRequest"
    )
    assert "request_data" in parameters
    assert "content" not in parameters
    assert "max_length" not in parameters

    route = _source(ROUTE)
    assert "request_data.content" in route
    assert "max_length=request_data.max_length" in route


def test_privacy_service_has_no_simulated_erasure_or_retired_vector_store() -> None:
    service = _source(SERVICE)
    forbidden = (
        "Milvus",
        "affected_count = 5",
        "affected_count = 3",
        "affected_count = 8",
        "affected_count = 15",
        "affected_keys = 12",
        "self.privacy_requests: Dict",
        '"mode": "simulated"',
    )
    for token in forbidden:
        assert token not in service

    assert "hmac.compare_digest" in service
    assert "verification_token_hash" in service
    assert "set_config('app.current_tenant_id'" in service
    assert "set_config('app.current_user_id'" in service


def test_name_and_address_pii_are_redacted_from_default_safe_surfaces() -> None:
    from ai_karen_engine.services.privacy_compliance import (
        DataExporter,
        PIIDetector,
        PrivacyComplianceService,
    )

    content = "John Smith lives at 123 Main Street"
    detector = PIIDetector()

    detected = detector.detect_pii(content)
    assert "John Smith" in detected["name"]
    assert detected["address"] == ["123 Main Street"]
    assert detector.anonymize_text(content) == (
        "[NAME_ANONYMIZED] lives at [ADDRESS_ANONYMIZED]"
    )

    exporter = DataExporter(db_client=object())
    redacted = exporter._redact({"content": content})
    assert redacted == {
        "content": "[NAME_ANONYMIZED] lives at [ADDRESS_ANONYMIZED]"
    }

    service = PrivacyComplianceService.__new__(PrivacyComplianceService)
    service.pii_detector = detector
    preview = service.create_safe_content_preview(content)
    assert preview["pii_protection_applied"] is True
    assert preview["metadata"]["pii_types"] == ["address", "name"]
    assert "John Smith" not in preview["safe_preview"]
    assert "123 Main Street" not in preview["safe_preview"]


def test_memory_erasure_covers_canonical_projection_closure() -> None:
    service = _source(SERVICE)
    required_tables = {
        "memory_items",
        "memory_event",
        "memory_assertion",
        "memory_episode",
        "profile_fact",
        "memory_relation",
        "memory_entity",
        "memory_entity_alias",
        "memory_procedure",
        "reinforcement_event",
        "contradiction_event",
        "projection_status",
        "consent_scope",
    }
    for table in required_tables:
        assert table in service, f"privacy memory closure is missing {table}"

    assert "pgvector embeddings" in service
    assert '"cache_erasure": False' in service
    assert '"audit_log_erasure": False' in service


def test_erasure_modes_and_unsupported_data_fail_closed() -> None:
    from ai_karen_engine.services.privacy_compliance import DataEraser, ErasureType

    assert DataEraser.normalize_data_types(["all"]) == ["memories", "conversations"]
    with pytest.raises(ValueError, match="Unsupported erasure data types"):
        DataEraser.normalize_data_types(["cache"])

    service = _source(SERVICE)
    assert "if erasure_type != ErasureType.HARD_DELETE" in service
    assert "soft_delete and anonymize fail closed" in service


@pytest.mark.asyncio
async def test_destructive_erasure_and_completion_share_one_database_transaction() -> None:
    from ai_karen_engine.services.privacy_compliance import (
        ErasureType,
        PrivacyComplianceService,
        PrivacyRequest,
        PrivacyRequestStatus,
    )

    class RowCountResult:
        rowcount = 1

    class RecordingSession:
        def __init__(self, session_id: int) -> None:
            self.session_id = session_id
            self.events: list[tuple[str, str]] = []

        async def execute(self, statement: Any, params: Any = None) -> RowCountResult:
            del params
            self.events.append(("execute", str(statement)))
            return RowCountResult()

        async def commit(self) -> None:
            self.events.append(("commit", ""))

    class SessionContext:
        def __init__(self, session: RecordingSession) -> None:
            self.session = session

        async def __aenter__(self) -> RecordingSession:
            return self.session

        async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            del exc_type, exc, traceback

    class RecordingDbClient:
        def __init__(self) -> None:
            self.sessions: list[RecordingSession] = []

        def get_async_session(self) -> SessionContext:
            session = RecordingSession(len(self.sessions) + 1)
            self.sessions.append(session)
            return SessionContext(session)

    class RecordingEraser:
        def __init__(self) -> None:
            self.session_ids: list[int] = []

        async def erase_user_data_in_session(
            self,
            session: RecordingSession,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del kwargs
            self.session_ids.append(session.session_id)
            session.events.append(("erase", "destructive user data deletion"))
            return {
                "results": {"memories": {"directly_deleted_records": 1}},
                "retained": {"audit_logs": "retained", "cache": "not claimed erased"},
            }

    class RecordingAuditLogger:
        def log_audit_event(self, payload: dict[str, Any]) -> None:
            del payload

    db_client = RecordingDbClient()
    eraser = RecordingEraser()
    service = PrivacyComplianceService.__new__(PrivacyComplianceService)
    service.db_client = db_client
    service.data_eraser = eraser
    service.audit_logger = RecordingAuditLogger()

    request = PrivacyRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        request_type="erasure",
        user_id="22222222-2222-4222-8222-222222222222",
        tenant_id="33333333-3333-4333-8333-333333333333",
        status=PrivacyRequestStatus.PENDING,
        created_at=datetime.utcnow(),
        data_types=["memories"],
        erasure_type=ErasureType.HARD_DELETE,
    )

    await service._process_erasure_atomically(
        request=request,
        user_id=request.user_id,
        tenant_id=request.tenant_id,
        correlation_id="privacy-atomicity-test",
    )

    assert len(db_client.sessions) == 1
    session = db_client.sessions[0]
    assert eraser.session_ids == [session.session_id]

    erase_index = next(index for index, event in enumerate(session.events) if event[0] == "erase")
    complete_index = next(
        index
        for index, event in enumerate(session.events)
        if event[0] == "execute" and "status = 'completed'" in event[1]
    )
    commit_indexes = [
        index for index, event in enumerate(session.events) if event[0] == "commit"
    ]

    assert len(commit_indexes) == 1
    assert erase_index < complete_index < commit_indexes[0]
    assert commit_indexes[0] == len(session.events) - 1


def test_only_real_database_row_counts_are_reported() -> None:
    service = _source(SERVICE)
    eraser = _class_source(SERVICE, "DataEraser")

    assert "_row_count(await session.execute" in eraser
    assert "sum(counts.values())" in eraser
    assert "cascaded_messages" in eraser
    assert "return 5" not in service
    assert "return 3" not in service
    assert "return 8" not in service
    assert "return 12" not in service
    assert "return 15" not in service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "expected_status", "expected_detail"),
    [
        ("permission", 403, "Privacy request access denied"),
        ("validation", 422, "Invalid privacy request"),
        ("conflict", 409, "Privacy request conflict"),
        ("not_found", 404, "Privacy request not found"),
        ("sql", 500, "Privacy operation failed"),
        ("known_permission", 403, "Invalid verification token"),
        ("known_conflict", 409, "Privacy request was already claimed or is no longer pending"),
        ("known_validation", 422, "Only JSON privacy exports are currently implemented"),
    ],
)
async def test_privacy_http_errors_redact_untrusted_exception_text(
    caplog: pytest.LogCaptureFixture,
    exception: str,
    expected_status: int,
    expected_detail: str,
) -> None:
    import logging
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.exc import StatementError

    from ai_karen_engine.api_routes.auth import privacy

    secret = "SECRET_PRIVACY_SQL_PARAMETER"
    injected = StatementError(
        "private", "SELECT :sensitive", {"sensitive": secret},
        RuntimeError("secret database driver"),
    )
    failures: dict[str, Exception] = {
        "permission": PermissionError(secret),
        "validation": ValueError(secret),
        "conflict": RuntimeError(secret),
        "not_found": KeyError(secret),
        "sql": injected,
        "known_permission": PermissionError("Invalid verification token"),
        "known_conflict": RuntimeError(
            "Privacy request was already claimed or is no longer pending"
        ),
        "known_validation": ValueError("Only JSON privacy exports are currently implemented"),
    }

    class RejectingPrivacy:
        async def create_privacy_request(self, **_kwargs: Any) -> None:
            raise failures[exception]

    app = FastAPI()
    app.include_router(privacy.router)
    app.dependency_overrides[privacy.get_current_user] = lambda: SimpleNamespace(
        user_id="11111111-1111-4111-8111-111111111111",
        tenant_id="22222222-2222-4222-8222-222222222222",
    )
    app.dependency_overrides[privacy.get_privacy_service] = RejectingPrivacy
    with caplog.at_level(logging.ERROR, logger=privacy.__name__):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/privacy/export/request", json={})
    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    for token in (secret, "SELECT :sensitive", "secret database driver"):
        assert token not in response.text + caplog.text
    assert all(
        record.exc_info is None for record in caplog.records
        if record.name == privacy.__name__
    )


@pytest.mark.asyncio
async def test_privacy_status_readback_redacts_legacy_persisted_sql_text() -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from ai_karen_engine.api_routes.auth import privacy
    from ai_karen_engine.services.privacy_compliance import (
        PrivacyComplianceService, PrivacyRequestStatus,
    )

    secret = "OLD_STORED_PRIVATE_SQL_PARAMETER"
    request_id = uuid4()

    class LegacyService:
        async def get_privacy_request_status(
            self, _request_id: str, **_kwargs: Any,
        ) -> SimpleNamespace:
            return SimpleNamespace(
                request_id=str(request_id), status=PrivacyRequestStatus.FAILED,
                request_type="export", data_types=["memories"],
                created_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                result_metadata={}, error_message=secret,
            )

    app = FastAPI()
    app.include_router(privacy.router)
    app.dependency_overrides[privacy.get_current_user] = lambda: SimpleNamespace(
        user_id="11111111-1111-4111-8111-111111111111",
        tenant_id="22222222-2222-4222-8222-222222222222",
    )
    app.dependency_overrides[privacy.get_privacy_service] = LegacyService
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.get(f"/privacy/request/{request_id}/status")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_message"] == "Privacy request processing failed"
    assert secret not in response.text
    row = {
        "request_id": str(request_id), "request_type": "export",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "tenant_id": "22222222-2222-4222-8222-222222222222",
        "status": "failed", "data_types": ["memories"],
        "created_at": datetime.utcnow(), "completed_at": datetime.utcnow(),
        "result_metadata": {}, "error_message": secret,
    }
    hydrated = PrivacyComplianceService._request_from_row(row)
    assert hydrated.error_message == "Privacy request processing failed"
    assert secret not in repr(hydrated)


@pytest.mark.asyncio
async def test_privacy_failed_erasure_persists_only_fixed_reason_and_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging
    from types import SimpleNamespace

    from sqlalchemy.exc import StatementError

    from ai_karen_engine.services.privacy_compliance import (
        ErasureType, PrivacyComplianceService, PrivacyRequest,
        PrivacyRequestStatus,
    )

    secret = "PRIVATE_ERASURE_BOUND_SQL"
    sql_error = StatementError(
        "sensitive operation", "SELECT :secret", {"secret": secret},
        RuntimeError("private SQL driver"),
    )
    statements: list[tuple[str, dict[str, Any]]] = []
    audits: list[dict[str, Any]] = []
    commits = 0

    class Session:
        async def execute(self, query: Any, params: Any = None) -> Any:
            statements.append((str(query), dict(params or {})))
            return SimpleNamespace(rowcount=1)

        async def commit(self) -> None:
            nonlocal commits
            commits += 1

    class SessionContext:
        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_args: Any) -> None:
            return None

    class Database:
        def get_async_session(self) -> SessionContext:
            return SessionContext()

    class FaultyEraser:
        async def erase_user_data_in_session(self, *_args: Any, **_kwargs: Any) -> None:
            raise sql_error

    class AuditLogger:
        def log_audit_event(self, event: dict[str, Any]) -> None:
            audits.append(event)

    service = PrivacyComplianceService.__new__(PrivacyComplianceService)
    service.db_client = Database()
    service.data_eraser = FaultyEraser()
    service.audit_logger = AuditLogger()
    request = PrivacyRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        request_type="erasure",
        user_id="22222222-2222-4222-8222-222222222222",
        tenant_id="33333333-3333-4333-8333-333333333333",
        status=PrivacyRequestStatus.PENDING,
        created_at=datetime.utcnow(), data_types=["memories"],
        erasure_type=ErasureType.HARD_DELETE,
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(StatementError):
            await service._process_erasure_atomically(
                request=request, user_id=request.user_id,
                tenant_id=request.tenant_id, correlation_id="privacy-failure-test",
            )
    failures = [
        params for query, params in statements if "SET status = 'failed'" in query
    ]
    assert len(failures) == 1
    assert failures[0]["user_id"] == request.user_id
    assert failures[0]["tenant_id"] == request.tenant_id
    assert failures[0]["error_message"] == "Privacy request processing failed"
    assert commits == 1
    assert len(audits) == 1
    assert audits[0]["metadata"]["error_message"] == "Privacy request processing failed"
    for serialized in (repr(statements), repr(audits), caplog.text):
        for token in (secret, "SELECT :secret", "private SQL driver"):
            assert token not in serialized
