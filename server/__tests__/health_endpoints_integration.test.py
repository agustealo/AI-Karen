"""
Integration tests for health endpoints

Tests the comprehensive health check endpoints to ensure they provide
accurate health information for all services.

Requirements: 5.1, 5.4
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Import the health endpoints registration function
from server.health_endpoints import register_health_endpoints


@pytest.fixture
def app():
    """Create a test FastAPI app with health endpoints."""
    app = FastAPI()
    register_health_endpoints(app)
    return app


@pytest.fixture
def client(app):
    """Create a test client."""
    return TestClient(app)


class TestBasicHealthEndpoints:
    """Test basic health endpoints."""

    def test_ping_endpoint(self, client):
        """Test the ping endpoint."""
        response = client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_api_ping_endpoint(self, client):
        """Test the API ping endpoint."""
        response = client.get("/api/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_basic_health_endpoint(self, client):
        """Test the basic health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_api_status_endpoint(self, client):
        """Test the API status endpoint."""
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data
        assert "uptime_seconds" in data
        assert "system_info" in data


class TestComprehensiveHealthEndpoint:
    """Test comprehensive health endpoint."""

    @patch('server.health_endpoints._check_database_health')
    @patch('server.health_endpoints._check_redis_health')
    @patch('server.health_endpoints._check_ai_providers_health')
    @patch('server.health_endpoints._check_system_resources')
    async def test_comprehensive_health_all_healthy(
        self, 
        mock_system, 
        mock_ai, 
        mock_redis, 
        mock_db,
        client
    ):
        """Test comprehensive health when all services are healthy."""
        # Mock all services as healthy
        mock_db.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 50,
        }
        mock_redis.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 25,
        }
        mock_ai.return_value = {
            "status": "healthy",
            "total_providers": 3,
            "available_providers": 3,
        }
        mock_system.return_value = {
            "status": "healthy",
            "cpu_percent": 45.0,
            "memory_percent": 60.0,
        }

        response = client.get("/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "response_time_ms" in data
        assert "services" in data
        assert "summary" in data

        # Check services
        services = data["services"]
        assert services["database"]["status"] == "healthy"
        assert services["redis"]["status"] == "healthy"
        assert services["ai_providers"]["status"] == "healthy"
        assert services["system_resources"]["status"] == "healthy"

        # Check summary
        summary = data["summary"]
        assert summary["healthy_services"] == 4
        assert summary["degraded_services"] == 0
        assert summary["unhealthy_services"] == 0
        assert summary["total_services"] == 4

    @patch('server.health_endpoints._check_database_health')
    @patch('server.health_endpoints._check_redis_health')
    @patch('server.health_endpoints._check_ai_providers_health')
    @patch('server.health_endpoints._check_system_resources')
    async def test_comprehensive_health_degraded(
        self, 
        mock_system, 
        mock_ai, 
        mock_redis, 
        mock_db,
        client
    ):
        """Test comprehensive health when some services are degraded."""
        # Mock some services as degraded
        mock_db.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 50,
        }
        mock_redis.return_value = {
            "status": "degraded",
            "connected": True,
            "degraded": True,
            "response_time_ms": 200,
        }
        mock_ai.return_value = {
            "status": "degraded",
            "total_providers": 3,
            "available_providers": 1,
        }
        mock_system.return_value = {
            "status": "healthy",
            "cpu_percent": 45.0,
            "memory_percent": 60.0,
        }

        response = client.get("/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "degraded"  # Overall status should be degraded

        # Check summary
        summary = data["summary"]
        assert summary["healthy_services"] == 2
        assert summary["degraded_services"] == 2
        assert summary["unhealthy_services"] == 0

    @patch('server.health_endpoints._check_database_health')
    @patch('server.health_endpoints._check_redis_health')
    @patch('server.health_endpoints._check_ai_providers_health')
    @patch('server.health_endpoints._check_system_resources')
    async def test_comprehensive_health_unhealthy(
        self, 
        mock_system, 
        mock_ai, 
        mock_redis, 
        mock_db,
        client
    ):
        """Test comprehensive health when some services are unhealthy."""
        # Mock some services as unhealthy
        mock_db.return_value = {
            "status": "unhealthy",
            "connected": False,
            "error": "Connection failed",
        }
        mock_redis.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 25,
        }
        mock_ai.return_value = {
            "status": "healthy",
            "total_providers": 3,
            "available_providers": 3,
        }
        mock_system.return_value = {
            "status": "healthy",
            "cpu_percent": 45.0,
            "memory_percent": 60.0,
        }

        response = client.get("/api/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "unhealthy"  # Overall status should be unhealthy

        # Check summary
        summary = data["summary"]
        assert summary["healthy_services"] == 3
        assert summary["degraded_services"] == 0
        assert summary["unhealthy_services"] == 1


class TestSpecificHealthEndpoints:
    """Test service-specific health endpoints."""

    @patch('server.health_endpoints._check_database_health')
    async def test_database_health_endpoint_healthy(self, mock_db, client):
        """Test database health endpoint when healthy."""
        mock_db.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 50,
            "pool_size": 10,
        }

        response = client.get("/api/health/database")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["connected"] is True
        assert data["response_time_ms"] == 50

    @patch('server.health_endpoints._check_database_health')
    async def test_database_health_endpoint_unhealthy(self, mock_db, client):
        """Test database health endpoint when unhealthy."""
        mock_db.return_value = {
            "status": "unhealthy",
            "connected": False,
            "error": "Connection failed",
        }

        response = client.get("/api/health/database")
        assert response.status_code == 503  # Service unavailable
        
        data = response.json()
        assert "detail" in data
        assert data["detail"]["status"] == "unhealthy"

    @patch('server.health_endpoints._check_redis_health')
    async def test_redis_health_endpoint(self, mock_redis, client):
        """Test Redis health endpoint."""
        mock_redis.return_value = {
            "status": "healthy",
            "connected": True,
            "response_time_ms": 25,
        }

        response = client.get("/api/health/redis")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["connected"] is True

    @patch('server.health_endpoints._check_ai_providers_health')
    async def test_ai_providers_health_endpoint(self, mock_ai, client):
        """Test AI providers health endpoint."""
        mock_ai.return_value = {
            "status": "healthy",
            "total_providers": 3,
            "available_providers": 3,
            "local_models": 2,
        }

        response = client.get("/api/health/ai-providers")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["total_providers"] == 3
        assert data["available_providers"] == 3

    @patch('server.health_endpoints._check_system_resources')
    async def test_system_health_endpoint(self, mock_system, client):
        """Test system resources health endpoint."""
        mock_system.return_value = {
            "status": "healthy",
            "cpu_percent": 45.0,
            "memory_percent": 60.0,
            "disk_percent": 70.0,
        }

        response = client.get("/api/health/system")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["cpu_percent"] == 45.0
        assert data["memory_percent"] == 60.0


