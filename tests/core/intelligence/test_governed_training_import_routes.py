from __future__ import annotations

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.admin import training


@pytest.mark.asyncio
async def test_tenant_scoped_import_and_inventory(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "get_ml_registry_dir", lambda: str(tmp_path))
    tenant_a = {"tenant_id": "a", "user_id": "operator"}
    tenant_b = {"tenant_id": "b", "user_id": "operator"}
    body = training.DatasetImportRequest(
        version="custom-v1",
        content_jsonl='{"text": "example"}\n',
    )
    result = await training.import_scoped_training_dataset(body, current_user=tenant_a)
    assert result["version"] == "custom-v1"
    owned = await training.list_scoped_training_datasets(current_user=tenant_a)
    isolated = await training.list_scoped_training_datasets(current_user=tenant_b)
    assert [record["version"] for record in owned["datasets"]] == ["custom-v1"]
    assert isolated["datasets"] == []


@pytest.mark.asyncio
async def test_training_import_rejects_missing_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "get_ml_registry_dir", lambda: str(tmp_path))
    body = training.DatasetImportRequest(
        version="custom-v1", content_jsonl='{"text":"a"}\n',
    )
    with pytest.raises(HTTPException) as exc:
        await training.import_scoped_training_dataset(
            body, current_user={"tenant_id": "default", "user_id": "operator"},
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_training_import_rejects_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "get_ml_registry_dir", lambda: str(tmp_path))
    actor = {"tenant_id": "a", "user_id": "operator"}
    body = training.DatasetImportRequest(
        version="custom-v1", content_jsonl='{"text":"a"}\n',
    )
    await training.import_scoped_training_dataset(body, current_user=actor)
    with pytest.raises(HTTPException) as exc:
        await training.import_scoped_training_dataset(body, current_user=actor)
    assert exc.value.status_code == 422



@pytest.mark.asyncio
async def test_training_csv_import_uses_authenticated_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "get_ml_registry_dir", lambda: str(tmp_path))
    body = training.DatasetCSVImportRequest(
        version="csv-v1",
        content_csv="input,class\nhello,positive\nbye,negative\n",
        column_mapping={"input": "text", "class": "label"},
    )
    user = {"tenant_id": "tenant-a", "user_id": "operator"}
    result = await training.import_scoped_training_csv(body, current_user=user)
    assert result["rows"] == 2
    inventory = await training.list_scoped_training_datasets(current_user=user)
    assert [row["version"] for row in inventory["datasets"]] == ["csv-v1"]
    other = await training.list_scoped_training_datasets(
        current_user={"tenant_id": "tenant-b", "user_id": "operator"}
    )
    assert other["datasets"] == []


@pytest.mark.asyncio
async def test_training_csv_rejects_invalid_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "get_ml_registry_dir", lambda: str(tmp_path))
    body = training.DatasetCSVImportRequest(
        version="bad", content_csv="input\nvalue\n",
        column_mapping={"absent": "text"},
    )
    with pytest.raises(HTTPException) as error:
        await training.import_scoped_training_csv(
            body, current_user={"tenant_id": "tenant-a", "user_id": "operator"},
        )
    assert error.value.status_code == 422
