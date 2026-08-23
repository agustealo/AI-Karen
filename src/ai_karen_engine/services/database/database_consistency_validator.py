"""
Database Consistency Validation System

Comprehensive validation system for database consistency across PostgreSQL and Redis.
Includes health checking, cross-database reference integrity validation, data cleanup,
and migration validation.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from sqlalchemy import text, select, func
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.database.client import DatabaseClient
from ai_karen_engine.core.memory.redis_connection_manager import get_redis_manager
from ai_karen_engine.database.models import (
    Base,
    TenantConversation,
    TenantMemoryItem,
    TenantMessage,
    AuthUser,
    Tenant,
    AuditLog,
    Extension,
    LLMProvider,
    LLMRequest,
)

logger = get_logger(__name__)


class ValidationStatus(str, Enum):
    """Validation status enumeration"""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    FAILED = "failed"


class DatabaseType(str, Enum):
    """Database type enumeration"""

    POSTGRESQL = "postgresql"
    REDIS = "redis"


@dataclass
class ValidationIssue:
    """Individual validation issue"""

    database: DatabaseType
    severity: ValidationStatus
    category: str
    description: str
    details: Dict[str, Any] = field(default_factory=dict)
    recommendation: Optional[str] = None
    auto_fixable: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DatabaseHealthStatus:
    """Database health status information"""

    database: DatabaseType
    is_connected: bool
    response_time_ms: float
    status: ValidationStatus
    version: Optional[str] = None
    connection_count: Optional[int] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsistencyReport:
    """Database consistency validation report"""

    timestamp: datetime
    overall_status: ValidationStatus
    database_health: List[DatabaseHealthStatus]
    validation_issues: List[ValidationIssue]
    cross_reference_issues: List[ValidationIssue]
    migration_issues: List[ValidationIssue]
    cleanup_recommendations: List[str]
    performance_metrics: Dict[str, Any]
    summary: Dict[str, int] = field(default_factory=dict)


class DatabaseConsistencyValidator:
    """
    Comprehensive database consistency validation system.

    Validates:
    - Database health and connectivity
    - Cross-database reference integrity
    - Data consistency and orphaned records
    - Migration status
    - Test/demo data cleanup needs
    """

    def __init__(
        self,
        data_directory: str = "data",
        enable_auto_fix: bool = False,
        validation_timeout: int = 300,
    ):
        self.data_directory = Path(data_directory)
        self.enable_auto_fix = enable_auto_fix
        self.validation_timeout = validation_timeout

        # Database managers
        self.db_client = DatabaseClient()
        self.redis_manager = get_redis_manager()

        # Validation state
        self._validation_start_time: Optional[datetime] = None
        self._validation_issues: List[ValidationIssue] = []
        self._database_health: List[DatabaseHealthStatus] = []

        # Demo/test data patterns to identify
        self.demo_patterns = {
            "emails": [
                "admin@example.com",
                "test@example.com",
                "demo@example.com",
                "user@example.com",
            ],
            "user_ids": [
                "dev_admin",
                "test_user",
                "demo_user",
            ],
            "tenant_ids": [
                "demo",
                "test",
                "example",
            ],
        }

    async def validate_all(self) -> ConsistencyReport:
        """
        Perform comprehensive database consistency validation.

        Returns:
            ConsistencyReport: Complete validation report
        """
        self._validation_start_time = datetime.utcnow()
        self._validation_issues.clear()
        self._database_health.clear()

        logger.info("Starting comprehensive database consistency validation")

        try:
            # Step 1: Validate database health
            await self._validate_database_health()

            # Step 2: Validate cross-database references
            await self._validate_cross_database_references()

            # Step 3: Validate migration status
            await self._validate_migration_status()

            # Step 4: Identify cleanup needs
            cleanup_recommendations = await self._identify_cleanup_needs()

            # Step 5: Performance metrics
            performance_metrics = await self._collect_performance_metrics()

            # Generate report
            report = self._generate_report(cleanup_recommendations, performance_metrics)

            logger.info(
                f"Database validation completed with status: {report.overall_status}"
            )
            return report

        except Exception as e:
            logger.error(f"Database validation failed: {e}")
            # Return error report
            return ConsistencyReport(
                timestamp=datetime.utcnow(),
                overall_status=ValidationStatus.FAILED,
                database_health=self._database_health,
                validation_issues=[
                    ValidationIssue(
                        database=DatabaseType.POSTGRESQL,
                        severity=ValidationStatus.CRITICAL,
                        category="validation_error",
                        description=f"Validation process failed: {str(e)}",
                        details={"error": str(e)},
                    )
                ],
                cross_reference_issues=[],
                migration_issues=[],
                cleanup_recommendations=[],
                performance_metrics={},
            )

    async def _validate_database_health(self) -> None:
        """Validate health of all database connections"""
        logger.info("Validating database health")

        # PostgreSQL health check
        await self._check_postgresql_health()

        # Redis health check
        await self._check_redis_health()

    async def _check_postgresql_health(self) -> None:
        """Check PostgreSQL database health"""
        start_time = time.time()

        try:
            # Test basic connectivity
            async with self.db_client.get_async_session() as session:
                result = await session.execute(text("SELECT version()"))
                version = result.scalar()

                # Get connection count
                result = await session.execute(
                    text("SELECT count(*) FROM pg_stat_activity")
                )
                connection_count = result.scalar()

                # Check for locks
                result = await session.execute(
                    text("""
                        SELECT count(*) FROM pg_locks 
                        WHERE NOT granted
                    """)
                )
                blocked_queries = result.scalar()

            response_time = (time.time() - start_time) * 1000

            # Determine status
            status = ValidationStatus.HEALTHY
            if response_time > 1000:  # > 1 second
                status = ValidationStatus.WARNING
            if blocked_queries > 0:
                status = ValidationStatus.WARNING

            self._database_health.append(
                DatabaseHealthStatus(
                    database=DatabaseType.POSTGRESQL,
                    is_connected=True,
                    response_time_ms=response_time,
                    status=status,
                    version=version,
                    connection_count=connection_count,
                    metadata={
                        "blocked_queries": blocked_queries,
                        "degraded_mode": False,
                    },
                )
            )

            if blocked_queries > 0:
                self._validation_issues.append(
                    ValidationIssue(
                        database=DatabaseType.POSTGRESQL,
                        severity=ValidationStatus.WARNING,
                        category="performance",
                        description=f"Found {blocked_queries} blocked queries",
                        recommendation="Check for long-running transactions or deadlocks",
                    )
                )

        except Exception as e:
            logger.error(f"PostgreSQL health check failed: {e}")
            self._database_health.append(
                DatabaseHealthStatus(
                    database=DatabaseType.POSTGRESQL,
                    is_connected=False,
                    response_time_ms=0,
                    status=ValidationStatus.CRITICAL,
                    error_message=str(e),
                )
            )

            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.POSTGRESQL,
                    severity=ValidationStatus.CRITICAL,
                    category="connectivity",
                    description="PostgreSQL connection failed",
                    details={"error": str(e)},
                    recommendation="Check database connection settings and ensure PostgreSQL is running",
                )
            )

    async def _check_redis_health(self) -> None:
        """Check Redis database health"""
        start_time = time.time()

        try:
            # Test basic connectivity
            await self.redis_manager.set("health_check", "test", ex=10)
            result = await self.redis_manager.get("health_check")
            await self.redis_manager.delete("health_check")

            response_time = (time.time() - start_time) * 1000

            # Get Redis info
            connection_info = self.redis_manager.get_connection_info()

            # Determine status
            status = ValidationStatus.HEALTHY
            if response_time > 500:  # > 500ms
                status = ValidationStatus.WARNING
            if self.redis_manager.is_degraded():
                status = ValidationStatus.WARNING

            self._database_health.append(
                DatabaseHealthStatus(
                    database=DatabaseType.REDIS,
                    is_connected=True,
                    response_time_ms=response_time,
                    status=status,
                    metadata={
                        "degraded_mode": self.redis_manager.is_degraded(),
                        "memory_cache_size": connection_info.get(
                            "memory_cache_size", 0
                        ),
                        "connection_failures": connection_info.get(
                            "connection_failures", 0
                        ),
                    },
                )
            )

            if self.redis_manager.is_degraded():
                self._validation_issues.append(
                    ValidationIssue(
                        database=DatabaseType.REDIS,
                        severity=ValidationStatus.WARNING,
                        category="degraded_mode",
                        description="Redis is operating in degraded mode",
                        recommendation="Check Redis connection and resolve connectivity issues",
                    )
                )

        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            self._database_health.append(
                DatabaseHealthStatus(
                    database=DatabaseType.REDIS,
                    is_connected=False,
                    response_time_ms=0,
                    status=ValidationStatus.CRITICAL,
                    error_message=str(e),
                )
            )

            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.REDIS,
                    severity=ValidationStatus.CRITICAL,
                    category="connectivity",
                    description="Redis connection failed",
                    details={"error": str(e)},
                    recommendation="Check Redis connection settings and ensure Redis is running",
                )
            )

    async def _validate_cross_database_references(self) -> None:
        """Validate cross-database reference integrity"""
        logger.info("Validating cross-database reference integrity")

        try:
            # Check Redis cache consistency
            await self._validate_redis_cache_consistency()

            # Check orphaned records
            await self._check_orphaned_records()

        except Exception as e:
            logger.error(f"Cross-database validation failed: {e}")
            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.POSTGRESQL,
                    severity=ValidationStatus.CRITICAL,
                    category="cross_reference",
                    description=f"Cross-database validation failed: {str(e)}",
                    details={"error": str(e)},
                )
            )

    async def _validate_redis_cache_consistency(self) -> None:
        """Validate Redis cache consistency with PostgreSQL"""
        try:
            # Check for stale cache entries
            # This is a simplified check - in production you'd want more comprehensive validation
            cache_info = self.redis_manager.get_connection_info()

            if cache_info.get("memory_cache_size", 0) > 1000:
                self._validation_issues.append(
                    ValidationIssue(
                        database=DatabaseType.REDIS,
                        severity=ValidationStatus.WARNING,
                        category="cache_size",
                        description="Redis memory cache is large, may indicate stale entries",
                        details={"cache_size": cache_info.get("memory_cache_size", 0)},
                        recommendation="Consider cache cleanup or TTL adjustment",
                    )
                )

        except Exception as e:
            logger.error(f"Redis cache validation failed: {e}")
            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.REDIS,
                    severity=ValidationStatus.WARNING,
                    category="cache_validation",
                    description=f"Redis cache validation failed: {str(e)}",
                    details={"error": str(e)},
                )
            )

    async def _check_orphaned_records(self) -> None:
        """Check for orphaned records across databases"""
        try:
            async with self.db_client.get_async_session() as session:
                # Check for messages without conversations
                result = await session.execute(
                    text("""
                        SELECT COUNT(*) FROM messages m
                        LEFT JOIN conversations c ON m.conversation_id = c.id
                        WHERE c.id IS NULL
                    """)
                )
                orphaned_messages = result.scalar()

                if orphaned_messages > 0:
                    self._validation_issues.append(
                        ValidationIssue(
                            database=DatabaseType.POSTGRESQL,
                            severity=ValidationStatus.WARNING,
                            category="orphaned_records",
                            description=f"Found {orphaned_messages} orphaned messages",
                            details={"count": orphaned_messages},
                            recommendation="Clean up orphaned messages",
                            auto_fixable=True,
                        )
                    )

                # Check for sessions without users
                result = await session.execute(
                    text("""
                        SELECT COUNT(*) FROM auth_sessions s
                        LEFT JOIN auth_users u ON s.user_id = u.user_id
                        WHERE u.user_id IS NULL
                    """)
                )
                orphaned_sessions = result.scalar()

                if orphaned_sessions > 0:
                    self._validation_issues.append(
                        ValidationIssue(
                            database=DatabaseType.POSTGRESQL,
                            severity=ValidationStatus.WARNING,
                            category="orphaned_records",
                            description=f"Found {orphaned_sessions} orphaned sessions",
                            details={"count": orphaned_sessions},
                            recommendation="Clean up orphaned sessions",
                            auto_fixable=True,
                        )
                    )

        except Exception as e:
            logger.error(f"Orphaned records check failed: {e}")
            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.POSTGRESQL,
                    severity=ValidationStatus.WARNING,
                    category="orphaned_check",
                    description=f"Orphaned records check failed: {str(e)}",
                    details={"error": str(e)},
                )
            )

    async def _validate_migration_status(self) -> None:
        """Validate database migration status"""
        logger.info("Validating migration status")

        try:
            async with self.db_client.get_async_session() as session:
                # Check if all expected tables exist
                result = await session.execute(
                    text("""
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                    """)
                )
                existing_tables = {row[0] for row in result.fetchall()}

                # Expected tables based on models
                expected_tables = {
                    "tenants",
                    "auth_users",
                    "conversations",
                    "messages",
                    "memory_items",
                    "extensions",
                    "llm_providers",
                    "llm_requests",
                    "audit_log",
                    "auth_sessions",
                    "hooks",
                    "files",
                    "webhooks",
                    "usage_counters",
                    "rate_limits",
                }

                missing_tables = expected_tables - existing_tables
                if missing_tables:
                    self._validation_issues.append(
                        ValidationIssue(
                            database=DatabaseType.POSTGRESQL,
                            severity=ValidationStatus.CRITICAL,
                            category="missing_tables",
                            description=f"Missing database tables: {', '.join(missing_tables)}",
                            details={"missing_tables": list(missing_tables)},
                            recommendation="Run database migrations to create missing tables",
                        )
                    )

                # Check for migration tracking table
                if "alembic_version" not in existing_tables:
                    self._validation_issues.append(
                        ValidationIssue(
                            database=DatabaseType.POSTGRESQL,
                            severity=ValidationStatus.WARNING,
                            category="migration_tracking",
                            description="Migration tracking table (alembic_version) not found",
                            recommendation="Initialize Alembic migration tracking",
                        )
                    )
                else:
                    # Check current migration version
                    result = await session.execute(
                        text("SELECT version_num FROM alembic_version")
                    )
                    current_version = result.scalar()

                    if not current_version:
                        self._validation_issues.append(
                            ValidationIssue(
                                database=DatabaseType.POSTGRESQL,
                                severity=ValidationStatus.WARNING,
                                category="migration_version",
                                description="No migration version found in tracking table",
                                recommendation="Check migration status and run pending migrations",
                            )
                        )

        except Exception as e:
            logger.error(f"Migration validation failed: {e}")
            self._validation_issues.append(
                ValidationIssue(
                    database=DatabaseType.POSTGRESQL,
                    severity=ValidationStatus.CRITICAL,
                    category="migration_validation",
                    description=f"Migration validation failed: {str(e)}",
                    details={"error": str(e)},
                )
            )

    async def _identify_cleanup_needs(self) -> List[str]:
        """Identify test/demo data that needs cleanup"""
        logger.info("Identifying cleanup needs")
        cleanup_recommendations = []

        try:
            # Check data directory for test files
            await self._check_data_directory_cleanup(cleanup_recommendations)

            # Check database for demo users
            await self._check_demo_users_cleanup(cleanup_recommendations)

            # Check for test data patterns
            await self._check_test_data_patterns(cleanup_recommendations)

        except Exception as e:
            logger.error(f"Cleanup identification failed: {e}")
            cleanup_recommendations.append(f"Cleanup identification failed: {str(e)}")

        return cleanup_recommendations

    async def _check_data_directory_cleanup(self, recommendations: List[str]) -> None:
        """Check data directory for files that need cleanup"""
        try:
            # Check users.json for demo accounts
            users_file = self.data_directory / "users.json"
            if users_file.exists():
                with open(users_file, "r") as f:
                    users_data = json.load(f)

                demo_users = []
                for email, user_data in users_data.items():
                    if email in self.demo_patterns["emails"]:
                        demo_users.append(email)
                    elif user_data.get("user_id") in self.demo_patterns["user_ids"]:
                        demo_users.append(email)

                if demo_users:
                    recommendations.append(
                        f"Remove demo users from data/users.json: {', '.join(demo_users)}"
                    )

            # Check for test databases
            test_db_file = self.data_directory / "kari_automation.db"
            if test_db_file.exists():
                file_size = test_db_file.stat().st_size
                if file_size > 1024 * 1024:  # > 1MB
                    recommendations.append(
                        f"Large test database file found: {test_db_file} ({file_size} bytes) - consider cleanup"
                    )

            # Check for temporary files
            temp_patterns = ["*.tmp", "*.temp", "*.log", "*.backup"]
            for pattern in temp_patterns:
                temp_files = list(self.data_directory.glob(f"**/{pattern}"))
                if temp_files:
                    recommendations.append(
                        f"Remove temporary files: {len(temp_files)} files matching {pattern}"
                    )

        except Exception as e:
            logger.error(f"Data directory cleanup check failed: {e}")
            recommendations.append(f"Data directory cleanup check failed: {str(e)}")

    async def _check_demo_users_cleanup(self, recommendations: List[str]) -> None:
        """Check database for demo users that need cleanup"""
        try:
            async with self.db_client.get_async_session() as session:
                # Check for demo users in database
                result = await session.execute(
                    select(AuthUser.email, AuthUser.user_id, AuthUser.full_name).where(
                        AuthUser.email.in_(self.demo_patterns["emails"])
                    )
                )
                demo_users = result.fetchall()

                if demo_users:
                    user_list = [
                        f"{user.email} ({user.full_name})" for user in demo_users
                    ]
                    recommendations.append(
                        f"Remove demo users from database: {', '.join(user_list)}"
                    )

                # Check for test conversations
                result = await session.execute(
                    select(func.count(TenantConversation.id))
                    .join(AuthUser, TenantConversation.user_id == AuthUser.user_id)
                    .where(AuthUser.email.in_(self.demo_patterns["emails"]))
                )
                demo_conversations = result.scalar()

                if demo_conversations > 0:
                    recommendations.append(
                        f"Remove {demo_conversations} conversations from demo users"
                    )

        except Exception as e:
            logger.error(f"Demo users cleanup check failed: {e}")
            recommendations.append(f"Demo users cleanup check failed: {str(e)}")

    async def _check_test_data_patterns(self, recommendations: List[str]) -> None:
        """Check for test data patterns in database"""
        try:
            async with self.db_client.get_async_session() as session:
                # Check for test memory items
                result = await session.execute(
                    select(func.count(TenantMemoryItem.id)).where(
                        TenantMemoryItem.content.like("%test%")
                    )
                )
                test_memory_items = result.scalar()

                if test_memory_items > 10:  # Threshold for concern
                    recommendations.append(
                        f"Review {test_memory_items} memory items containing 'test' - may be test data"
                    )

                # Check for old audit logs
                result = await session.execute(
                    select(func.count(AuditLog.event_id)).where(
                        AuditLog.created_at < datetime.utcnow() - timedelta(days=90)
                    )
                )
                old_audit_logs = result.scalar()

                if old_audit_logs > 1000:
                    recommendations.append(
                        f"Archive or remove {old_audit_logs} old audit log entries (>90 days)"
                    )

        except Exception as e:
            logger.error(f"Test data patterns check failed: {e}")
            recommendations.append(f"Test data patterns check failed: {str(e)}")

    async def _collect_performance_metrics(self) -> Dict[str, Any]:
        """Collect performance metrics from all databases"""
        metrics = {}

        try:
            # PostgreSQL metrics
            async with self.db_client.get_async_session() as session:
                # Database size
                result = await session.execute(
                    text("SELECT pg_database_size(current_database())")
                )
                db_size = result.scalar()

                # Table sizes
                result = await session.execute(
                    text("""
                        SELECT schemaname, tablename, pg_total_relation_size(schemaname||'.'||tablename) as size
                        FROM pg_tables 
                        WHERE schemaname = 'public'
                        ORDER BY size DESC
                        LIMIT 10
                    """)
                )
                table_sizes = [
                    {"table": f"{row[0]}.{row[1]}", "size_bytes": row[2]}
                    for row in result.fetchall()
                ]

                metrics["postgresql"] = {
                    "database_size_bytes": db_size,
                    "largest_tables": table_sizes,
                }

            # Redis metrics
            redis_info = self.redis_manager.get_connection_info()
            metrics["redis"] = {
                "degraded_mode": redis_info.get("degraded_mode", False),
                "memory_cache_size": redis_info.get("memory_cache_size", 0),
                "connection_failures": redis_info.get("connection_failures", 0),
            }

        except Exception as e:
            logger.error(f"Performance metrics collection failed: {e}")
            metrics["error"] = str(e)

        return metrics

    def _generate_report(
        self, cleanup_recommendations: List[str], performance_metrics: Dict[str, Any]
    ) -> ConsistencyReport:
        """Generate comprehensive validation report"""

        # Determine overall status
        overall_status = ValidationStatus.HEALTHY

        # Check database health
        for health in self._database_health:
            if health.status == ValidationStatus.CRITICAL:
                overall_status = ValidationStatus.CRITICAL
                break
            elif (
                health.status == ValidationStatus.WARNING
                and overall_status == ValidationStatus.HEALTHY
            ):
                overall_status = ValidationStatus.WARNING

        # Check validation issues
        critical_issues = [
            i
            for i in self._validation_issues
            if i.severity == ValidationStatus.CRITICAL
        ]
        warning_issues = [
            i for i in self._validation_issues if i.severity == ValidationStatus.WARNING
        ]

        if critical_issues:
            overall_status = ValidationStatus.CRITICAL
        elif warning_issues and overall_status == ValidationStatus.HEALTHY:
            overall_status = ValidationStatus.WARNING

        # Generate summary
        summary = {
            "total_issues": len(self._validation_issues),
            "critical_issues": len(critical_issues),
            "warning_issues": len(warning_issues),
            "auto_fixable_issues": len(
                [i for i in self._validation_issues if i.auto_fixable]
            ),
            "cleanup_recommendations": len(cleanup_recommendations),
            "databases_healthy": len(
                [h for h in self._database_health if h.is_connected]
            ),
            "databases_total": len(self._database_health),
        }

        return ConsistencyReport(
            timestamp=datetime.utcnow(),
            overall_status=overall_status,
            database_health=self._database_health,
            validation_issues=self._validation_issues,
            cross_reference_issues=[
                i for i in self._validation_issues if i.category.startswith("cross_")
            ],
            migration_issues=[
                i
                for i in self._validation_issues
                if i.category.startswith("migration_")
            ],
            cleanup_recommendations=cleanup_recommendations,
            performance_metrics=performance_metrics,
            summary=summary,
        )

    async def cleanup_demo_data(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up demo/test data from databases and data directory.

        Args:
            dry_run: If True, only report what would be cleaned without making changes

        Returns:
            Dict containing cleanup results
        """
        logger.info(f"Starting demo data cleanup (dry_run={dry_run})")

        cleanup_results = {
            "dry_run": dry_run,
            "timestamp": datetime.utcnow().isoformat(),
            "actions_taken": [],
            "errors": [],
        }

        try:
            # Clean up data directory files
            await self._cleanup_data_directory(cleanup_results, dry_run)

            # Clean up database demo users
            await self._cleanup_demo_users(cleanup_results, dry_run)

            # Clean up orphaned records
            if not dry_run:
                await self._cleanup_orphaned_records(cleanup_results)

        except Exception as e:
            logger.error(f"Demo data cleanup failed: {e}")
            cleanup_results["errors"].append(str(e))

        return cleanup_results

    async def _cleanup_data_directory(
        self, results: Dict[str, Any], dry_run: bool
    ) -> None:
        """Clean up demo data from data directory"""
        try:
            users_file = self.data_directory / "users.json"
            if users_file.exists():
                with open(users_file, "r") as f:
                    users_data = json.load(f)

                original_count = len(users_data)
                demo_users_removed = []

                # Remove demo users
                for email in list(users_data.keys()):
                    if email in self.demo_patterns["emails"]:
                        if not dry_run:
                            del users_data[email]
                        demo_users_removed.append(email)

                if demo_users_removed:
                    action = f"{'Would remove' if dry_run else 'Removed'} {len(demo_users_removed)} demo users from users.json: {', '.join(demo_users_removed)}"
                    results["actions_taken"].append(action)

                    if not dry_run:
                        # Backup original file
                        backup_file = users_file.with_suffix(
                            f".backup.{int(time.time())}"
                        )
                        users_file.rename(backup_file)

                        # Write cleaned data
                        with open(users_file, "w") as f:
                            json.dump(users_data, f, indent=2)

                        results["actions_taken"].append(
                            f"Backed up original users.json to {backup_file.name}"
                        )

        except Exception as e:
            logger.error(f"Data directory cleanup failed: {e}")
            results["errors"].append(f"Data directory cleanup failed: {str(e)}")

    async def _cleanup_demo_users(self, results: Dict[str, Any], dry_run: bool) -> None:
        """Clean up demo users from database"""
        try:
            async with self.db_client.get_async_session() as session:
                # Find demo users
                result = await session.execute(
                    select(AuthUser).where(
                        AuthUser.email.in_(self.demo_patterns["emails"])
                    )
                )
                demo_users = result.fetchall()

                if demo_users:
                    user_emails = [user.email for user in demo_users]
                    action = f"{'Would remove' if dry_run else 'Removed'} {len(demo_users)} demo users from database: {', '.join(user_emails)}"
                    results["actions_taken"].append(action)

                    if not dry_run:
                        # Delete demo users (cascading deletes will handle related records)
                        for user in demo_users:
                            await session.delete(user)
                        await session.commit()

        except Exception as e:
            logger.error(f"Demo users cleanup failed: {e}")
            results["errors"].append(f"Demo users cleanup failed: {str(e)}")

    async def _cleanup_orphaned_records(self, results: Dict[str, Any]) -> None:
        """Clean up orphaned records from database"""
        try:
            async with self.db_client.get_async_session() as session:
                # Clean up orphaned messages
                result = await session.execute(
                    text("""
                        DELETE FROM messages 
                        WHERE conversation_id NOT IN (SELECT id FROM conversations)
                    """)
                )
                orphaned_messages = result.rowcount

                if orphaned_messages > 0:
                    results["actions_taken"].append(
                        f"Removed {orphaned_messages} orphaned messages"
                    )

                # Clean up orphaned sessions
                result = await session.execute(
                    text("""
                        DELETE FROM auth_sessions 
                        WHERE user_id NOT IN (SELECT user_id FROM auth_users)
                    """)
                )
                orphaned_sessions = result.rowcount

                if orphaned_sessions > 0:
                    results["actions_taken"].append(
                        f"Removed {orphaned_sessions} orphaned sessions"
                    )

                await session.commit()

        except Exception as e:
            logger.error(f"Orphaned records cleanup failed: {e}")
            results["errors"].append(f"Orphaned records cleanup failed: {str(e)}")

    async def auto_fix_issues(self, issues: List[ValidationIssue]) -> Dict[str, Any]:
        """
        Automatically fix issues that are marked as auto-fixable.

        Args:
            issues: List of validation issues to attempt to fix

        Returns:
            Dict containing fix results
        """
        logger.info(f"Attempting to auto-fix {len(issues)} issues")

        fix_results = {
            "timestamp": datetime.utcnow().isoformat(),
            "attempted_fixes": 0,
            "successful_fixes": 0,
            "failed_fixes": 0,
            "fix_details": [],
            "errors": [],
        }

        auto_fixable_issues = [issue for issue in issues if issue.auto_fixable]
        fix_results["attempted_fixes"] = len(auto_fixable_issues)

        for issue in auto_fixable_issues:
            try:
                success = await self._fix_individual_issue(issue)
                if success:
                    fix_results["successful_fixes"] += 1
                    fix_results["fix_details"].append(f"Fixed: {issue.description}")
                else:
                    fix_results["failed_fixes"] += 1
                    fix_results["fix_details"].append(
                        f"Failed to fix: {issue.description}"
                    )

            except Exception as e:
                logger.error(f"Error fixing issue {issue.description}: {e}")
                fix_results["failed_fixes"] += 1
                fix_results["errors"].append(
                    f"Error fixing '{issue.description}': {str(e)}"
                )

        return fix_results

    async def _fix_individual_issue(self, issue: ValidationIssue) -> bool:
        """Fix an individual validation issue"""
        try:
            if issue.category == "orphaned_records":
                if "orphaned messages" in issue.description:
                    async with self.db_client.get_async_session() as session:
                        result = await session.execute(
                            text("""
                                DELETE FROM messages 
                                WHERE conversation_id NOT IN (SELECT id FROM conversations)
                            """)
                        )
                        await session.commit()
                        return True

                elif "orphaned sessions" in issue.description:
                    async with self.db_client.get_async_session() as session:
                        result = await session.execute(
                            text("""
                                DELETE FROM auth_sessions 
                                WHERE user_id NOT IN (SELECT user_id FROM auth_users)
                            """)
                        )
                        await session.commit()
                        return True

            # Add more auto-fix logic for other issue types as needed
            return False

        except Exception as e:
            logger.error(f"Failed to fix issue {issue.description}: {e}")
            return False


