from __future__ import annotations

import json

from ai_karen_engine.core.intelligence.ml.training.workbench import (
    AdvancedTrainingWorkbench,
)


def _dataset(tmp_path):
    root = tmp_path / "datasets"
    root.mkdir()
    lines = []
    for index in range(20):
        lines.append(
            json.dumps({
                "example_id": str(index),
                "feature_version": "v1",
                "features": {"token_count": index + 1},
                "target": "high" if index >= 10 else "low",
            })
        )
    (root / "adaptive_v1.jsonl").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return root


def _preflight(service, **kwargs):
    config = {
        "engine": "sklearn",
        "task": "affect",
        "dataset_version": "adaptive_v1",
        "test_split": 0.2,
        "max_samples": 100,
        "seed": 42,
        "max_iter": 1000,
        "class_weight": "balanced",
        "optimizer": "lbfgs",
        "precision": "fp64",
    }
    config.update(kwargs)
    return service.preflight(**config)


def test_advanced_workbench_enumerates_real_versioned_datasets(tmp_path):
    service = AdvancedTrainingWorkbench(_dataset(tmp_path))
    catalog = service.catalog()

    assert catalog["datasets"][0]["version"] == "adaptive_v1"
    assert "affect" in catalog["tasks"]
    assert "preference" in catalog["tasks"]
    assert "outcome_forecast" in catalog["tasks"]
    assert catalog["configuration"]["engines_declare_support"] is True
    assert next(
        engine for engine in catalog["engines"] if engine["id"] == "transformers"
    )["supported"] is False


def test_advanced_preflight_checks_dataset_labels_and_features(tmp_path):
    service = AdvancedTrainingWorkbench(_dataset(tmp_path))
    result = _preflight(service)

    assert result["ready"] is True
    assert result["checks"] == []
    assert result["evidence"]["examples_scanned"] == 20
    assert result["evidence"]["feature_count"] == 1
    assert result["evidence"]["class_counts"] == {"low": 10, "high": 10}


def test_advanced_preflight_rejects_unsupported_engine(tmp_path):
    service = AdvancedTrainingWorkbench(_dataset(tmp_path))
    result = _preflight(service, engine="transformers", precision="bf16")

    assert result["ready"] is False
    assert {issue["code"] for issue in result["checks"]} >= {
        "unsupported_engine",
        "unsupported_precision",
    }


def test_advanced_preflight_rejects_traversal(tmp_path):
    service = AdvancedTrainingWorkbench(_dataset(tmp_path))
    result = _preflight(service, dataset_version="../secrets")

    assert result["ready"] is False
    assert "invalid_dataset_version" in {
        issue["code"] for issue in result["checks"]
    }


def test_advanced_preflight_rejects_bad_feature_contract(tmp_path):
    root = _dataset(tmp_path)
    path = root / "adaptive_v1.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    rows[2] = json.dumps({
        "example_id": "2",
        "feature_version": "v1",
        "features": {"different_feature": 3},
        "target": "low",
    })
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    service = AdvancedTrainingWorkbench(root)
    result = _preflight(service)

    assert result["ready"] is False
    assert "invalid_dataset_record" in {
        issue["code"] for issue in result["checks"]
    }


def test_advanced_preflight_requires_dataset_loader_fields(tmp_path):
    root = _dataset(tmp_path)
    path = root / "adaptive_v1.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    item = json.loads(rows[0])
    item.pop("feature_version")
    rows[0] = json.dumps(item)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = _preflight(AdvancedTrainingWorkbench(root))
    assert not result["ready"]
    assert "invalid_dataset_record" in {issue["code"] for issue in result["checks"]}


def test_preflight_rejects_singleton_class_that_executor_cannot_stratify(tmp_path):
    root = _dataset(tmp_path)
    path = root / "adaptive_v1.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["target"] = "common"
    rows[0]["target"] = "singleton"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    result = _preflight(AdvancedTrainingWorkbench(root))
    assert result["ready"] is False
    assert "rare_classes" in {check["code"] for check in result["checks"]}


def test_catalog_identifies_structural_dataset_engines(tmp_path):
    root = _dataset(tmp_path)
    (root / "text_v1.jsonl").write_text(
        "\\n".join(json.dumps({"text": f"example {index}", "label": "demo"}) for index in range(16)) + "\\n",
        encoding="utf-8",
    )
    catalog = AdvancedTrainingWorkbench(root).catalog()
    by_version = {item["version"]: item for item in catalog["datasets"]}
    assert by_version["adaptive_v1"]["schema_engines"] == ["sklearn"]
    assert by_version["adaptive_v1"]["inspection_status"] == "structural_only"
    assert by_version["text_v1"]["schema_engines"] == ["spacy", "transformers"]
    assert by_version["text_v1"]["inspection_status"] == "structural_only"


def test_catalog_does_not_mark_incomplete_or_bad_datasets_as_compatible(tmp_path):
    root = _dataset(tmp_path)
    (root / "bad.jsonl").write_text("{not json}\\n", encoding="utf-8")
    (root / "empty.jsonl").write_text("", encoding="utf-8")
    (root / "large.jsonl").write_text(
        "".join(json.dumps({"text": f"example {index}"}) + "\\n" for index in range(257)),
        encoding="utf-8",
    )
    by_version = {
        item["version"]: item for item in AdvancedTrainingWorkbench(root).catalog()["datasets"]
    }
    assert by_version["bad"]["inspection_status"] == "invalid"
    assert by_version["empty"]["inspection_status"] == "empty"
    assert by_version["large"]["inspection_status"] == "incomplete"
    for version in ("bad", "empty", "large"):
        assert by_version[version]["schema_engines"] == []
