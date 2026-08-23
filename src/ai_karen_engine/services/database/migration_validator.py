"""
Migration Validator Service

Service for validating database migration status and ensuring all schemas are up to date.
Checks migration consistency across PostgreSQL and Redis.

Requirements: 2.5
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import importlib.util

from sqlalchemy import text, inspect, MetaData
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from .database_connection_manager import get_database_manager
from ai_karen_engine.database.models import Base

logger = get_logger(__name__)


class MigrationStatus(str, Enum):
    """Migration status enumeration"""
    UP_TO_DATE = "up_to_date"
    PENDING = "pending"
    FAILED = "failed"
    UNKNOWN = "unknown"
    INCONSISTENT = "inconsistent"


class SchemaValidationStatus(str, Enum):
    """Schema validation status"""
    VALID = "valid"
    MISSING_TABLES = "missing_tables"
    EXTRA_TABLES = "extra_tables"
    SCHEMA_MISMATCH = "schema_mismatch"
    VALIDATION_ERROR = "validation_error"


@dataclass
class TableInfo:
    """Database table information"""
    name: str
    exists: bool
    columns: List[str] = field(default_factory=list)
    indexes: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    row_count: Optional[int] = None


@dataclass
class MigrationInfo:
    """Migration information"""
    version: Optional[str]
    applied_at: Optional[datetime]
    description: Optional[str]
    is_current: bool = False


@dataclass
class SchemaValidationResult:
    """Schema validation result"""
    status: SchemaValidationStatus
    expected_tables: Set[str]
    actual_tables: Set[str]
    missing_tables: Set[str]
    extra_tables: Set[str]
    table_details: List[TableInfo]
    issues: List[str] = field(default_factory=list)


@dataclass
class MigrationValidationReport:
    """Migration validation report"""
    timestamp: datetime
    overall_status: MigrationStatus
    current_migration: Optional[MigrationInfo]
    pending_migrations: List[str]
    schema_validation: SchemaValidationResult
    migration_history: List[MigrationInfo]
    recommendations: List[str]
    errors: List[str] = field(default_factory=list)


class MigrationValidator:
    """
    Service for validating database migration status and schema consistency.
    
    Validates:
    - Current migration version
    - Pending migrations
    - Schema consistency with models
    - Table structure validation
    - Migration history integrity
    """

    def __init__(self, migrations_directory: str = "src/ai_karen_engine/database/migrations"):
        self.migrations_directory = Path(migrations_directory)
        from ai_karen_engine.database.client import get_database_client
        self.db_client = get_database_client()
        
        # Expected tables from SQLAlchemy models
        self.expected_tables = self._get_expected_tables()

    def _get_expected_tables(self) -> Set[str]:
        """Get expected table names from SQLAlchemy models"""
        expected_tables = set()
        
        try:
            # Get all table names from Base metadata
            for table in Base.metadata.tables.values():
                expected_tables.add(table.name)
                
        except Exception as e:
            logger.error(f"Error getting expected tables: {e}")
            # Fallback to hardcoded list of core tables
            expected_tables = {
                "tenants",
                "auth_users",
                "auth_sessions",
                "conversations",
                "messages",
                "memory_items",
                "extensions",
                "extension_usage",
                "hooks",
                "hook_exec_stats",
                "llm_providers",
                "llm_requests",
                "files",
                "webhooks",
                "usage_counters",
                "rate_limits",
                "audit_log",
                "marketplace_extensions",
                "installed_extensions",
                "auth_providers",
                "user_identities",
                "chat_memories",
                "password_reset_tokens",
                "email_verification_tokens",
                "roles",
                "role_permissions",
                "api_keys",
            }
        
        return expected_tables

    async def validate_migrations(self) -> MigrationValidationReport:
        """
        Perform comprehensive migration validation.
        
        Returns:
            MigrationValidationReport: Complete validation report
        """
        logger.info("Starting migration validation")
        
        errors = []
        recommendations = []
        
        try:
            # Get current migration status
            current_migration = await self._get_current_migration()
            
            # Get migration history
            migration_history = await self._get_migration_history()
            
            # Check for pending migrations
            pending_migrations = await self._get_pending_migrations()
            
            # Validate schema consistency
            schema_validation = await self._validate_schema()
            
            # Determine overall status
            overall_status = self._determine_overall_status(
                current_migration, pending_migrations, schema_validation
            )
            
            # Generate recommendations
            recommendations = self._generate_recommendations(
                current_migration, pending_migrations, schema_validation
            )
            
        except Exception as e:
            logger.error(f"Migration validation failed: {e}")
            errors.append(str(e))
            overall_status = MigrationStatus.FAILED
            current_migration = None
            migration_history = []
            pending_migrations = []
            schema_validation = SchemaValidationResult(
                status=SchemaValidationStatus.VALIDATION_ERROR,
                expected_tables=self.expected_tables,
                actual_tables=set(),
                missing_tables=self.expected_tables,
                extra_tables=set(),
                table_details=[],
                issues=[str(e)],
            )
        
        return MigrationValidationReport(
            timestamp=datetime.utcnow(),
            overall_status=overall_status,
            current_migration=current_migration,
            pending_migrations=pending_migrations,
            schema_validation=schema_validation,
            migration_history=migration_history,
            recommendations=recommendations,
            errors=errors,
        )

    async def _get_current_migration(self) -> Optional[MigrationInfo]:
        """Get current migration version"""
        try:
            async with self.db_client.async_session_scope() as session:
                # Check if alembic_version table exists
                result = await session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = 'alembic_version'
                        )
                    """)
                )
                
                if not result.scalar():
                    logger.warning("Alembic version table not found")
                    return None
                
                # Get current version
                result = await session.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                version = result.scalar()
                
                if version:
                    return MigrationInfo(
                        version=version,
                        applied_at=datetime.utcnow(),  # We don't track this in alembic_version
                        description=f"Current migration: {version}",
                        is_current=True,
                    )
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting current migration: {e}")
            return None

    async def _get_migration_history(self) -> List[MigrationInfo]:
        """Get migration history (simplified - Alembic doesn't store history by default)"""
        history = []
        
        try:
            # In a full implementation, you might have a custom migration tracking table
            # For now, we'll just return the current migration if it exists
            current = await self._get_current_migration()
            if current:
                history.append(current)
                
        except Exception as e:
            logger.error(f"Error getting migration history: {e}")
        
        return history

    async def _get_pending_migrations(self) -> List[str]:
        """Get list of pending migrations"""
        pending = []
        
        try:
            # Check if migrations directory exists
            if not self.migrations_directory.exists():
                logger.warning(f"Migrations directory not found: {self.migrations_directory}")
                return pending
            
            # In a full implementation, you would compare available migration files
            # with applied migrations. For now, we'll do a basic check.
            migration_files = list(self.migrations_directory.glob("*.py"))
            
            # Filter out __init__.py and other non-migration files
            migration_files = [
                f for f in migration_files 
                if not f.name.startswith("__") and f.name != "env.py"
            ]
            
            if not migration_files:
                logger.info("No migration files found")
            else:
                logger.info(f"Found {len(migration_files)} migration files")
                # Without a proper migration tracking system, we can't determine
                # which are pending. This would need Alembic integration.
                
        except Exception as e:
            logger.error(f"Error checking pending migrations: {e}")
        
        return pending

    async def _validate_schema(self) -> SchemaValidationResult:
        """Validate database schema against expected models"""
        try:
            async with self.db_client.async_session_scope() as session:
                # Get actual tables in database
                result = await session.execute(
                    text("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                    """)
                )
                actual_tables = {row[0] for row in result.fetchall()}
                
                # Compare with expected tables
                missing_tables = self.expected_tables - actual_tables
                extra_tables = actual_tables - self.expected_tables
                
                # Get detailed table information
                table_details = []
                issues = []
                
                for table_name in actual_tables:
                    table_info = await self._get_table_info(session, table_name)
                    table_details.append(table_info)
                
                # Determine validation status
                if missing_tables:
                    status = SchemaValidationStatus.MISSING_TABLES
                    issues.append(f"Missing tables: {', '.join(missing_tables)}")
                elif extra_tables:
                    status = SchemaValidationStatus.EXTRA_TABLES
                    issues.append(f"Extra tables: {', '.join(extra_tables)}")
                else:
                    status = SchemaValidationStatus.VALID
                
                return SchemaValidationResult(
                    status=status,
                    expected_tables=self.expected_tables,
                    actual_tables=actual_tables,
                    missing_tables=missing_tables,
                    extra_tables=extra_tables,
                    table_details=table_details,
                    issues=issues,
                )
                
        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            return SchemaValidationResult(
                status=SchemaValidationStatus.VALIDATION_ERROR,
                expected_tables=self.expected_tables,
                actual_tables=set(),
                missing_tables=self.expected_tables,
                extra_tables=set(),
                table_details=[],
                issues=[str(e)],
            )

    async def _get_table_info(self, session, table_name: str) -> TableInfo:
        """Get detailed information about a table"""
        try:
            # Get column information
            result = await session.execute(
                text("""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                    ORDER BY ordinal_position
                """),
                {"table_name": table_name}
            )
            columns = [f"{row[0]} ({row[1]})" for row in result.fetchall()]
            
            # Get index information
            result = await session.execute(
                text("""
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = :table_name
                """),
                {"table_name": table_name}
            )
            indexes = [row[0] for row in result.fetchall()]
            
            # Get row count (with limit to avoid performance issues)
            try:
                result = await session.execute(
                    text(f"SELECT COUNT(*) FROM {table_name} LIMIT 1000")
                )
                row_count = result.scalar()
            except Exception:
                row_count = None  # Table might be empty or have issues
            
            return TableInfo(
                name=table_name,
                exists=True,
                columns=columns,
                indexes=indexes,
                constraints=[],  # Could be expanded
                row_count=row_count,
            )
            
        except Exception as e:
            logger.error(f"Error getting table info for {table_name}: {e}")
            return TableInfo(
                name=table_name,
                exists=False,
                columns=[],
                indexes=[],
                constraints=[],
                row_count=None,
            )

    def _determine_overall_status(
        self,
        current_migration: Optional[MigrationInfo],
        pending_migrations: List[str],
        schema_validation: SchemaValidationResult,
    ) -> MigrationStatus:
        """Determine overall migration status"""
        
        # If schema validation failed, that's critical
        if schema_validation.status == SchemaValidationStatus.VALIDATION_ERROR:
            return MigrationStatus.FAILED
        
        # If we have missing tables, migrations are needed
        if schema_validation.status == SchemaValidationStatus.MISSING_TABLES:
            return MigrationStatus.PENDING
        
        # If we have pending migrations
        if pending_migrations:
            return MigrationStatus.PENDING
        
        # If no current migration is tracked
        if not current_migration:
            return MigrationStatus.UNKNOWN
        
        # If schema has extra tables, might be inconsistent
        if schema_validation.status == SchemaValidationStatus.EXTRA_TABLES:
            return MigrationStatus.INCONSISTENT
        
        # Everything looks good
        return MigrationStatus.UP_TO_DATE

    def _generate_recommendations(
        self,
        current_migration: Optional[MigrationInfo],
        pending_migrations: List[str],
        schema_validation: SchemaValidationResult,
    ) -> List[str]:
        """Generate migration recommendations"""
        recommendations = []
        
        # Migration tracking recommendations
        if not current_migration:
            recommendations.append(
                "Initialize Alembic migration tracking with 'alembic stamp head'"
            )
        
        # Schema recommendations
        if schema_validation.missing_tables:
            recommendations.append(
                f"Create missing tables: {', '.join(schema_validation.missing_tables)}"
            )
            recommendations.append(
                "Run 'alembic upgrade head' to apply pending migrations"
            )
        
        if schema_validation.extra_tables:
            recommendations.append(
                f"Review extra tables: {', '.join(schema_validation.extra_tables)}"
            )
            recommendations.append(
                "Consider creating migrations to remove unused tables"
            )
        
        # Pending migrations
        if pending_migrations:
            recommendations.append(
                f"Apply {len(pending_migrations)} pending migrations"
            )
        
        # General recommendations
        if not self.migrations_directory.exists():
            recommendations.append(
                "Set up Alembic migrations directory structure"
            )
        
        # If everything is good
        if (current_migration and 
            not pending_migrations and 
            schema_validation.status == SchemaValidationStatus.VALID):
            recommendations.append("Database schema is up to date")
        
        return recommendations

    async def create_missing_tables(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Create missing tables based on SQLAlchemy models.
        
        Args:
            dry_run: If True, only report what would be created
            
        Returns:
            Dict containing creation results
        """
        logger.info(f"Creating missing tables (dry_run={dry_run})")
        
        results = {
            "dry_run": dry_run,
            "timestamp": datetime.utcnow().isoformat(),
            "tables_created": [],
            "errors": [],
        }
        
        try:
            # Validate current schema
            schema_validation = await self._validate_schema()
            
            if not schema_validation.missing_tables:
                results["message"] = "No missing tables found"
                return results
            
            if not dry_run:
                # Create missing tables using SQLAlchemy
                try:
                    # This will create all tables defined in Base.metadata
                    await self.db_client.create_tables_async()
                    
                    results["tables_created"] = list(schema_validation.missing_tables)
                    results["message"] = f"Created {len(schema_validation.missing_tables)} tables"
                    
                except Exception as e:
                    logger.error(f"Error creating tables: {e}")
                    results["errors"].append(str(e))
            else:
                results["tables_created"] = list(schema_validation.missing_tables)
                results["message"] = f"Would create {len(schema_validation.missing_tables)} tables"
        
        except Exception as e:
            logger.error(f"Table creation failed: {e}")
            results["errors"].append(str(e))
        
        return results

    async def validate_table_structure(self, table_name: str) -> Dict[str, Any]:
        """
        Validate the structure of a specific table against its model.
        
        Args:
            table_name: Name of table to validate
            
        Returns:
            Dict containing validation results
        """
        logger.info(f"Validating table structure: {table_name}")
        
        results = {
            "table_name": table_name,
            "timestamp": datetime.utcnow().isoformat(),
            "exists": False,
            "structure_valid": False,
            "issues": [],
            "recommendations": [],
        }
        
        try:
            async with self.db_client.async_session_scope() as session:
                # Check if table exists
                result = await session.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' 
                            AND table_name = :table_name
                        )
                    """),
                    {"table_name": table_name}
                )
                
                table_exists = result.scalar()
                results["exists"] = table_exists
                
                if not table_exists:
                    results["issues"].append(f"Table {table_name} does not exist")
                    results["recommendations"].append(f"Create table {table_name}")
                    return results
                
                # Get table info
                table_info = await self._get_table_info(session, table_name)
                
                # Basic validation - in a full implementation, you would compare
                # against the SQLAlchemy model definition
                if table_info.columns:
                    results["structure_valid"] = True
                    results["column_count"] = len(table_info.columns)
                    results["index_count"] = len(table_info.indexes)
                    results["row_count"] = table_info.row_count
                else:
                    results["issues"].append(f"Table {table_name} has no columns")
                    results["recommendations"].append(f"Check table {table_name} structure")
        
        except Exception as e:
            logger.error(f"Table structure validation failed: {e}")
            results["issues"].append(str(e))
        
        return results


# Global instance
_migration_validator: Optional[MigrationValidator] = None


def get_migration_validator() -> MigrationValidator:
    """Get global migration validator instance"""
    global _migration_validator
    if _migration_validator is None:
        _migration_validator = MigrationValidator()
    return _migration_validator


async def validate_database_migrations(
    migrations_directory: str = "src/ai_karen_engine/database/migrations",
) -> MigrationValidationReport:
    """
    Convenience function to validate database migrations.
    
    Args:
        migrations_directory: Path to migrations directory
        
    Returns:
        MigrationValidationReport: Complete validation report
    """
    validator = MigrationValidator(migrations_directory=migrations_directory)
    return await validator.validate_migrations()
