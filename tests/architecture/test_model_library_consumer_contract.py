"""Authenticated model library must reuse the canonical scoped query."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_API = ROOT / "src/ai_karen_engine/api_routes/models/runtime_api.py"
REPOSITORY = ROOT / "src/ai_karen_engine/persistence/repositories/model_download_repository.py"


def test_model_library_enforces_authenticated_tenant_scope():
    source = RUNTIME_API.read_text(encoding="utf-8")
    assert '@router.get("/model-library/my-downloads")' in source
    assert "Depends(get_current_user)" in source
    assert 'getattr(current_user, "is_verified", False)' in source
    assert 'tenant_id == "default"' in source
    assert "list_owned_jobs(" in source
    assert "tenant_id=tenant_id, user_id=user_id" in source
    assert '"scope": "authenticated_user"' in source


def test_owner_query_filters_before_limit_and_redacts():
    source = REPOSITORY.read_text(encoding="utf-8")
    method = source.split("async def list_owned_jobs(", 1)[1].split(
        "async def get_job(", 1
    )[0]
    assert "WHERE tenant_id = :tenant_id AND requested_by = :user_id" in method
    assert "ORDER BY created_at DESC LIMIT :limit" in method
    for forbidden in ("install_path", "lease_token", "trust_remote_code",
                      "storage_key", "message, error"):
        assert forbidden not in method


def test_individual_job_contract_requires_sql_ownership_and_uniform_not_found():
    api = RUNTIME_API.read_text(encoding="utf-8")
    repository = REPOSITORY.read_text(encoding="utf-8")
    assert '@router.get("/model-library/my-downloads/{job_id}")' in api
    assert "get_owned_job(" in api
    assert 'detail="Model job unavailable"' in api
    query = repository.split("async def get_owned_job(", 1)[1].split(
        "async def get_job(", 1
    )[0]
    assert "job_id = :job_id AND tenant_id = :tenant_id" in query
    assert "AND requested_by = :user_id" in query
    for forbidden in ("install_path", "lease_token", "storage_key"):
        assert forbidden not in query



def test_owned_failure_diagnostic_is_shared_bounded_sql_and_not_raw_error():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert source.count("{_OWNED_FAILURE_CATEGORY_SQL}") == 2
    assert "_OWNED_FAILURE_CATEGORY_SQL = " in source
    for category in ("source_access", "network", "storage", "integrity", "unknown", "cancelled"):
        assert f"'{category}'" in source
    # Both methods must select a server-derived category without selecting
    # worker errors, messages, paths, or other private metadata.
    for method in ("list_owned_jobs", "get_owned_job"):
        query = source.split(f"async def {method}(", 1)[1].split(
            "    async def ", 1
        )[0]
        assert "{_OWNED_FAILURE_CATEGORY_SQL}" in query
        assert "SELECT job_id, model_id, revision, channel_id, status," in query
        assert "progress, created_at, updated_at," in query
        for forbidden in ("SELECT *", "error, ", "message, ", "install_path", "lease_token"):
            assert forbidden not in query


def test_owned_control_is_sql_atomic_and_preserves_existing_state_guards():
    source = REPOSITORY.read_text(encoding="utf-8")
    for action in ("cancel_job", "pause_job", "resume_job"):
        section = source.split(f"async def {action}(", 1)[1].split(
            "    async def ", 1
        )[0]
        assert "tenant_id: Optional[str] = None" in section
        assert "model_download_owner_scope_incomplete" in section
        assert "tenant_id = :tenant_id AND requested_by = :user_id" in section
        assert "RETURNING *" in section


def test_consumer_mutation_validates_identity_and_action():
    source = RUNTIME_API.read_text(encoding="utf-8")
    section = source.split("async def control_my_model_download(", 1)[1]
    assert 'action not in ("cancel", "pause", "resume")' in section
    assert "Depends(get_current_user)" in section
    assert 'getattr(current_user, "is_verified", False)' in section
    assert "control_owned_job(" in section
    assert "tenant_id=tenant_id, user_id=user_id" in section


def test_owned_model_library_service_unavailability_is_redacted_and_retryable():
    """Source contract: database outages are not misreported as access denial."""
    source = RUNTIME_API.read_text(encoding="utf-8")
    for event in (
        "model_library_owned_history_unavailable",
        "model_library_owned_job_unavailable",
        "model_library_owned_control_unavailable",
    ):
        assert event in source
    assert source.count("status_code=503") >= 3
    assert 'extra={"error_type": type(exc).__name__}' in source


def test_owned_model_library_unavailable_does_not_erase_scope_guards():
    source = RUNTIME_API.read_text(encoding="utf-8")
    assert source.count('not getattr(current_user, "is_verified", False)') >= 3
    assert source.count('tenant_id == "default"') >= 3
    assert source.count('except PermissionError as exc:') >= 3
    assert 'detail="Model library unavailable"' in source
    assert 'detail="Model job unavailable"' in source


async def _exercise_owned_job_route(method: str, actor):
    from ai_karen_engine.api_routes.models import runtime_api

    if method == "list":
        return await runtime_api.get_my_model_downloads(limit=200, current_user=actor)
    if method == "get":
        return await runtime_api.get_my_model_download(
            "mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335", current_user=actor
        )
    return await runtime_api.control_my_model_download(
        "mdl-a3478177-6f1a-4e99-ab3a-9f94dd73a335",
        "cancel",
        current_user=actor,
    )


def _model_library_actor(*, is_verified: bool = True):
    from types import SimpleNamespace

    return SimpleNamespace(
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        tenant_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        is_active=True,
        is_verified=is_verified,
    )


import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "get", "control"])
async def test_owned_model_library_service_failure_returns_redacted_503(
    monkeypatch, method
):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from ai_karen_engine.core.model_runtime import model_download_control_service as control

    secret = "private-db-password-do-not-expose"
    failure = RuntimeError(secret)
    fake = SimpleNamespace(
        list_owned_jobs=AsyncMock(side_effect=failure),
        get_owned_job=AsyncMock(side_effect=failure),
        control_owned_job=AsyncMock(side_effect=failure),
    )
    monkeypatch.setattr(control, "get_model_download_control_service", lambda: fake)

    with pytest.raises(HTTPException) as raised:
        await _exercise_owned_job_route(method, _model_library_actor())
    assert raised.value.status_code == 503
    assert secret not in str(raised.value.detail)
    assert "temporarily unavailable" in str(raised.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "expected_status"),
    [("list", 403), ("get", 404), ("control", 404)],
)
async def test_owned_model_library_permission_denial_preserves_uniform_status(
    monkeypatch, method, expected_status
):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from ai_karen_engine.core.model_runtime import model_download_control_service as control

    denied = PermissionError("foreign tenant row")
    fake = SimpleNamespace(
        list_owned_jobs=AsyncMock(side_effect=denied),
        get_owned_job=AsyncMock(side_effect=denied),
        control_owned_job=AsyncMock(side_effect=denied),
    )
    monkeypatch.setattr(control, "get_model_download_control_service", lambda: fake)

    with pytest.raises(HTTPException) as raised:
        await _exercise_owned_job_route(method, _model_library_actor())
    assert raised.value.status_code == expected_status
    assert "foreign tenant" not in str(raised.value.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list", "get", "control"])
async def test_owned_model_library_rejects_unverified_actor_before_lookup(
    method,
):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as raised:
        await _exercise_owned_job_route(
            method, _model_library_actor(is_verified=False)
        )
    assert raised.value.status_code == 403
