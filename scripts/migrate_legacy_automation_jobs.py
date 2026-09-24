#!/usr/bin/env python3
"""Migrate pre-tenant file-backed automation jobs into PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_karen_engine.services.automation.legacy_job_migration import (  # noqa: E402
    LegacyAutomationMigrationError,
    migrate_legacy_jobs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Bind legacy automation jobs to an explicit durable tenant/user, "
            "preserve job IDs, verify PostgreSQL state, and remove the old JSON "
            "source after successful migration."
        )
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/automation_jobs.json"),
    )
    parser.add_argument(
        "--keep-source",
        action="store_true",
        help="Keep the legacy JSON file after verified import.",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    result = await migrate_legacy_jobs(
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        source_path=args.source,
        remove_source=not args.keep_source,
    )
    print(
        json.dumps(
            {
                "source": result.source,
                "source_sha256": result.source_sha256,
                "imported": result.imported,
                "already_present": result.already_present,
                "removed_source": result.removed_source,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    args = _parser().parse_args()
    try:
        return asyncio.run(_run(args))
    except LegacyAutomationMigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
