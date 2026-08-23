"""
Production Database Services Factory
Comprehensive factory for initializing and wiring all database-related services.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DatabaseServiceConfig:
    """Configuration for database services."""

    def __init__(
        self,
        # Core database settings
        enable_multi_tenant: bool = True,
        enable_migrations: bool = True,
        auto_migrate: bool = False,
        # Manager settings
        enable_conversation_manager: bool = True,
        enable_memory_manager: bool = True,
        enable_tenant_manager: bool = True,
        # Canonical repository settings (DATA-CONVERGE-1)
        enable_canonical_memory_repository: bool = False,
        enable_canonical_conversation_repository: bool = False,
        enable_canonical_artifact_store: bool = False,
        # Performance settings
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_pre_ping: bool = True,
        pool_recycle: int = 3600,
        # Operational settings
        enable_health_checks: bool = True,
        enable_audit_logging: bool = True,
    ):
        self.enable_multi_tenant = enable_multi_tenant
        self.enable_migrations = enable_migrations
        self.auto_migrate = auto_migrate

        self.enable_conversation_manager = enable_conversation_manager
        self.enable_memory_manager = enable_memory_manager
        self.enable_tenant_manager = enable_tenant_manager

        self.enable_canonical_memory_repository = enable_canonical_memory_repository
        self.enable_canonical_conversation_repository = enable_canonical_conversation_repository
        self.enable_canonical_artifact_store = enable_canonical_artifact_store

        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_pre_ping = pool_pre_ping
        self.pool_recycle = pool_recycle

        self.enable_health_checks = enable_health_checks
        self.enable_audit_logging = enable_audit_logging


class DatabaseServiceFactory:
    """
    Factory for creating and wiring database services.

    This factory ensures all database services (clients, managers, migrations)
    are properly initialized, configured, and wired together for production use.
    """

    def __init__(self, config: Optional[DatabaseServiceConfig] = None):
        self.config = config or DatabaseServiceConfig()
        self._services = {}
        logger.info("DatabaseServiceFactory initialized")

    def create_database_client(self):
        """Create and configure the main database client."""
        try:
            from ai_karen_engine.database.client import (
                MultiTenantPostgresClient,
                DatabaseClient,
            )

            if self.config.enable_multi_tenant:
                client = MultiTenantPostgresClient()
                self._services["database_client"] = client
                logger.info("Multi-tenant database client created successfully")
            else:
                client = DatabaseClient()
                self._services["database_client"] = client
                logger.info("Standard database client created successfully")

            return client

        except Exception as e:
            logger.error(f"Failed to create database client: {e}")
            return None

    def create_migration_manager(self):
        """Create and configure migration manager."""
        if not self.config.enable_migrations:
            logger.info("Migration manager disabled by configuration")
            return None

        try:
            from ai_karen_engine.database.migration_manager import MigrationManager

            manager = MigrationManager()
            self._services["migration_manager"] = manager
            logger.info("Migration manager created successfully")

            # Auto-migrate if configured
            if self.config.auto_migrate:
                logger.info("Running auto-migration...")
                try:
                    # Run pending migrations
                    manager.apply_pending_migrations()
                    logger.info("Auto-migration completed successfully")
                except Exception as e:
                    logger.error(f"Auto-migration failed: {e}")

            return manager

        except Exception as e:
            logger.error(f"Failed to create migration manager: {e}")
            return None

    def create_conversation_manager(self):
        """Create and configure conversation manager."""
        if not self.config.enable_conversation_manager:
            logger.info("Conversation manager disabled by configuration")
            return None

        try:
            from ai_karen_engine.database.conversation_manager import (
                ConversationManager,
            )

            # Get database client
            db_client = self.get_service("database_client")
            if not db_client:
                db_client = self.create_database_client()

            manager = ConversationManager(db_client=db_client)
            self._services["conversation_manager"] = manager
            logger.info("Conversation manager created successfully")
            return manager

        except Exception as e:
            logger.error(f"Failed to create conversation manager: {e}")
            return None

    def create_memory_manager(self):
        """Create and configure the next-gen memory runtime manager and profile service."""
        if not self.config.enable_memory_manager:
            logger.info("Memory manager disabled by configuration")
            return None

        try:
            from ai_karen_engine.core.memory import get_memory_manager
            from ai_karen_engine.core.memory.profile_synthesis import get_profile_service

            # Get database client to retrieve session factory
            db_client = self.get_service("database_client")
            if not db_client:
                db_client = self.create_database_client()

            # Initialize Next-Gen Memory Runtime Manager (Singleton)
            manager = get_memory_manager()
            if hasattr(db_client, "get_async_session"):
                manager.set_db_session_factory(db_client.get_async_session)
                
            # Initialize Profile Service (Singleton)
            profile_svc = get_profile_service()
            if hasattr(db_client, "get_async_session"):
                profile_svc.set_db_session_factory(db_client.get_async_session)

            self._services["memory_manager"] = manager
            self._services["profile_service"] = profile_svc
            
            # Initialize EchoCore Sleep-Cycle Engine (Offline Consolidation)
            from ai_karen_engine.echocore.sleep_cycle import get_sleep_cycle_engine
            echo_engine = get_sleep_cycle_engine()
            if hasattr(db_client, "get_async_session"):
                echo_engine.set_db_session_factory(db_client.get_async_session)
            self._services["echocore_engine"] = echo_engine

            logger.info("Next-gen memory runtime, profile synthesis, and EchoCore services created successfully")
            return manager

        except Exception as e:
            logger.error(f"Failed to create memory manager: {e}")
            return None

    def create_tenant_manager(self):
        """Create and configure tenant manager."""
        if not self.config.enable_tenant_manager:
            logger.info("Tenant manager disabled by configuration")
            return None

        try:
            from ai_karen_engine.database.tenant_manager import TenantManager

            # Get database client
            db_client = self.get_service("database_client")
            if not db_client:
                db_client = self.create_database_client()

            manager = TenantManager(db_client=db_client)
            self._services["tenant_manager"] = manager
            logger.info("Tenant manager created successfully")
            return manager

        except Exception as e:
            logger.error(f"Failed to create tenant manager: {e}")
            return None

    def create_canonical_repositories(self):
        """Create canonical DATA-CONVERGE-1 repositories."""
        if not any(
            [
                self.config.enable_canonical_memory_repository,
                self.config.enable_canonical_conversation_repository,
                self.config.enable_canonical_artifact_store,
            ]
        ):
            return None

        try:
            from ai_karen_engine.services.database.repositories import RepositoryFactory
            from ai_karen_engine.database.client import MultiTenantPostgresClient

            db_client = self.get_service("database_client")
            if not db_client:
                db_client = self.create_database_client()
            if not db_client:
                logger.error("Cannot create canonical repositories: database client unavailable")
                return None

            session_factory = getattr(db_client, "get_async_session", None)
            if session_factory is None:
                logger.error("Cannot create canonical repositories: session factory unavailable")
                return None

            storage_client = None
            if self.config.enable_canonical_artifact_store:
                try:
                    from ai_karen_engine.integrations.supabase_client import get_supabase_client
                    storage_client = get_supabase_client()
                except Exception as exc:
                    logger.warning("Supabase client unavailable for ArtifactStore: %s", exc)

            factory = RepositoryFactory(
                session_factory=session_factory,
                storage_client=storage_client,
            )

            if self.config.enable_canonical_memory_repository:
                self._services["memory_repository"] = factory.create_memory_repository()
                if "memory_manager" in self._services and hasattr(self._services["memory_manager"], "memory_repository"):
                    self._services["memory_manager"].memory_repository = self._services["memory_repository"]

            if self.config.enable_canonical_conversation_repository:
                self._services["conversation_repository"] = factory.create_conversation_repository()

            if self.config.enable_canonical_artifact_store:
                self._services["artifact_store"] = factory.create_artifact_store()

            logger.info("Canonical repositories created successfully")
            return factory

        except Exception as e:
            logger.error(f"Failed to create canonical repositories: {e}")
            return None

    def initialize_database(self):
        """
        Initialize database: create tables, run migrations, seed data.

        This should be called during application startup.
        """
        logger.info("Initializing database...")

        try:
            # Get or create database client
            db_client = self.get_service("database_client")
            if not db_client:
                db_client = self.create_database_client()

            if not db_client:
                logger.error("Cannot initialize database: client creation failed")
                return False

            # Create tables
            try:
                db_client.create_tables()
                logger.info("Database tables created/verified")
            except Exception as e:
                logger.warning(f"Table creation failed (may already exist): {e}")

            # Run migrations
            if self.config.enable_migrations:
                migration_manager = self.get_service("migration_manager")
                if not migration_manager:
                    migration_manager = self.create_migration_manager()

            # Seed initial data if needed
            try:
                from ai_karen_engine.database.seed.auth_seed import seed_default_auth
                from ai_karen_engine.database.seed.rbac_seed import seed_rbac_data

                # Seed auth data
                seed_default_auth()
                logger.info("Auth data seeded")

                # Seed RBAC data
                seed_rbac_data()
                logger.info("RBAC data seeded")

            except Exception as e:
                logger.warning(f"Data seeding failed (may already exist): {e}")

            logger.info("Database initialization completed successfully")
            return True

        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            return False

    def create_all_services(self) -> Dict[str, Any]:
        """
        Create all database services and wire them together.

        This is the main entry point for full database system initialization.

        Returns:
            Dictionary of all created services
        """
        logger.info("Creating all database services")

        # Create core services in dependency order
        self.create_database_client()
        self.create_migration_manager()
        self.create_conversation_manager()
        self.create_memory_manager()
        self.create_tenant_manager()

        logger.info(f"All database services created: {list(self._services.keys())}")
        return self._services

    def get_service(self, service_name: str):
        """Get a service by name."""
        return self._services.get(service_name)

    def get_all_services(self) -> Dict[str, Any]:
        """Get all created services."""
        return self._services.copy()

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on database services.

        Returns:
            Dictionary with health status of all services
        """
        if not self.config.enable_health_checks:
            return {"health_checks_disabled": True}

        health = {}

        # Check database client
        db_client = self.get_service("database_client")
        if db_client:
            try:
                status = db_client.health_check()
                health["database"] = {
                    "healthy": status.is_healthy,
                    "status": status.status,
                    "response_time_ms": status.response_time_ms,
                }
            except Exception as e:
                health["database"] = {"healthy": False, "error": str(e)}

        # Check managers
        for manager_name in [
            "conversation_manager",
            "memory_manager",
            "tenant_manager",
        ]:
            manager = self.get_service(manager_name)
            if manager:
                health[manager_name] = {"exists": True}

        return health