class TestHealthCheckFunctions:
    """Test individual health check functions."""

    @patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager')
    async def test_check_database_health_success(self, mock_get_manager):
        """Test database health check when successful."""
        from server.health_endpoints import _check_database_health
        
        # Mock database manager
        mock_manager = Mock()
        mock_manager.test_connection = AsyncMock(return_value=True)
        mock_manager.is_degraded.return_value = False
        mock_manager.pool_size = 10
        mock_manager.active_connections = 3
        mock_get_manager.return_value = mock_manager

        result = await _check_database_health()
        
        assert result["status"] == "healthy"
        assert result["connected"] is True
        assert result["degraded"] is False
        assert "response_time_ms" in result
        assert result["pool_size"] == 10

    @patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager')
    async def test_check_database_health_failure(self, mock_get_manager):
        """Test database health check when failed."""
        from server.health_endpoints import _check_database_health
        
        # Mock database manager to raise exception
        mock_get_manager.side_effect = Exception("Database connection failed")

        result = await _check_database_health()
        
        assert result["status"] == "unhealthy"
        assert result["connected"] is False
        assert "error" in result
        assert "Database connection failed" in result["error"]

    @patch('ai_karen_engine.services.redis_connection_manager.get_redis_manager')
    async def test_check_redis_health_success(self, mock_get_manager):
        """Test Redis health check when successful."""
        from server.health_endpoints import _check_redis_health
        
        # Mock Redis manager
        mock_manager = Mock()
        mock_manager.test_connection = AsyncMock(return_value=True)
        mock_manager.is_degraded.return_value = False
        mock_get_manager.return_value = mock_manager

        result = await _check_redis_health()
        
        assert result["status"] == "healthy"
        assert result["connected"] is True
        assert result["degraded"] is False
        assert "response_time_ms" in result

    @patch('ai_karen_engine.services.provider_registry.get_provider_registry_service')
    async def test_check_ai_providers_health_success(self, mock_get_service):
        """Test AI providers health check when successful."""
        from server.health_endpoints import _check_ai_providers_health
        
        # Mock provider service
        mock_service = Mock()
        mock_service.get_system_status.return_value = {
            "total_providers": 3,
            "available_providers": 3,
            "failed_providers": [],
            "provider_details": {
                "openai": {"is_available": True},
                "anthropic": {"is_available": True},
                "local": {"is_available": True},
            }
        }
        mock_get_service.return_value = mock_service

        result = await _check_ai_providers_health()
        
        assert result["status"] == "healthy"
        assert result["total_providers"] == 3
        assert result["available_providers"] == 3
        assert result["failed_providers"] == []

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    async def test_check_system_resources_success(self, mock_disk, mock_memory, mock_cpu):
        """Test system resources health check when successful."""
        from server.health_endpoints import _check_system_resources
        
        # Mock system metrics
        mock_cpu.return_value = 45.0
        
        mock_memory_obj = Mock()
        mock_memory_obj.percent = 60.0
        mock_memory_obj.available = 8 * 1024**3  # 8GB
        mock_memory.return_value = mock_memory_obj
        
        mock_disk_obj = Mock()
        mock_disk_obj.percent = 70.0
        mock_disk_obj.free = 100 * 1024**3  # 100GB
        mock_disk.return_value = mock_disk_obj

        result = await _check_system_resources()
        
        assert result["status"] == "healthy"
        assert result["cpu_percent"] == 45.0
        assert result["memory_percent"] == 60.0
        assert result["disk_percent"] == 70.0
        assert result["memory_available_gb"] == 8.0
        assert result["disk_free_gb"] == 100.0

    @patch('psutil.cpu_percent')
    @patch('psutil.virtual_memory')
    @patch('psutil.disk_usage')
    async def test_check_system_resources_degraded(self, mock_disk, mock_memory, mock_cpu):
        """Test system resources health check when degraded."""
        from server.health_endpoints import _check_system_resources
        
        # Mock high resource usage
        mock_cpu.return_value = 92.0  # High CPU
        
        mock_memory_obj = Mock()
        mock_memory_obj.percent = 85.0  # High memory
        mock_memory_obj.available = 1 * 1024**3  # 1GB
        mock_memory.return_value = mock_memory_obj
        
        mock_disk_obj = Mock()
        mock_disk_obj.percent = 95.0  # High disk usage
        mock_disk_obj.free = 5 * 1024**3  # 5GB
        mock_disk.return_value = mock_disk_obj

        result = await _check_system_resources()
        
        assert result["status"] == "unhealthy"  # Should be unhealthy due to high usage
        assert result["cpu_percent"] == 92.0
        assert result["memory_percent"] == 85.0
        assert result["disk_percent"] == 95.0


if __name__ == "__main__":
    pytest.main([__file__])