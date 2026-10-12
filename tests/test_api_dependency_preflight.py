"""Read-only API preflight must probe actual imports rather than module discovery."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "api_dependency_preflight.py"
_spec = importlib.util.spec_from_file_location("api_dependency_preflight", _SCRIPT)
assert _spec is not None and _spec.loader is not None
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


def test_dependency_probe_rejects_broken_import(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "version", lambda _: "1.0")

    def broken(_module):
        raise ImportError("missing transitive dependency")

    monkeypatch.setattr(preflight.importlib, "import_module", broken)
    assert preflight.dependency("crawl4ai", "crawl4ai") is False
    record = json.loads(capsys.readouterr().out)
    assert record["module_available"] is False
    assert record["installed_version"] == "1.0"


def test_dependency_probe_accepts_successful_import(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "version", lambda _: "1.0")
    monkeypatch.setattr(preflight.importlib, "import_module", lambda _: object())
    assert preflight.dependency("crawl4ai", "crawl4ai") is True
    assert json.loads(capsys.readouterr().out)["module_available"] is True


def test_permissions_override_role_names_fail_closed(monkeypatch, tmp_path, capsys):
    file = tmp_path / "rbac.json"
    file.write_text(json.dumps({"roles": {"user": {"permissions": ["read", "admin"]}}}), encoding="utf-8")
    monkeypatch.setenv("KARI_PERMISSIONS_CONFIG", str(file))
    assert preflight.permissions() is False
    output = json.loads(capsys.readouterr().out)
    assert output["role_names_used_as_permissions"] == ["admin"]


def test_missing_permissions_override_does_not_succeed(monkeypatch, tmp_path):
    monkeypatch.setenv("KARI_PERMISSIONS_CONFIG", str(tmp_path / "missing.json"))
    assert preflight.permissions() is False
