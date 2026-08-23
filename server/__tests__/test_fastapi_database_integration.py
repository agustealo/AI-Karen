"""
Integration tests for FastAPI Backend Database Configuration.
Tests the integration of database configuration with FastAPI application.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
from datetime import datetime, timezone

# Import FastAPI app and related modules
from server.app import create_app
from server.config import Settings


class TestFastAPIDatabaseIntegration:
    """Test FastAPI application with enhanced database configuration"""
    
    @pytest.fixture
    def settings(self):
        """Create test settings"""
        return Settings(
            database_url="postgresql://test:test@localhost:5432/test",
            db_connection_timeout=45,
            db_pool_size=10,
            db_max_overflow=20,
            enable_graceful_shutdown=True,
            environment="test"
        )
    
    @pytest.fixture
    def mock_database_manager(self):
        """Create mock database manager"""
        mock_manager = Mock()
        mock_manager.is_degraded.return_value = False
        mock_manager._health_check = AsyncMock(return_value={
            "healthy": True,
            "response_time_ms": 50.0,
            "pool_info": {
                "sync_pool": {"size": 10, "checked_out": 2},
                "async_pool": {"size": 10, "checked_out": 1}
            },
            "connection_failures": 0
        })
        mock_manager.async_health_check = AsyncMock(return_value=True)
        mock_manager.close = AsyncMock()
        return mock_manager
    
    @pytest.fixture
    def mock_redis_manager(self):
        """Create mock Redis manager"""
        mock_manager = Mock()
        mock_manager.is_degraded.return_value = False
        return mock_manager
    
    def test_app_creation_with_database_config(self, settings):
        """Test FastAPI app creation with database configuration"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            
            assert app is not None
            assert app.title == "Kari AI Assistant API"
            mock_get_config.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_database_health_endpoint(self, settings, mock_database_manager):
        """Test database health endpoint"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.get_database_health = AsyncMock(return_value={
                "healthy": True,
                "response_time_ms": 45.0,
                "configuration": {
                    "pool_size": 10,
                    "max_overflow": 20,
                    "connection_timeout": 45
                },
                "pool_info": {"sync_pool": {"size": 10}}
            })
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            client = TestClient(app)
            
            response = client.get("/api/health/database")
            
            assert response.status_code == 200
            data = response.json()
            assert "timestamp" in data
            assert "database" in data
            assert data["database"]["healthy"] is True
            assert data["database"]["configuration"]["pool_size"] == 10
    
    @pytest.mark.asyncio
    async def test_database_connection_test_endpoint(self, settings):
        """Test database connection test endpoint"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.test_database_connection = AsyncMock(return_value=True)
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            client = TestClient(app)
            
            response = client.get("/api/health/database/test")
            
            assert response.status_code == 200
            data = response.json()
            assert "timestamp" in data
            assert "connection_test" in data
            assert data["connection_test"]["success"] is True
            assert "response_time_ms" in data["connection_test"]
    
    @pytest.mark.asyncio
    async def test_comprehensive_health_check_with_database(self, settings, mock_database_manager, mock_redis_manager):
        """Test comprehensive health check includes database information"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            with patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager', 
                      return_value=mock_database_manager):
                with patch('ai_karen_engine.services.redis_connection_manager.get_redis_manager',
                          return_value=mock_redis_manager):
                    
                    mock_db_config = Mock()
                    mock_db_config.get_database_health = AsyncMock(return_value={
                        "healthy": True,
                        "pool_info": {"sync_pool": {"size": 10}},
                        "configuration": {"pool_size": 10},
                        "connection_failures": 0
                    })
                    mock_get_config.return_value = mock_db_config
                    
                    app = create_app()
                    client = TestClient(app)
                    
                    response = client.get("/health")
                    
                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] in ["healthy", "degraded"]
                    assert "connections" in data
                    assert "database" in data["connections"]
                    
                    db_info = data["connections"]["database"]
                    assert "status" in db_info
                    assert "pool_info" in db_info
                    assert "configuration" in db_info
    
    def test_database_health_endpoint_error_handling(self, settings):
        """Test database health endpoint error handling"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.get_database_health = AsyncMock(
                side_effect=Exception("Database connection failed")
            )
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            client = TestClient(app)
            
            response = client.get("/api/health/database")
            
            assert response.status_code == 200
            data = response.json()
            assert "database" in data
            assert data["database"]["status"] == "error"
            assert data["database"]["healthy"] is False
            assert "error" in data["database"]
    
    def test_database_connection_test_error_handling(self, settings):
        """Test database connection test endpoint error handling"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.test_database_connection = AsyncMock(
                side_effect=Exception("Connection test failed")
            )
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            client = TestClient(app)
            
            response = client.get("/api/health/database/test")
            
            assert response.status_code == 200
            data = response.json()
            assert "connection_test" in data
            assert data["connection_test"]["success"] is False
            assert "error" in data["connection_test"]


class TestDatabaseStartupIntegration:
    """Test database startup integration with FastAPI"""
    
    @pytest.mark.asyncio
    async def test_database_startup_task_success(self):
        """Test successful database startup task"""
        with patch('server.startup.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.initialize_database = AsyncMock(return_value=True)
            mock_db_config.setup_graceful_shutdown = AsyncMock()
            mock_get_config.return_value = mock_db_config
            
            # Import and test the startup function
            from server.startup import register_startup_tasks
            from fastapi import FastAPI
            
            app = FastAPI()
            register_startup_tasks(app)
            
            # Simulate startup event
            for handler in app.router.on_startup:
                if handler.__name__ == "_init_database_config":
                    await handler()
                    break
            
            mock_db_config.initialize_database.assert_called_once()
            mock_db_config.setup_graceful_shutdown.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_database_startup_task_failure(self):
        """Test database startup task failure handling"""
        with patch('server.startup.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.initialize_database = AsyncMock(return_value=False)
            mock_db_config.setup_graceful_shutdown = AsyncMock()
            mock_get_config.return_value = mock_db_config
            
            from server.startup import register_startup_tasks
            from fastapi import FastAPI
            
            app = FastAPI()
            register_startup_tasks(app)
            
            # Simulate startup event - should not raise exception
            for handler in app.router.on_startup:
                if handler.__name__ == "_init_database_config":
                    await handler()
                    break
            
            mock_db_config.initialize_database.assert_called_once()
            # Should still attempt graceful shutdown setup even if init fails
            mock_db_config.setup_graceful_shutdown.assert_called_once()


class TestDatabaseShutdownIntegration:
    """Test database shutdown integration with FastAPI"""
    
    @pytest.mark.asyncio
    async def test_database_shutdown_task(self):
        """Test database shutdown task"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.cleanup = AsyncMock()
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            
            # Find and execute shutdown handler
            for handler in app.router.on_shutdown:
                if handler.__name__ == "_shutdown_database":
                    await handler()
                    break
            
            mock_db_config.cleanup.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_database_shutdown_task_error_handling(self):
        """Test database shutdown task error handling"""
        with patch('server.database_config.get_database_config') as mock_get_config:
            mock_db_config = Mock()
            mock_db_config.cleanup = AsyncMock(side_effect=Exception("Cleanup failed"))
            mock_get_config.return_value = mock_db_config
            
            app = create_app()
            
            # Should not raise exception during shutdown
            for handler in app.router.on_shutdown:
                if handler.__name__ == "_shutdown_database":
                    await handler()
                    break
            
            mock_db_config.cleanup.assert_called_once()


