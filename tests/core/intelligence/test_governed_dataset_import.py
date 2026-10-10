from __future__ import annotations

import io
import json

import pytest

from ai_karen_engine.core.intelligence.ml.training.dataset_import import (
    DatasetImportError,
    import_jsonl_dataset,
)


def _import(root, tenant="tenant-a", version="v1", rows=None, max_bytes=1024):
    if rows is None:
        rows = [{"text": "first"}, {"text": "second"}]
    source = io.BytesIO(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
    return import_jsonl_dataset(
        root=root, tenant_id=tenant, version=version, source=source, max_bytes=max_bytes
    )


def test_import_is_immutable_and_scoped_by_tenant(tmp_path):
    first = _import(tmp_path)
    other = _import(tmp_path, tenant="tenant-b")
    assert first["rows"] == 2
    assert first["sha256"] == other["sha256"]
    assert first["tenant_key"] != other["tenant_key"]
    assert len(list(tmp_path.rglob("v1.jsonl"))) == 2
    with pytest.raises(DatasetImportError, match="already exists"):
        _import(tmp_path)
    assert len(list(tmp_path.rglob("v1.jsonl"))) == 2


@pytest.mark.parametrize("version", ["../x", ".", "..", "", "/root", "a/b"])
def test_import_rejects_invalid_versions(tmp_path, version):
    with pytest.raises(DatasetImportError):
        _import(tmp_path, version=version)


def test_import_fails_closed_without_partial_publication(tmp_path):
    with pytest.raises(DatasetImportError, match="record 2"):
        import_jsonl_dataset(
            source=io.BytesIO(b'{"text":"ok"}\n{bad}\n'),
            root=tmp_path, tenant_id="tenant-a", version="bad",
        )
    assert list(tmp_path.rglob("*.jsonl")) == []
    assert list(tmp_path.rglob(".incoming-*")) == []


def test_import_rejects_empty_and_oversized(tmp_path):
    with pytest.raises(DatasetImportError, match="empty"):
        import_jsonl_dataset(
            source=io.BytesIO(b""), root=tmp_path,
            tenant_id="tenant-a", version="empty",
        )
    with pytest.raises(DatasetImportError, match="exceeds import limit"):
        _import(tmp_path, max_bytes=8)
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_import_requires_explicit_tenant(tmp_path):
    for tenant in ("", "default"):
        with pytest.raises(DatasetImportError, match="tenant"):
            _import(tmp_path, tenant=tenant)


def test_tenant_catalog_uses_same_directory_as_import(tmp_path, monkeypatch):
    from ai_karen_engine.core.intelligence.ml.training import workbench as module
    from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench
    from ai_karen_engine.core.intelligence.ml.training.dataset_import import tenant_dataset_directory

    monkeypatch.setattr(module, "get_ml_registry_dir", lambda: str(tmp_path))
    root = tmp_path / "datasets"
    _import(root, tenant="tenant-a", version="private-a")
    _import(root, tenant="tenant-b", version="private-b")
    catalog_a = AdvancedTrainingWorkbench.for_tenant("tenant-a").catalog()
    catalog_b = AdvancedTrainingWorkbench.for_tenant("tenant-b").catalog()
    assert [d["version"] for d in catalog_a["datasets"]] == ["private-a"]
    assert [d["version"] for d in catalog_b["datasets"]] == ["private-b"]
    assert tenant_dataset_directory(root, "tenant-a") != tenant_dataset_directory(root, "tenant-b")
    with pytest.raises(DatasetImportError):
        AdvancedTrainingWorkbench.for_tenant("default")


def test_import_rejects_symlinked_dataset_root(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(DatasetImportError, match="symlinks"):
        _import(link)
    assert not list(real.rglob("*.jsonl"))


def test_import_rejects_nonfinite_json_and_cleans_up(tmp_path):
    with pytest.raises(DatasetImportError, match="invalid JSON value"):
        import_jsonl_dataset(
            source=io.BytesIO(b'{"value":NaN}\n'),
            root=tmp_path, tenant_id="tenant-a", version="not-finite",
        )
    assert list(tmp_path.rglob("*.jsonl")) == []
    assert list(tmp_path.rglob(".incoming-*")) == []
