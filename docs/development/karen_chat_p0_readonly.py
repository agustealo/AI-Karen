#!/usr/bin/env python3
"""Read-only diagnostic for AI-Karen's canonical chat prerequisites.

Place at scripts/diagnostics/chat_p0_readonly.py and run INSIDE the API
container using the running service's actual environment.

It does not send chat messages, modify schema/data, print secrets, or
claim that provider inference/AG-UI browser execution was verified.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Check:
    id: str
    status: str
    detail: str


class Report:
    def __init__(self) -> None:
        self.checks: list[Check] = []

    def add(self, identifier: str, status: str, detail: str) -> None:
        if status not in {"pass", "fail", "warning", "not_tested"}:
            raise ValueError("Invalid audit status")
        self.checks.append(Check(identifier, status, detail))

    def to_dict(self) -> dict[str, Any]:
        counts = {state: sum(c.status == state for c in self.checks)
                  for state in ("pass", "fail", "warning", "not_tested")}
        return {
            "contract": "karen_chat_p0_readonly_v1",
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": counts,
            "checks": [asdict(check) for check in self.checks],
            "disclaimer": (
                "Read-only configuration and schema assessment only. This is not "
                "a real-model or browser end-to-end smoke test."
            ),
        }


def safe_sqlstate(exc: BaseException) -> str | None:
    """Return SQLSTATE only, never the database driver's exception message."""
    current: Any = exc
    for _ in range(4):
        if current is None:
            break
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(value, str) and re.fullmatch(r"[A-Z0-9]{5}", value):
            return value
        current = getattr(current, "orig", None)
    return None


def status_of(condition: bool) -> str:
    return "pass" if condition else "fail"


async def audit() -> Report:
    report = Report()
    try:
        from ai_karen_engine.config.runtime import get_runtime_settings
        features = get_runtime_settings().features
        for name, label in (
            ("enable_ag_ui_bridge", "agui_bridge"),
            ("enable_streaming", "streaming"),
        ):
            enabled = bool(getattr(features, name, False))
            report.add(label, status_of(enabled), "enabled" if enabled else "disabled")
        for name, label in (
            ("enable_ag_ui_durable_runs", "agui_durable_runs"),
            ("enable_ag_ui_event_journal", "agui_event_journal"),
        ):
            enabled = bool(getattr(features, name, False))
            report.add(label, "pass" if enabled else "warning",
                       "enabled" if enabled else "not enabled; verify requirements before opting in")
    except Exception as exc:
        report.add("runtime_configuration", "fail", f"inspection failed: {type(exc).__name__}")

    try:
        from sqlalchemy import text
        from ai_karen_engine.persistence.postgres.engine import get_postgres_engine
    except Exception as exc:
        report.add("db_imports", "fail", f"inspection failed: {type(exc).__name__}")
        report.add("live_chat", "not_tested", "Use the existing authenticated Playwright proof")
        return report

    engine = None
    try:
        engine = get_postgres_engine()
        async with engine.get_async_session() as session:
            # Even if a future query changes, this transaction cannot write.
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(text("SELECT 1"))
            report.add("database_connection", "pass", "canonical PostgreSQL session responds")

            dependencies = await session.execute(text("""
                SELECT
                  to_regclass('public.conversations') IS NOT NULL AS conversations,
                  to_regclass('public.auth_users') IS NOT NULL AS auth_users,
                  to_regclass('public.tenants') IS NOT NULL AS tenants,
                  to_regclass('public.conversation_composer_drafts') IS NOT NULL AS drafts
            """))
            objects = dependencies.mappings().one()
            for name in ("conversations", "auth_users", "tenants"):
                exists = bool(objects[name])
                report.add(f"table_{name}", status_of(exists),
                           "present" if exists else "missing")
            drafts_present = bool(objects["drafts"])
            report.add("table_conversation_composer_drafts", status_of(drafts_present),
                       "present" if drafts_present else "missing: reconcile migration 47")
            if drafts_present:
                result = await session.execute(text("""
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE oid = to_regclass('public.conversation_composer_drafts')
                """))
                relation = result.mappings().one()
                for column, label in (("relrowsecurity", "draft_rls_enabled"),
                                      ("relforcerowsecurity", "draft_rls_forced")):
                    enabled = bool(relation[column])
                    report.add(label, status_of(enabled), "enabled" if enabled else "disabled")

                policy = await session.scalar(text("""
                    SELECT count(*) FROM pg_policies
                    WHERE schemaname = 'public'
                      AND tablename = 'conversation_composer_drafts'
                      AND policyname = 'conversation_composer_draft_owner'
                """))
                report.add("draft_owner_policy", status_of(policy == 1),
                           "owner policy present" if policy == 1 else "owner policy missing")

                column = await session.scalar(text("""
                    SELECT data_type FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'conversation_composer_drafts'
                      AND column_name = 'revision'
                """))
                report.add("draft_revision_column", status_of(column == "bigint"),
                           "bigint" if column == "bigint" else "revision type missing or incompatible")

                foreign_keys = await session.scalar(text("""
                    SELECT count(*) FROM pg_constraint
                    WHERE conrelid = to_regclass('public.conversation_composer_drafts')
                      AND contype = 'f'
                """))
                report.add("draft_foreign_keys", status_of(int(foreign_keys or 0) >= 3),
                           "three or more foreign keys" if int(foreign_keys or 0) >= 3
                           else "expected conversation, tenant and user foreign keys")

                privileges = (await session.execute(text("""
                    SELECT
                      has_table_privilege(current_user,
                        'public.conversation_composer_drafts', 'SELECT') AS can_select,
                      has_table_privilege(current_user,
                        'public.conversation_composer_drafts', 'INSERT') AS can_insert,
                      has_table_privilege(current_user,
                        'public.conversation_composer_drafts', 'UPDATE') AS can_update
                """))).mappings().one()
                allowed = all(bool(privileges[key])
                              for key in ("can_select", "can_insert", "can_update"))
                report.add("draft_role_table_privileges", status_of(allowed),
                           "SELECT/INSERT/UPDATE permitted" if allowed
                           else "runtime database role lacks required privileges")

            # A developer superuser can obscure RLS integration failures.
            role = (await session.execute(text("""
                SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user
            """))).mappings().one()
            bypasses = bool(role["rolsuper"] or role["rolbypassrls"])
            report.add("runtime_role_rls_bypass", "warning" if bypasses else "pass",
                       "runtime DB role bypasses RLS; use least-privilege role for release proof"
                       if bypasses else "runtime DB role has no superuser/BYPASSRLS attributes")
    except Exception as exc:
        state = safe_sqlstate(exc)
        detail = f"{type(exc).__name__}" + (f" / SQLSTATE {state}" if state else "")
        report.add("database_inspection", "fail", detail)
    finally:
        if engine is not None:
            try:
                await engine.cleanup()
            except Exception:
                report.add("database_cleanup", "warning", "diagnostic connection cleanup failed")

    report.add("authenticated_browser_model_round_trip", "not_tested",
               "Run the existing exact-revision real-model CopilotKit Playwright acceptance")
    report.add("model_provider_health", "not_tested",
               "Read-only schema checks cannot certify model execution")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pretty", action="store_true", help="Indent JSON output")
    args = parser.parse_args()
    report = asyncio.run(audit())
    print(json.dumps(report.to_dict(), indent=2 if args.pretty else None, sort_keys=True))
    return 1 if any(check.status == "fail" for check in report.checks) else 0


if __name__ == "__main__":
    sys.exit(main())
