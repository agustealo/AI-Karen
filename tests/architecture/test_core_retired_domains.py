from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"


def test_retired_core_domains_do_not_reappear() -> None:
    """Infrastructure-only domains must not silently reappear under Core."""
    assert not (CORE_ROOT / "cron").exists()
    assert not (CORE_ROOT / "operations").exists()


def test_core_readme_records_retired_domain_ownership() -> None:
    readme = (CORE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "`core/cron/` was removed" in readme
    assert "`core/operations/` is not a live directory" in readme
    assert "future scheduling infrastructure" in readme
    assert "belongs under `platform/`" in readme
