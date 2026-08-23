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

# Expected migration version (update when adding migrations)
# This should match the latest migration file in /data/migrations/postgres/
EXPECTED_MIGRATION_VERSION = "022_enhanced_auth_validation_system.sql"
EXPECTED_MIGRATION_SERVICE = "postgres"


class SchemaVersionError(Exception):
    """Raised when schema version doesn't match expected version."""
    pass


def validate_schema_version_sync(db_engine: Engine) -> Dict[str, Any]:
    """
    Validate that database schema matches expected version (synchronous).

    Args:
        db_engine: SQLAlchemy Engine instance

    Returns:
        Dict with validation status and details

    Raises:
        SchemaVersionError: If version mismatch or no migrations applied
    """
    try:
        with db_engine.connect() as conn:
            # Check if migration_history table exists
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

            # Get latest applied migration
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

            current_version = row[0]
            applied_at = row[1]
            status = row[2]

            if status != "applied":
                error_msg = (
                    f"Latest migration has status '{status}' (not 'applied')!\n"
                    f"Migration: {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    f"Action: Check migration logs and fix failed migration"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            if current_version != EXPECTED_MIGRATION_VERSION:
                error_msg = (
                    f"Schema version mismatch!\n"
                    f"Expected: {EXPECTED_MIGRATION_VERSION}\n"
                    f"Current:  {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    f"Action: Run pending migrations: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            logger.info(
                f"✅ Schema version validated: {current_version} (applied {applied_at})"
            )

            return {
                "valid": True,
                "expected_version": EXPECTED_MIGRATION_VERSION,
                "current_version": current_version,
                "applied_at": str(applied_at),
                "status": status
            }

    except SchemaVersionError:
        raise
    except Exception as ex:
        error_msg = f"Schema version validation failed: {ex}"
        logger.error(error_msg)
        raise SchemaVersionError(error_msg) from ex


async def validate_schema_version_async(db_engine: AsyncEngine) -> Dict[str, Any]:
    """
    Validate that database schema matches expected version (async).

    Args:
        db_engine: SQLAlchemy AsyncEngine instance

    Returns:
        Dict with validation status and details

    Raises:
        SchemaVersionError: If version mismatch or no migrations applied
    """
    try:
        async with db_engine.connect() as conn:
            # Check if migration_history table exists
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

            # Get latest applied migration
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

            current_version = row[0]
            applied_at = row[1]
            status = row[2]

            if status != "applied":
                error_msg = (
                    f"Latest migration has status '{status}' (not 'applied')!\n"
                    f"Migration: {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    f"Action: Check migration logs and fix failed migration"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            if current_version != EXPECTED_MIGRATION_VERSION:
                error_msg = (
                    f"Schema version mismatch!\n"
                    f"Expected: {EXPECTED_MIGRATION_VERSION}\n"
                    f"Current:  {current_version}\n"
                    f"Applied at: {applied_at}\n"
                    f"Action: Run pending migrations: python scripts/migrations/run_migrations.py"
                )
                logger.error(error_msg)
                raise SchemaVersionError(error_msg)

            logger.info(
                f"✅ Schema version validated: {current_version} (applied {applied_at})"
            )

            return {
                "valid": True,
                "expected_version": EXPECTED_MIGRATION_VERSION,
                "current_version": current_version,
                "applied_at": str(applied_at),
                "status": status
            }

    except SchemaVersionError:
        raise
    except Exception as ex:
        error_msg = f"Schema version validation failed: {ex}"
        logger.error(error_msg)
        raise SchemaVersionError(error_msg) from ex


async def validate_and_migrate_schema(session: Any) -> Optional[Any]:
    """
    Validate schema and return error response if validation fails.

    This is a compatibility wrapper for web API routes that expect
    error response objects instead of exceptions.

    Args:
        session: Database session (AsyncSession or similar)

    Returns:
        None if validation succeeds, error response object if fails
    """
    try:
        # Get the engine from the session
        from sqlalchemy.ext.asyncio import AsyncSession

        if isinstance(session, AsyncSession):
            engine = session.get_bind()
        else:
            # Fallback - try to get bind attribute
            engine = getattr(session, 'bind', None) or getattr(session, 'get_bind', lambda: None)()

        if engine is None:
            # If we can't get engine, just return None (skip validation)
            logger.warning("Could not get database engine from session, skipping validation")
            return None

        # Run validation
        await validate_schema_version_async(engine)
        return None  # Success

    except SchemaVersionError as e:
        # Import error response creator
        try:
             from ai_karen_engine.services.error_response_schemas import create_database_error_response

            return create_database_error_response(
                error=e,
                operation="schema_validation",
                user_message=str(e),
                request_id=None
            )
        except ImportError:
            # If error response module not available, create simple error object
            class SimpleError:
                def __init__(self, message: str):
                    self.message = message
                    self.type = "DATABASE_ERROR"

                def dict(self):
                    return {"message": self.message, "type": self.type}

            return SimpleError(str(e))
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error during schema validation: {e}")
        try:
             from ai_karen_engine.services.error_response_schemas import create_database_error_response

            return create_database_error_response(
                error=e,
                operation="schema_validation",
                user_message="Schema validation failed unexpectedly",
                request_id=None
            )
        except ImportError:
            class SimpleError:
                def __init__(self, message: str):
                    self.message = message
                    self.type = "DATABASE_ERROR"

                def dict(self):
                    return {"message": self.message, "type": self.type}

            return SimpleError(str(e))


__all__ = [
    "validate_schema_version_sync",
    "validate_schema_version_async",
    "validate_and_migrate_schema",
    "SchemaVersionError",
    "EXPECTED_MIGRATION_VERSION",
    "EXPECTED_MIGRATION_SERVICE"
]