# Global factory instance
_global_factory: Optional[DatabaseServiceFactory] = None


def get_database_service_factory(
    config: Optional[DatabaseServiceConfig] = None,
) -> DatabaseServiceFactory:
    """
    Get or create global database service factory.

    Args:
        config: Optional configuration for the factory

    Returns:
        DatabaseServiceFactory instance
    """
    global _global_factory

    if _global_factory is None:
        _global_factory = DatabaseServiceFactory(config)
        logger.info("Global database service factory created")

    return _global_factory


def get_database_client():
    """Get or create global database client."""
    factory = get_database_service_factory()
    client = factory.get_service("database_client")

    if client is None:
        client = factory.create_database_client()

    return client


def get_conversation_manager():
    """Get or create global conversation manager."""
    factory = get_database_service_factory()
    manager = factory.get_service("conversation_manager")

    if manager is None:
        manager = factory.create_conversation_manager()

    return manager


def get_memory_manager():
    """Get or create global memory manager."""
    factory = get_database_service_factory()
    manager = factory.get_service("memory_manager")

    if manager is None:
        manager = factory.create_memory_manager()

    return manager


def get_tenant_manager():
    """Get or create global tenant manager."""
    factory = get_database_service_factory()
    manager = factory.get_service("tenant_manager")

    if manager is None:
        manager = factory.create_tenant_manager()

    return manager


def get_echocore_engine():
    """Get or create global EchoCore engine."""
    factory = get_database_service_factory()
    engine = factory.get_service("echocore_engine")

    if engine is None:
        factory.create_memory_manager()
        engine = factory.get_service("echocore_engine")

    return engine


def initialize_database_for_production():
    """
    Initialize database for production use.

    This is the main entry point for production database initialization.
    Call this during application startup.
    """
    factory = get_database_service_factory()
    return factory.initialize_database()


__all__ = [
    "DatabaseServiceConfig",
    "DatabaseServiceFactory",
    "get_database_service_factory",
    "get_database_client",
    "get_conversation_manager",
    "get_memory_manager",
    "get_tenant_manager",
    "get_echocore_engine",
    "initialize_database_for_production",
]
