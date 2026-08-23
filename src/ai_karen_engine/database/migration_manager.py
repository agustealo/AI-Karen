"""Simplified migration manager using ordered SQL schema files."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from ai_karen_engine.core.memory.chat_memory_config import settings
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.models import Tenant

logger = logging.getLogger(__name__)

# Ordered SQL migration files (filenames, not stems)
SCHEMA_MIGRATIONS: List[str] = [
    "001_agui_chat_core.sql",
    "003_persona_persistence.sql",
    "004_chat_runtime_control_plane.sql",
    "005_fix_auth_user_schema.sql",
    "006_populate_missing_profile_fields.sql",
    "007_memory_ledger.sql",
    "008_memory_convergence.sql",
    "009_conversation_tenant_scoping.sql",
    "010_row_level_security.sql",
    "011_schema_corrections.sql",
]


class MigrationManager:
    """Manage database schema using a single consolidated SQL migration."""

    def __init__(
        self, database_url: Optional[str] = None, migrations_dir: Optional[str] = None
    ):
        self.database_url = database_url or self._build_database_url()
        self.migrations_dir = migrations_dir or os.path.join(
            os.path.dirname(__file__), "migrations"
        )
        self.client = MultiTenantPostgresClient(self.database_url)
        self.migration_files = SCHEMA_MIGRATIONS

    def _build_database_url(self) -> str:
        if getattr(settings, "database_url", None):
            return settings.database_url
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "postgres")
        database = os.getenv("POSTGRES_DB", "ai_karen")
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    # ------------------------------------------------------------------
    # Compatibility stubs for previous Alembic-based interface
    # ------------------------------------------------------------------
    def initialize_alembic(self) -> bool:
        """Alembic is no longer used; migrations are plain SQL files."""
        logger.info("Alembic not used - using consolidated SQL migrations")
        return True

    def create_initial_migration(self) -> bool:
        """Initial migration is provided as a static SQL file."""
        logger.info("Initial migration already consolidated")
        return True

    # ------------------------------------------------------------------
    # Migration operations
    # ------------------------------------------------------------------
    def run_migrations(self, revision: str = "head") -> bool:
        """Apply any pending SQL migrations to the database."""
        try:
            with self.client.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            version TEXT PRIMARY KEY,
                            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                applied = {
                    row[0]
                    for row in conn.execute(
                        text("SELECT version FROM schema_migrations")
                    ).fetchall()
                }
                applied = self._bootstrap_existing_schema(conn, applied)
                for filename in self.migration_files:
                    version = filename[:-4]  # strip .sql
                    if version in applied:
                        continue
                    path = Path(self.migrations_dir) / filename
                    sql = path.read_text()
                    conn.execute(text(sql))
                    conn.execute(
                        text(
                            "INSERT INTO schema_migrations (version) VALUES (:version)"
                        ),
                        {"version": version},
                    )
            logger.info("Applied pending schema migrations")
            return True
        except Exception as e:  # pragma: no cover - database errors
            logger.error(f"Failed to run migrations: {e}")
            return False

    def _bootstrap_existing_schema(self, conn: Any, applied: set[str]) -> set[str]:
        """Mark legacy baseline migrations as applied when their tables already exist."""
        if "001_agui_chat_core" not in applied:
            auth_users_exists = conn.execute(
                text("SELECT to_regclass('public.auth_users')")
            ).scalar()
            if auth_users_exists:
                conn.execute(
                    text(
                        "INSERT INTO schema_migrations (version) VALUES (:version) ON CONFLICT DO NOTHING"
                    ),
                    {"version": "001_agui_chat_core"},
                )
                applied = set(applied)
                applied.add("001_agui_chat_core")
        return applied

    def rollback_migration(self, revision: str) -> bool:
        """Rollback is not supported with consolidated migrations."""
        logger.warning("Rollback not supported for consolidated migrations")
        return False

    def get_migration_history(self) -> List[Dict[str, Any]]:
        """Return the revision history for the SQL migration files."""
        history: List[Dict[str, Any]] = []
        previous: Optional[str] = None
        for filename in self.migration_files:
            revision = filename[:-4]  # strip .sql
            message = filename[len(revision) + 1 : -4]
            history.append(
                {
                    "revision": revision,
                    "down_revision": previous,
                    "message": message,
                    "is_current": filename == self.migration_files[-1],
                }
            )
            previous = revision
        return history

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------
    def get_database_status(self) -> Dict[str, Any]:
        """Get basic database status information."""
        status = {
            "database_url": self.database_url.split("@")[-1],
            "migrations_dir": self.migrations_dir,
            "alembic_initialized": True,
            "current_revision": self.migration_files[-1].split("_", 1)[0],
            "pending_migrations": 0,
            "tenant_count": 0,
            "health": "unknown",
        }

        try:  # pragma: no cover - requires database
            with self.client.session_scope() as session:
                status["tenant_count"] = session.query(Tenant).count()
                session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            version TEXT PRIMARY KEY,
                            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )
                applied = {
                    row[0]
                    for row in session.execute(
                        text("SELECT version FROM schema_migrations")
                    ).fetchall()
                }
                applied = self._bootstrap_existing_schema(session, applied)
                status["pending_migrations"] = len(
                    [f for f in self.migration_files if f[:-4] not in applied]
                )

            status["health"] = "healthy" if self.client.health_check() else "unhealthy"
        except Exception as e:  # pragma: no cover - database errors
            status["error"] = str(e)
            logger.error(f"Failed to get database status: {e}")

        return status


__all__ = ["MigrationManager", "SCHEMA_MIGRATIONS"]
