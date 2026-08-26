from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "src" / "ai_karen_engine" / "core"


def test_retired_core_domains_do_not_reappear() -> None:
    """Retired or infrastructure-only domains must not silently reappear under Core."""
    for domain in ("automation", "context", "cron", "operations"):
        assert not (CORE_ROOT / domain).exists()


def test_core_readme_records_retired_domain_ownership() -> None:
    readme = (CORE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "`core/automation/` was removed" in readme
    assert "`core/context/` was removed" in readme
    assert "`core/cron/` was removed" in readme
    assert "`core/operations/` is not a live directory" in readme
    assert "request-context assembly belong to `core/runtime/`" in readme
    assert "Future automation belongs to an explicit automation/application or platform owner" in readme
    assert "future scheduling infrastructure" in readme
    assert "belongs under `platform/`" in readme
