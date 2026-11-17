"""Adversarial contracts for read-only model execution caller candidate inventory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.kchat_auth_05b2b_caller_census import SCHEMA, main, scan_sources


def test_census_records_direct_dynamic_and_constructor_candidates(tmp_path: Path):
    module = tmp_path / "a.py"
    module.write_text(
        "def run(manager, token):\n"
        "    manager.generate_chat([], execution_admission=token)\n"
        "    manager.generate_embedding('one')\n"
        "    manager.invoke_provider_sync(object(), 'input')\n"
        "    raw = OpenAICompatibleRuntimeClient(model='model-a', base_url='http://localhost')\n"
        "    getattr(manager, 'invoke_embedding')('content')\n"
        "    return raw\n",
        encoding="utf-8",
    )
    report = scan_sources(tmp_path)
    assert report["schema"] == SCHEMA
    assert report["scanned_python_files"] == 1
    assert report["candidate_total"] == 5
    assert not report["parse_errors"]
    assert [entry["method"] for entry in report["candidates"]] == [
        "generate_chat",
        "generate_embedding",
        "invoke_provider_sync",
        "OpenAICompatibleRuntimeClient",
        "invoke_embedding",
    ]
    assert report["candidates"][0]["execution_admission_keyword"] is True
    assert report["candidates"][1]["execution_admission_keyword"] is False
    assert report["candidates"][-1]["kind"] == "dynamic_attribute_lookup"
    assert all(entry["review_status"] == "unverified_candidate" for entry in report["candidates"])


def test_census_does_not_execute_scanned_modules_or_reveal_arguments(tmp_path: Path):
    (tmp_path / "unsafe.py").write_text(
        "raise RuntimeError('must never execute')\n"
        "def handler(manager):\n"
        "    manager.generate_chat('secret private prompt')\n",
        encoding="utf-8",
    )
    report = scan_sources(tmp_path)
    assert report["candidate_total"] == 1
    assert report["candidates"][0]["scope"] == "handler"
    assert "secret private prompt" not in json.dumps(report)


def test_census_keeps_parse_errors_and_does_not_guess_safety(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "safe.py").write_text(
        "def handler(admission):\n"
        "    admission.reserve_transport(endpoint, model='test')\n",
        encoding="utf-8",
    )
    report = scan_sources(tmp_path)
    assert report["scanned_python_files"] == 2
    assert len(report["parse_errors"]) == 1
    assert report["parse_errors"][0]["path"] == "broken.py"
    assert report["candidates"][0]["review_status"] == "unverified_candidate"
    assert report["candidates"][0]["category"] == "existing_admission"


def test_census_output_is_deterministic_and_cli_fails_on_parse_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    root = tmp_path / "source"
    root.mkdir()
    (root / "b.py").write_text("def f(a):\n    a.embed('x')\n", encoding="utf-8")
    (root / "a.py").write_text(
        "def g(a):\n    a.generate_chat([])\n", encoding="utf-8"
    )
    target = tmp_path / "out" / "census.json"
    assert main(["--root", str(root), "--output", str(target)]) == 0
    first = json.loads(target.read_text(encoding="utf-8"))
    assert [item["path"] for item in first["candidates"]] == ["a.py", "b.py"]
    assert "non-certifying" in capsys.readouterr().out
    assert main(["--root", str(root), "--output", str(target)]) == 0
    assert first == json.loads(target.read_text(encoding="utf-8"))
    (root / "syntax.py").write_text("def oops(:\n", encoding="utf-8")
    assert main(["--root", str(root), "--output", str(target)]) == 1
    assert json.loads(target.read_text(encoding="utf-8"))["parse_errors"]


def test_census_rejects_missing_root(tmp_path: Path):
    with pytest.raises(ValueError, match="Source root is not a directory"):
        scan_sources(tmp_path / "missing")