# Global instance
_database_consistency_validator: Optional[DatabaseConsistencyValidator] = None


def get_database_consistency_validator() -> DatabaseConsistencyValidator:
    """Get global database consistency validator instance"""
    global _database_consistency_validator
    if _database_consistency_validator is None:
        _database_consistency_validator = DatabaseConsistencyValidator()
    return _database_consistency_validator


async def validate_database_consistency(
    data_directory: str = "data",
    enable_auto_fix: bool = False,
) -> ConsistencyReport:
    """
    Convenience function to perform database consistency validation.

    Args:
        data_directory: Path to data directory to check for cleanup needs
        enable_auto_fix: Whether to automatically fix issues that can be auto-fixed

    Returns:
        ConsistencyReport: Complete validation report
    """
    validator = DatabaseConsistencyValidator(
        data_directory=data_directory,
        enable_auto_fix=enable_auto_fix,
    )

    report = await validator.validate_all()

    # Auto-fix issues if enabled
    if enable_auto_fix:
        auto_fixable_issues = [
            issue for issue in report.validation_issues if issue.auto_fixable
        ]
        if auto_fixable_issues:
            logger.info(f"Auto-fixing {len(auto_fixable_issues)} issues")
            fix_results = await validator.auto_fix_issues(auto_fixable_issues)

            # Add fix results to report metadata
            if "fix_results" not in report.performance_metrics:
                report.performance_metrics["fix_results"] = fix_results

    return report