class TestDatabaseConfigurationValidation:
    """Test database configuration validation"""
    
    def test_database_timeout_configuration(self):
        """Test database timeout configuration meets requirements"""
        settings = Settings()
        
        # Requirement 4.3: Database connection timeout increased to 45 seconds
        assert settings.db_connection_timeout == 45
        assert settings.db_connection_timeout > 15  # Increased from original 15 seconds
        
        # Requirement 4.4: Query timeout configured appropriately
        assert settings.db_query_timeout == 30
        assert settings.db_query_timeout >= 30
    
    def test_connection_pool_configuration(self):
        """Test connection pool configuration for improved reliability"""
        settings = Settings()
        
        # Connection pool settings for reliability
        assert settings.db_pool_size >= 10
        assert settings.db_max_overflow >= 20
        assert settings.db_pool_recycle == 3600  # 1 hour
        assert settings.db_pool_pre_ping is True  # Health checks enabled
        assert settings.db_pool_timeout >= 30
    
    def test_graceful_shutdown_configuration(self):
        """Test graceful shutdown configuration"""
        settings = Settings()
        
        # Graceful shutdown settings
        assert settings.enable_graceful_shutdown is True
        assert settings.shutdown_timeout >= 30
    
    def test_health_monitoring_configuration(self):
        """Test health monitoring configuration"""
        settings = Settings()
        
        # Health monitoring settings
        assert settings.db_health_check_interval >= 30
        assert settings.db_max_connection_failures >= 5
        assert settings.db_connection_retry_delay >= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])