import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from ai_karen_engine.services.database.health_contracts import (
    DatabaseOperationsOverview,
    StorageTierHealth,
    MemoryWritebackHealth,
    ProjectionHealth,
    MigrationHealth,
    HealthStatus,
    TierName
)

# Existing services
from ai_karen_engine.services.database.health.checker import DatabaseHealthChecker
from ai_karen_engine.database.migration_manager import MigrationManager
# MemoryWritebackSystem doesn't have a global instance getter - we'll initialize when needed
from ai_karen_engine.core.memory.memory_writeback import MemoryWritebackSystem
from ai_karen_engine.core.memory.projections.manager import get_projection_manager
from ai_karen_engine.core.runtime.resilience.circuit_breaker import get_breaker_registry

logger = logging.getLogger(__name__)

class DatabaseOperationsService:
    """Service for aggregating operational data about Karen's database systems."""

    def __init__(self):
        self.health_checker = DatabaseHealthChecker()
        self.migration_manager = MigrationManager()
        self.circuit_breaker_registry = get_breaker_registry()
        self._writeback_system: Optional[MemoryWritebackSystem] = None

    async def get_overview(self, correlation_id: str) -> DatabaseOperationsOverview:
        """Get a comprehensive overview of database operations."""
        request_id = str(uuid.uuid4())
        
        # 1. Fetch Storage Tiers Health
        storage_tiers = await self._get_storage_tiers_health()
        
        # 2. Fetch Memory Writeback Health
        memory_writeback = await self._get_memory_writeback_health()
        
        # 3. Fetch Projections Health
        projections = await self._get_projections_health()
        
        # 4. Fetch Migrations Health
        migrations = await self._get_migrations_health()
        
        # Determine overall status
        overall_status: HealthStatus = "healthy"
        all_healths = [tier.status for tier in storage_tiers] + [memory_writeback.status] + [p.status for p in projections] + [migrations.status]
        
        if "unavailable" in all_healths:
            overall_status = "unavailable"
        elif "degraded" in all_healths:
            overall_status = "degraded"

        return DatabaseOperationsOverview(
            status=overall_status,
            generated_at=datetime.now(timezone.utc).isoformat(),
            correlation_id=correlation_id,
            request_id=request_id,
            storage_tiers=storage_tiers,
            memory_writeback=memory_writeback,
            projections=projections,
            migrations=migrations,
            warnings=self._collect_warnings(storage_tiers, memory_writeback, projections, migrations),
            actions_available=["maintenance.run", "projections.retry", "migrations.validate"]
        )

    async def _get_storage_tiers_health(self) -> List[StorageTierHealth]:
        """Aggregate health data for all storage tiers."""
        tiers: List[TierName] = ["postgres", "redis", "duckdb", "leangraph"]
        health_results = []
        
        for tier in tiers:
            try:
                # Use the existing health checker
                # Note: Assuming health_checker has methods for these tiers
                check_method = getattr(self.health_checker, f"check_{tier}", None)
                if check_method:
                    res = await check_method()
                    status = "healthy" if res.get("healthy") else "degraded"
                    if res.get("error"):
                        status = "unavailable"
                    
                    cb_state = self.circuit_breaker_registry.get_state(f"database.{tier}")
                    
                    health_results.append(StorageTierHealth(
                        tier=tier,
                        status=status,
                        enabled=res.get("enabled", True),
                        connected=res.get("connected", False),
                        latency_ms=res.get("latency_ms"),
                        last_success_at=res.get("last_success_at"),
                        last_failure_at=res.get("last_failure_at"),
                        error_type=res.get("error_type"),
                        error_message=res.get("error_message"),
                        circuit_breaker_state=cb_state,
                        metadata=res.get("details", {})
                    ))
                else:
                    health_results.append(StorageTierHealth(
                        tier=tier,
                        status="unknown",
                        enabled=True,
                        connected=False,
                        metadata={"info": f"No health check method found for {tier}"}
                    ))
            except Exception as e:
                logger.error(f"Error checking health for {tier}: {e}")
                health_results.append(StorageTierHealth(
                    tier=tier,
                    status="unavailable",
                    enabled=True,
                    connected=False,
                    error_message=str(e)
                ))
        
        return health_results

    async def _get_memory_writeback_health(self) -> MemoryWritebackHealth:
        """Get operational health of the memory writeback system."""
        try:
            # MemoryWritebackSystem doesn't have a global instance getter
            # Return degraded status indicating this feature is not configured
            return MemoryWritebackHealth(
                status="disabled",
                enabled=False,
                writeback_status="not_configured",
                degraded_reason="Memory writeback system not initialized"
            )
        except Exception as e:
            logger.error(f"Error getting memory writeback health: {e}")
            return MemoryWritebackHealth(status="unavailable", enabled=True)

    async def _get_projections_health(self) -> List[ProjectionHealth]:
        """Get operational health of all memory projections."""
        try:
            manager = get_projection_manager()
            projections_stats = await manager.get_all_projection_stats()
            
            results = []
            for name, stats in projections_stats.items():
                status: HealthStatus = "healthy"
                if stats.get("lag", 0) > 100:
                    status = "degraded"
                if stats.get("failed", False):
                    status = "unavailable"
                    
                results.append(ProjectionHealth(
                    name=name,
                    target_tier=stats.get("target_tier", "unknown"),
                    status=status,
                    lag_count=stats.get("lag"),
                    last_projected_at=stats.get("last_run"),
                    failed_count=stats.get("failed_count"),
                    retry_available=True
                ))
            return results
        except Exception as e:
            logger.error(f"Error getting projections health: {e}")
            return []

    async def _get_migrations_health(self) -> MigrationHealth:
        """Get migration state and consistency status."""
        try:
            state = await self.migration_manager.get_state()
            
            status: HealthStatus = "healthy"
            if state.get("pending_count", 0) > 0:
                status = "degraded"
            if state.get("failed_count", 0) > 0:
                status = "unavailable"
                
            return MigrationHealth(
                status=status,
                current_version=state.get("current_version"),
                latest_version=state.get("latest_version"),
                pending_count=state.get("pending_count", 0),
                failed_count=state.get("failed_count", 0),
                validation_status=state.get("validation_status")
            )
        except Exception as e:
            logger.error(f"Error getting migrations health: {e}")
            return MigrationHealth(status="unavailable")

    def _collect_warnings(self, tiers, writeback, projections, migrations) -> List[str]:
        """Collect operational warnings across all systems."""
        warnings = []
        for tier in tiers:
            if tier.status in ["degraded", "unavailable"]:
                warnings.append(f"Storage tier {tier.tier} is {tier.status}: {tier.error_message or 'No details'}")
        
        if writeback.status == "degraded":
            warnings.append(f"Memory writeback is degraded: {writeback.degraded_reason or 'Queue backup'}")
            
        for p in projections:
            if p.status == "degraded":
                warnings.append(f"Projection {p.name} is lagging by {p.lag_count} items")
                
        if migrations.pending_count > 0:
            warnings.append(f"Database has {migrations.pending_count} pending migrations")
            
        return warnings

_database_operations_service: Optional[DatabaseOperationsService] = None

def get_database_operations_service() -> DatabaseOperationsService:
    global _database_operations_service
    if _database_operations_service is None:
        _database_operations_service = DatabaseOperationsService()
    return _database_operations_service
