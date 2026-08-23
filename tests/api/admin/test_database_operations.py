import pytest
from fastapi.testclient import TestClient
from server.app import app
import uuid

# Mock the service
class MockDatabaseOperationsService:
    async def get_overview(self, correlation_id: str):
        from ai_karen_engine.services.database.health_contracts import DatabaseOperationsOverview
        return DatabaseOperationsOverview(
            status="healthy",
            generated_at="2026-05-02T12:00:00Z",
            correlation_id=correlation_id,
            request_id=str(uuid.uuid4()),
            storage_tiers=[],
            memory_writeback={"status": "healthy", "enabled": True},
            projections=[],
            migrations={"status": "healthy", "pending_count": 0, "failed_count": 0},
            warnings=[],
            actions_available=[]
        )

@pytest.fixture
def client():
    return TestClient(app)

def test_get_database_overview_unauthorized(client):
    response = client.get("/api/admin/database/overview")
    # Assuming no auth header results in 401 or 403 depending on implementation
    assert response.status_code in [401, 403]

def test_get_database_overview_admin(client, mocker):
    # Need to mock get_current_user and the service
    mocker.patch("ai_karen_engine.api_routes.admin.database.get_current_user", 
                 return_value={"id": "admin", "roles": ["admin"]})
    mocker.patch("ai_karen_engine.api_routes.admin.database.get_database_operations_service", 
                 return_value=MockDatabaseOperationsService())
    
    response = client.get("/api/admin/database/overview", headers={"X-Correlation-ID": "test-corr"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["correlation_id"] == "test-corr"
