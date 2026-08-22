import pytest
from ai_karen_engine.services.database.operations_service import DatabaseOperationsService
from ai_karen_engine.models.database_operations import DatabaseOperationsOverview

@pytest.mark.asyncio
async def test_get_overview_structure():
    service = DatabaseOperationsService()
    overview = await service.get_overview("test-correlation")
    
    assert isinstance(overview, DatabaseOperationsOverview)
    assert overview.correlation_id == "test-correlation"
    assert len(overview.storage_tiers) > 0
    assert overview.memory_writeback is not None
    assert overview.migrations is not None

@pytest.mark.asyncio
async def test_collect_warnings():
    service = DatabaseOperationsService()
    
    from ai_karen_engine.models.database_operations import StorageTierHealth, MemoryWritebackHealth, ProjectionHealth, MigrationHealth
    
    tiers = [StorageTierHealth(tier="postgres", status="degraded", enabled=True, connected=True, error_message="High latency", metadata={})]
    writeback = MemoryWritebackHealth(status="healthy", enabled=True)
    projections = [ProjectionHealth(name="redis", target_tier="redis", status="degraded", lag_count=150, retry_available=True)]
    migrations = MigrationHealth(status="degraded", pending_count=2, failed_count=0)
    
    warnings = service._collect_warnings(tiers, writeback, projections, migrations)
    
    assert any("postgres" in w for w in warnings)
    assert any("lagging by 150" in w for w in warnings)
    assert any("2 pending migrations" in w for w in warnings)
