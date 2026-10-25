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
