"""Repository search cursor and literal query boundary regressions."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.services.database.repositories.supabase_artifact_store import (
    SupabaseArtifactStore,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OWNER = "22222222-2222-4222-8222-222222222222"
FILE = "33333333-3333-4333-8333-333333333333"


def test_search_cursor_is_bound_to_query_and_scope():
    artifact = SimpleNamespace(id=FILE, created_at=datetime.now(timezone.utc))
    store = SupabaseArtifactStore
    cursor = store._encode_owner_cursor(artifact, TENANT, OWNER, search="report")
    assert store._decode_owner_cursor(cursor, TENANT, OWNER, search="report") == (
        artifact.created_at, FILE,
    )
    for tenant, owner, query in [
        (TENANT, OWNER, ""),
        (TENANT, OWNER, "other"),
        (OWNER, OWNER, "report"),
        (TENANT, TENANT, "report"),
    ]:
        with pytest.raises(ValueError, match="artifact_owner_cursor_invalid"):
            store._decode_owner_cursor(cursor, tenant, owner, search=query)
    legacy = store._encode_owner_cursor(artifact, TENANT, OWNER)
    assert store._decode_owner_cursor(legacy, TENANT, OWNER) == (
        artifact.created_at, FILE,
    )
    with pytest.raises(ValueError):
        store._decode_owner_cursor(legacy, TENANT, OWNER, search="report")


@pytest.mark.parametrize("value", [123, "x" * 161, "bad\x00query", "bad\nquery"])
def test_invalid_search_rejected(value):
    with pytest.raises(ValueError, match="artifact_owner_search_invalid"):
        SupabaseArtifactStore._normalize_owner_search(value)


@pytest.mark.asyncio
async def test_search_is_bound_and_owner_filtered_before_pagination():
    session = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    session.execute.return_value = result
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    store = SupabaseArtifactStore(lambda: context, None)
    query = "%_';--"
    response = await store.list_owner_artifacts_page(TENANT, OWNER, limit=2, search=query)
    assert response.success
    statement, params = session.execute.await_args.args
    sql = str(statement)
    assert query not in sql
    assert params == {"tenant_id": TENANT, "user_id": OWNER, "page_limit": 3, "search": query}
    assert "tenant_id = :tenant_id" in sql
    assert "owner_user_id = :user_id" in sql
    assert "deleted_at IS NULL" in sql
    assert sql.index("strpos(lower(name), lower(:search))") < sql.index("LIMIT :page_limit")


@pytest.mark.parametrize("folder_id", [None, "44444444-4444-4444-8444-444444444444"])
def test_folder_search_cursor_is_bound_to_parent_query_and_mode(folder_id):
    artifact = SimpleNamespace(id=FILE, created_at=datetime.now(timezone.utc))
    store = SupabaseArtifactStore
    options = dict(folder_scoped=True, folder_id=folder_id, search="report")
    cursor = store._encode_owner_cursor(artifact, TENANT, OWNER, **options)
    assert store._decode_owner_cursor(cursor, TENANT, OWNER, **options) == (
        artifact.created_at, FILE,
    )
    for changes in (
        {"search": ""},
        {"search": "other"},
        {"folder_id": "55555555-5555-4555-8555-555555555555"},
        {"folder_scoped": False, "folder_id": None},
    ):
        with pytest.raises(ValueError, match="artifact_owner_cursor_invalid"):
            store._decode_owner_cursor(cursor, TENANT, OWNER, **{**options, **changes})
    unfiltered = store._encode_owner_cursor(
        artifact, TENANT, OWNER, folder_scoped=True, folder_id=folder_id,
    )
    assert store._decode_owner_cursor(
        unfiltered, TENANT, OWNER, folder_scoped=True, folder_id=folder_id,
    ) == (artifact.created_at, FILE)
    with pytest.raises(ValueError):
        store._decode_owner_cursor(unfiltered, TENANT, OWNER, **options)
