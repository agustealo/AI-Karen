"""
Production-grade integration manager for AI Karen.
Orchestrates all database components and provides a unified interface for the application.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.database.tenant_manager import TenantManager, TenantConfig
from ai_karen_engine.database.memory_manager import MemoryManager, MemoryQuery
from ai_karen_engine.database.conversation_manager import ConversationManager, MessageRole
from ai_karen_engine.core.model_runtime.milvus_client import MilvusClient
from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database configuration."""
    postgres_url: Optional[str] = None
    redis_url: Optional[str] = None
    milvus_host: str = "ai-karen-milvus"
    milvus_port: int = 19531
    elasticsearch_host: str = "localhost"
    elasticsearch_port: int = 9200
    pool_size: int = 10
    max_overflow: int = 20
    enable_redis: bool = True
    enable_milvus: bool = True
    enable_elasticsearch: bool = True
    enable_canonical_memory_repository: bool = False
    enable_canonical_conversation_repository: bool = False
    enable_canonical_artifact_store: bool = False


class DatabaseIntegrationManager:
    """Production-grade database integration manager."""
    
    def __init__(self, config: Optional[DatabaseConfig] = None):
        """Initialize database integration manager.
        
        Args:
            config: Database configuration
        """
        self.config = config or DatabaseConfig()
        
        # Core components
        self.db_client: Optional[MultiTenantPostgresClient] = None
        self.milvus_client: Optional[MilvusClient] = None
        self.embedding_manager: Optional[EmbeddingManager] = None
        self.redis_client: Optional[Any] = None
        self.elasticsearch_client: Optional[Any] = None
        
        # Managers
        self.tenant_manager: Optional[TenantManager] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.conversation_manager: Optional[ConversationManager] = None
        
        # Canonical repositories (DATA-CONVERGE-1)
        self.memory_repository: Optional[Any] = None
        self.conversation_repository: Optional[Any] = None
        self.artifact_store: Optional[Any] = None
        
        # State
        self._initialized = False
        self._health_check_interval = 300  # 5 minutes
        self._last_health_check = None
        
    async def initialize(self):
        """Initialize all database components."""
        if self._initialized:
            logger.warning("Database integration manager already initialized")
            return
        
        logger.info("Initializing database integration manager...")
        
        try:
            # Initialize PostgreSQL client
            await self._initialize_postgres()
            
            # Initialize vector database
            if self.config.enable_milvus:
                await self._initialize_milvus()
            
            # Initialize embedding manager
            await self._initialize_embedding_manager()
            
            # Initialize Redis cache
            if self.config.enable_redis:
                await self._initialize_redis()
            
            # Initialize Elasticsearch
            if self.config.enable_elasticsearch:
                await self._initialize_elasticsearch()
            
            # Initialize managers
            await self._initialize_managers()
            
            # Create shared tables
            self.db_client.create_shared_tables()
            
            self._initialized = True
            logger.info("Database integration manager initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database integration manager: {e}")
            await self.cleanup()
            raise
    
    async def _initialize_postgres(self):
        """Initialize PostgreSQL client."""
        logger.info("Initializing PostgreSQL client...")
        
        self.db_client = MultiTenantPostgresClient(
            database_url=self.config.postgres_url,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow
        )
        
        # Test connection
        is_healthy = self.db_client.health_check()
        if not is_healthy:
            raise RuntimeError("PostgreSQL health check failed")
        
        logger.info("PostgreSQL client initialized successfully")
    
    async def _initialize_milvus(self):
        """Initialize Milvus vector database."""
        logger.info("Initializing Milvus client...")
        
        # Optional readiness loop: wait for external Milvus health endpoint before enabling vectors
        # Configure via MILVUS_HEALTH_WAIT_SECONDS (>0 to enable). Defaults to 0 (no wait).
        try:
            max_wait = int(os.getenv("MILVUS_HEALTH_WAIT_SECONDS", "0"))
        except Exception:
            max_wait = 0

        if max_wait > 0:
            health_host = os.getenv("MILVUS_HEALTH_HOST", str(self.config.milvus_host))
            health_port = int(os.getenv("MILVUS_HEALTH_PORT", "9091"))
            health_path = os.getenv("MILVUS_HEALTH_PATH", "/healthz")
            health_url = os.getenv(
                "MILVUS_HEALTH_URL",
                f"http://{health_host}:{health_port}{health_path}"
            )
            interval = max(2, min(10, int(os.getenv("MILVUS_HEALTH_POLL_INTERVAL", "3"))))

            logger.info(
                "Waiting for Milvus health (up to %ss): %s",
                max_wait,
                health_url,
            )

            async def _probe_health(url: str) -> bool:
                # Use stdlib to avoid extra deps
                import urllib.request  # type: ignore
                import json as _json
                try:
                    def _fetch() -> bool:
                        with urllib.request.urlopen(url, timeout=3) as resp:
                            ct = resp.headers.get("Content-Type", "")
                            body = resp.read().decode("utf-8", errors="ignore")
                            if "application/json" in ct:
                                try:
                                    data = _json.loads(body)
                                    # Accept common fields: status/ready/healthy
                                    status = str(data.get("status", "")).lower()
                                    ready = data.get("ready") or data.get("healthy")
                                    return ready is True or status in {"healthy", "ready", "ok"}
                                except Exception:
                                    return False
                            return "healthy" in body.lower() or "ok" == body.strip().lower()
                    return await asyncio.to_thread(_fetch)
                except Exception:
                    return False

            deadline = asyncio.get_event_loop().time() + max_wait
            while asyncio.get_event_loop().time() < deadline:
                ok = await _probe_health(health_url)
                if ok:
                    logger.info("Milvus reported healthy at %s", health_url)
                    break
                await asyncio.sleep(interval)
            else:
                logger.warning(
                    "Milvus health check did not become healthy within %ss; vector features will initialize regardless",
                    max_wait,
                )

        # Initialize the (current) Milvus client implementation
        try:
            self.milvus_client = MilvusClient(
                host=self.config.milvus_host,
                port=self.config.milvus_port
            )

            # Test connection through the client API
            await self.milvus_client.connect()
            health = await self.milvus_client.health_check()

            if health.get("status") != "healthy":
                logger.warning(f"Milvus health check failed: {health}")
                self.milvus_client = None
            else:
                logger.info("Milvus client initialized successfully")

        except Exception as e:
            logger.warning(f"Failed to initialize Milvus: {e}")
            self.milvus_client = None
    
    async def _initialize_embedding_manager(self):
        """Initialize embedding manager."""
        logger.info("Initializing embedding manager...")
        
        try:
            self.embedding_manager = EmbeddingManager()
            await self.embedding_manager.initialize()
            logger.info("Embedding manager initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize embedding manager: {e}")
            raise
    
    async def _initialize_redis(self):
        """Initialize Redis client."""
        logger.info("Initializing Redis client...")
        
        try:
            import aioredis
            
            redis_url = self.config.redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.redis_client = await aioredis.from_url(redis_url)
            
            # Test connection
            await self.redis_client.ping()
            logger.info("Redis client initialized successfully")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Redis: {e}")
            self.redis_client = None
    
    async def _initialize_elasticsearch(self):
        """Initialize Elasticsearch client."""
        logger.info("Initializing Elasticsearch client...")
        
        try:
            from elasticsearch import AsyncElasticsearch
            
            self.elasticsearch_client = AsyncElasticsearch([
                f"http://{self.config.elasticsearch_host}:{self.config.elasticsearch_port}"
            ])
            
            # Test connection
            health = await self.elasticsearch_client.cluster.health()
            if health["status"] not in ["green", "yellow"]:
                logger.warning(f"Elasticsearch cluster unhealthy: {health}")
                self.elasticsearch_client = None
            else:
                logger.info("Elasticsearch client initialized successfully")
                
        except Exception as e:
            logger.warning(f"Failed to initialize Elasticsearch: {e}")
            self.elasticsearch_client = None
    
    async def _initialize_managers(self):
        """Initialize all managers."""
        logger.info("Initializing managers...")
        
        # Tenant manager
        self.tenant_manager = TenantManager(
            db_client=self.db_client,
            milvus_client=self.milvus_client,
            embedding_manager=self.embedding_manager
        )
        
        # Canonical repositories (DATA-CONVERGE-1)
        if self.config.enable_canonical_memory_repository or self.config.enable_canonical_conversation_repository:
            try:
                from ai_karen_engine.services.database.repositories import RepositoryFactory
                session_factory = getattr(self.db_client, "get_async_session", None)
                if session_factory:
                    repo_factory = RepositoryFactory(session_factory=session_factory)
                    if self.config.enable_canonical_memory_repository:
                        self.memory_repository = repo_factory.create_memory_repository()
                    if self.config.enable_canonical_conversation_repository:
                        self.conversation_repository = repo_factory.create_conversation_repository()
            except Exception as exc:
                logger.warning("Failed to initialize canonical repositories: %s", exc)
        
        # Memory manager
        self.memory_manager = MemoryManager(
            db_client=self.db_client,
            milvus_client=self.milvus_client,
            embedding_manager=self.embedding_manager,
            redis_client=self.redis_client,
            elasticsearch_client=self.elasticsearch_client,
            memory_repository=self.memory_repository,
        )
        
        # Conversation manager
        self.conversation_manager = ConversationManager(
            db_client=self.db_client,
            memory_manager=self.memory_manager,
            embedding_manager=self.embedding_manager
        )
        
        logger.info("All managers initialized successfully")
    
    # Tenant Management Methods
    async def create_tenant(
        self,
        name: str,
        slug: str,
        admin_email: str,
        subscription_tier: str = "basic",
        settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new tenant with complete setup."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        config = TenantConfig(
            name=name,
            slug=slug,
            subscription_tier=subscription_tier,
            settings=settings or {}
        )
        
        tenant = await self.tenant_manager.create_tenant(config, admin_email)
        return {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "subscription_tier": tenant.subscription_tier,
            "created_at": tenant.created_at.isoformat()
        }
    
    async def get_tenant(self, tenant_id: Union[str, uuid.UUID]) -> Optional[Dict[str, Any]]:
        """Get tenant information."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        tenant = await self.tenant_manager.get_tenant(tenant_id)
        if not tenant:
            return None
        
        return {
            "tenant_id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "subscription_tier": tenant.subscription_tier,
            "settings": tenant.settings,
            "is_active": tenant.is_active,
            "created_at": tenant.created_at.isoformat(),
            "updated_at": tenant.updated_at.isoformat()
        }
    
    async def get_tenant_stats(self, tenant_id: Union[str, uuid.UUID]) -> Optional[Dict[str, Any]]:
        """Get comprehensive tenant statistics."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        stats = await self.tenant_manager.get_tenant_stats(tenant_id)
        return stats.to_dict() if stats else None
    
    # Memory Management Methods
    async def store_memory(
        self,
        tenant_id: Union[str, uuid.UUID],
        content: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[str]:
        """Store a memory entry."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        return await self.memory_manager.store_memory(
            tenant_id=tenant_id,
            content=content,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata,
            tags=tags
        )
    
    async def query_memories(
        self,
        tenant_id: Union[str, uuid.UUID],
        query_text: str,
        user_id: Optional[str] = None,
        top_k: int = 10,
        similarity_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Query memories with semantic search."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        query = MemoryQuery(
            text=query_text,
            user_id=user_id,
            top_k=top_k,
            similarity_threshold=similarity_threshold
        )
        
        memories = await self.memory_manager.query_memories(tenant_id, query)
        return [memory.to_dict() for memory in memories]
    
    # Conversation Management Methods
    async def create_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_id: str,
        title: Optional[str] = None,
        initial_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new conversation."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        conversation = await self.conversation_manager.create_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            initial_message=initial_message
        )
        
        return conversation.to_dict()
    
    async def add_message(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Add a message to conversation."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        message_role = MessageRole(role)
        message = await self.conversation_manager.add_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=message_role,
            content=content,
            metadata=metadata
        )
        
        return message.to_dict() if message else None
    
    async def get_conversation(
        self,
        tenant_id: Union[str, uuid.UUID],
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get conversation with context."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        conversation = await self.conversation_manager.get_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            include_context=True
        )
        
        return conversation.to_dict() if conversation else None
    
    async def list_conversations(
        self,
        tenant_id: Union[str, uuid.UUID],
        user_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List conversations for a user."""
        if not self._initialized:
            raise RuntimeError("Database integration manager not initialized")
        
        conversations = await self.conversation_manager.list_conversations(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit
        )
        
        return [conv.to_dict() for conv in conversations]
    
    # Health and Maintenance Methods
    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        if not self._initialized:
            return {"status": "unhealthy", "error": "Not initialized"}
        
        health_data = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        # Check PostgreSQL
        if self.db_client:
            is_healthy = self.db_client.health_check()
            health_data["components"]["postgres"] = {
                "status": "healthy" if is_healthy else "unhealthy"
            }
        
        # Check Milvus
        if self.milvus_client:
            try:
                health_data["components"]["milvus"] = await self.milvus_client.health_check()
            except Exception as e:
                health_data["components"]["milvus"] = {"status": "unhealthy", "error": str(e)}
        
        # Check Redis
        if self.redis_client:
            try:
                await self.redis_client.ping()
                health_data["components"]["redis"] = {"status": "healthy"}
            except Exception as e:
                health_data["components"]["redis"] = {"status": "unhealthy", "error": str(e)}
        
        # Check Elasticsearch
        if self.elasticsearch_client:
            try:
                cluster_health = await self.elasticsearch_client.cluster.health()
                health_data["components"]["elasticsearch"] = {
                    "status": "healthy" if cluster_health["status"] in ["green", "yellow"] else "unhealthy",
                    "cluster_status": cluster_health["status"]
                }
            except Exception as e:
                health_data["components"]["elasticsearch"] = {"status": "unhealthy", "error": str(e)}
        
        # Check managers
        if self.tenant_manager:
            health_data["components"]["tenant_manager"] = await self.tenant_manager.health_check()
        
        # Overall status
        component_statuses = [comp.get("status") for comp in health_data["components"].values()]
        if any(status == "unhealthy" for status in component_statuses):
            health_data["status"] = "degraded"
        
        self._last_health_check = datetime.utcnow()
        return health_data
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics."""
        if not self._initialized:
            return {"error": "Not initialized"}
        
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "memory_manager": self.memory_manager.metrics.copy() if self.memory_manager else {},
            "conversation_manager": self.conversation_manager.metrics.copy() if self.conversation_manager else {},
            "database_pools": {}
        }
        
        # Database pool metrics
        if self.db_client and self.db_client.sync_engine:
            pool = self.db_client.sync_engine.pool
            metrics["database_pools"]["postgres"] = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "invalid": pool.invalid()
            }
        
        return metrics
    
    async def maintenance_tasks(self) -> Dict[str, Any]:
        """Run maintenance tasks."""
        if not self._initialized:
            return {"error": "Not initialized"}
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "tasks_completed": []
        }
        
        try:
            # Get all active tenants
            tenants = await self.tenant_manager.list_tenants(active_only=True, limit=1000)
            
            for tenant in tenants:
                tenant_id = tenant.id
                
                # Prune expired memories
                if self.memory_manager:
                    pruned_count = await self.memory_manager.prune_expired_memories(tenant_id)
                    if pruned_count > 0:
                        results["tasks_completed"].append(
                            f"Pruned {pruned_count} expired memories for tenant {tenant_id}"
                        )
                
                # Cleanup inactive conversations
                if self.conversation_manager:
                    inactive_count = await self.conversation_manager.cleanup_inactive_conversations(tenant_id)
                    if inactive_count > 0:
                        results["tasks_completed"].append(
                            f"Marked {inactive_count} conversations as inactive for tenant {tenant_id}"
                        )
            
            results["status"] = "completed"
            
        except Exception as e:
            results["status"] = "failed"
            results["error"] = str(e)
            logger.error(f"Maintenance tasks failed: {e}")
        
        return results
    
    async def cleanup(self):
        """Cleanup all resources."""
        logger.info("Cleaning up database integration manager...")
        
        try:
            if self.redis_client:
                await self.redis_client.close()
            
            if self.elasticsearch_client:
                await self.elasticsearch_client.close()
            
            if self.milvus_client:
                await self.milvus_client.disconnect()
            
            if self.db_client:
                self.db_client.close()
            
            self._initialized = False
            logger.info("Database integration manager cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    @asynccontextmanager
    async def get_session(self):
        """Get database session context manager."""
        if not self._initialized or not self.db_client:
            raise RuntimeError("Database integration manager not initialized")
        
        async with self.db_client.get_async_session() as session:
            yield session
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        asyncio.create_task(self.cleanup())
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()


# Global instance for application use
_db_manager: Optional[DatabaseIntegrationManager] = None


async def get_database_manager(config: Optional[DatabaseConfig] = None) -> DatabaseIntegrationManager:
    """Get or create the global database manager instance."""
    global _db_manager
    
    if _db_manager is None:
        _db_manager = DatabaseIntegrationManager(config)
        await _db_manager.initialize()
    
    return _db_manager


async def cleanup_database_manager():
    """Cleanup the global database manager instance."""
    global _db_manager
    
    if _db_manager:
        await _db_manager.cleanup()
        _db_manager = None
