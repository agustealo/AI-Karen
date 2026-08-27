"""
Schema Version Validator

Ensures application runs against correct database schema version.
Fails fast on mismatch to prevent runtime errors.

ARCHITECTURAL COMPLIANCE:
- Validates against single source of truth (Postgres migration_history)
- Fail-fast pattern: service won't start with wrong schema
- Clear error messages for operators
"""

import logging
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

EXPECTED_MIGRATION_VERSION = "022_enhanced_auth_validation_system.sql"
EXPECTED_MIGRATION_SERVICE = "postgres"


class SchemaVersionError(Exception):
    """Raised when schema version doesn't match expected version."""
    pass


def validate_schema_version_sync(db_engine: Engine) -> Dict[str, Any]:
    """Validate that database schema matches expected version synchronously."""
    try:
        with db_engine.connect() as conn:
            check_table = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'migration_history'
                )
            """)
            table_exists = conn.execute(check_table).scalar()

            if not table_exists:
                error_msg = (
                    "migration_history table not found! "
                    "Database has not been initialized with migrations. "
                    "Run migrations first: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            query = text("""
                SELECT migration_name, applied_at, status
                FROM migration_history
                WHERE service = :service
                ORDER BY applied_at DESC
                LIMIT 1
            """)
            result = conn.execute(query, {"service": EXPECTED_MIGRATION_SERVICE})
            row = result.fetchone()

            if not row:
                error_msg = (
                    f"No migrations applied for service '{EXPECTED_MIGRATION_SERVICE}'! "
                    "Run migrations first: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            current_version, applied_at, status = row[0], row[1], row[2]
            if status != "applied":
                error_msg = (
                    f"Latest migration has status '{status}' (not 'applied')!\n"
                    f"Migration: {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    "Action: Check migration logs and fix failed migration"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            if current_version != EXPECTED_MIGRATION_VERSION:
                error_msg = (
                    "Schema version mismatch!\n"
                    f"Expected: {EXPECTED_MIGRATION_VERSION}\n"
                    f"Current:  {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    "Action: Run pending migrations: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            logger.info("Schema version validated: %s (applied %s)", current_version, applied_at)
            return {
                "valid": True,
                "expected_version": EXPECTED_MIGRATION_VERSION,
                "current_version": current_version,
                "applied_at": str(applied_at),
                "status": status,
            }
    except SchemaVersionError:
        raise
    except Exception as ex:
        error_msg = f"Schema version validation failed: {ex}"
        logger.error(error_msg)
        raise SchemaVersionError(error_msg) from ex


async def validate_schema_version_async(db_engine: AsyncEngine) -> Dict[str, Any]:
    """Validate that database schema matches expected version asynchronously."""
    try:
        async with db_engine.connect() as conn:
            check_table = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'migration_history'
                )
            """)
            result = await conn.execute(check_table)
            table_exists = result.scalar()

            if not table_exists:
                error_msg = (
                    "migration_history table not found! "
                    "Database has not been initialized with migrations. "
                    "Run migrations first: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            query = text("""
                SELECT migration_name, applied_at, status
                FROM migration_history
                WHERE service = :service
                ORDER BY applied_at DESC
                LIMIT 1
            """)
            result = await conn.execute(query, {"service": EXPECTED_MIGRATION_SERVICE})
            row = result.fetchone()

            if not row:
                error_msg = (
                    f"No migrations applied for service '{EXPECTED_MIGRATION_SERVICE}'! "
                    "Run migrations first: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            current_version, applied_at, status = row[0], row[1], row[2]
            if status != "applied":
                error_msg = (
                    f"Latest migration has status '{status}' (not 'applied')!\n"
                    f"Migration: {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    "Action: Check migration logs and fix failed migration"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            if current_version != EXPECTED_MIGRATION_VERSION:
                error_msg = (
                    "Schema version mismatch!\n"
                    f"Expected: {EXPECTED_MIGRATION_VERSION}\n"
                    f"Current:  {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    "Action: Run pending migrations: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            logger.info("Schema version validated: %s (applied %s)", current_version, applied_at)
            return {
                "valid": True,
                "expected_version": EXPECTED_MIGRATION_VERSION,
                "current_version": current_version,
                "applied_at": str(applied_at),
                "status": status,
            }
    except SchemaVersionError:
        raise
    except Exception as ex:
        error_msg = f"Schema version validation failed: {ex}"
        logger.error(error_msg)
        raise SchemaVersionError(error_msg) from ex


async def validate_and_migrate_schema(session: Any) -> Optional[Any]:
    """Validate schema and return a compatibility error response on failure."""
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        if isinstance(session, AsyncSession):
            engine = session.get_bind()
        else:
            engine = getattr(session, "bind", None) or getattr(
                session, "get_bind", lambda: None
            )()

        if engine is None:
            logger.warning("Could not get database engine from session, skipping validation")
            return None

        await validate_schema_version_async(engine)
        return None
    except SchemaVersionError as exc:
        try:
            from ai_karen_engine.services.error_response_schemas import (
                create_database_error_response,
            )

            return create_database_error_response(
                error=exc,
                operation="schema_validation",
                user_message=str(exc),
                request_id=None,
            )
        except ImportError:
            return _SimpleDatabaseError(str(exc))
    except Exception as exc:
        logger.error("Unexpected error during schema validation: %s", exc)
        try:
            from ai_karen_engine.services.error_response_schemas import (
                create_database_error_response,
            )

            return create_database_error_response(
                error=exc,
                operation="schema_validation",
                user_message="Schema validation failed unexpectedly",
                request_id=None,
            )
        except ImportError:
            return _SimpleDatabaseError(str(exc))


class _SimpleDatabaseError:
    """Compatibility response used only when the canonical schema is unavailable."""

    def __init__(self, message: str):
        self.message = message
        self.type = "DATABASE_ERROR"

    def dict(self) -> Dict[str, str]:
        return {"message": self.message, "type": self.type}


__all__ = [
    "validate_schema_version_sync",
    "validate_schema_version_async",
    "validate_and_migrate_schema",
    "SchemaVersionError",
    "EXPECTED_MIGRATION_VERSION",
    "EXPECTED_MIGRATION_SERVICE",
]
