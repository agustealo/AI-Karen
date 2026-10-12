"""Regression tests for filesystem-backed extension package imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ai_karen_engine.extensions.platform.core.host.loader import ExtensionLoader


def _plugin(root: Path, name: str, value: str) -> Path:
    directory = root / name
    handlers = directory / "handlers"
    handlers.mkdir(parents=True)
    (handlers / "__init__.py").write_text(
        "from .clock import read_value\n", encoding="utf-8"
    )
    (handlers / "clock.py").write_text(
        f"def read_value():\n    return {value!r}\n", encoding="utf-8"
    )
    (directory / "handler.py").write_text(
        "from .handlers import read_value\n"
        "def execute():\n    return read_value()\n",
        encoding="utf-8",
    )
    return directory


def test_hyphenated_absolute_extension_supports_relative_imports(tmp_path: Path) -> None:
    directory = _plugin(tmp_path, "time-query", "clocks")
    before = list(sys.path)

    module = ExtensionLoader._import_handler(directory)

    assert module.execute() == "clocks"
    assert module.__package__
    assert module.__package__ in sys.modules
    assert sys.modules[module.__package__].__path__ == [str(directory.resolve())]
    assert sys.path == before


def test_identical_handler_names_are_isolated(tmp_path: Path) -> None:
    first = ExtensionLoader._import_handler(_plugin(tmp_path, "time-query", "alarm"))
    second = ExtensionLoader._import_handler(
        _plugin(tmp_path, "intelligent-search", "search")
    )

    assert first.execute() == "alarm"
    assert second.execute() == "search"
    assert first.__package__ != second.__package__


def test_broken_relative_import_does_not_leave_partial_package(tmp_path: Path) -> None:
    directory = tmp_path / "broken-extension"
    directory.mkdir()
    (directory / "handler.py").write_text(
        "from .not_installed import missing\n", encoding="utf-8"
    )

    with pytest.raises(ModuleNotFoundError):
        ExtensionLoader._import_handler(directory)

    module_prefix = "_karen_extension_"
    assert not any(
        name.startswith(module_prefix)
        and getattr(module, "__path__", None) == [str(directory.resolve())]
        for name, module in sys.modules.items()
    )
