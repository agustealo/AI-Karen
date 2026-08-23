"""
Tests for health endpoints functionality.

Tests health check endpoints, status reporting, and system health monitoring.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthEndpoints:
    """Test health endpoints functionality."""
    
    def test_ping_endpoint_success(self):
        """Test successful ping endpoint."""
        # Import the ping function
        from health_endpoints import register_health_endpoints
        
        # Create a mock FastAPI app
        mock_app = Mock()
        
        # Register endpoints
        register_health_endpoints(mock_app)
        
        # Verify that endpoints were registered
        assert hasattr(mock_app, 'add_route')
        
        # Check that the expected number of routes were added
        # We can't easily test the exact routes without more complex mocking,
        # but we can verify the function was called
        assert mock_app.add_route.called
    
    def test_database_health_function_exists(self):
        """Test that database health function exists and has correct signature."""
        # Import the function
        from health_endpoints import _check_database_health
        
        # Verify function exists
        assert callable(_check_database_health)
        
        # Verify function is async
        import inspect
        sig = inspect.signature(_check_database_health)
        assert inspect.iscoroutinefunction(_check_database_health)
    
    def test_redis_health_function_exists(self):
        """Test that Redis health function exists and has correct signature."""
        # Import the function
        from health_endpoints import _check_redis_health
        
        # Verify function exists
        assert callable(_check_redis_health)
        
        # Verify function is async
        import inspect
        sig = inspect.signature(_check_redis_health)
        assert inspect.iscoroutinefunction(_check_redis_health)
    
    def test_system_resources_function_exists(self):
        """Test that system resources function exists and has correct signature."""
        # Import the function
        from health_endpoints import _check_system_resources
        
        # Verify function exists
        assert callable(_check_system_resources)
        
        # Verify function is async
        import inspect
        sig = inspect.signature(_check_system_resources)
        assert inspect.iscoroutinefunction(_check_system_resources)
    
    def test_ai_providers_health_function_exists(self):
        """Test that AI providers health function exists and has correct signature."""
        # Import the function
        from health_endpoints import _check_ai_providers_health
        
        # Verify function exists
        assert callable(_check_ai_providers_health)
        
        # Verify function is async
        import inspect
        sig = inspect.signature(_check_ai_providers_health)
        assert inspect.iscoroutinefunction(_check_ai_providers_health)
    
    def test_extension_system_health_function_exists(self):
        """Test that extension system health function exists and has correct signature."""
        # Import the function
        from health_endpoints import _check_extension_system_health
        
        # Verify function exists
        assert callable(_check_extension_system_health)
        
        # Verify function is async
        import inspect
        sig = inspect.signature(_check_extension_system_health)
        assert inspect.iscoroutinefunction(_check_extension_system_health)
    
    def test_database_health_function_with_mock(self):
        """Test database health function with mocked dependencies."""
        # Import the function
        from health_endpoints import _check_database_health
        
        # Mock database manager
        with patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.test_connection.return_value = True
            mock_manager.is_degraded.return_value = False
            mock_get_manager.return_value = mock_manager
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_database_health())
            
            # Verify response structure
            assert "status" in result
            assert result["status"] == "healthy"
            assert result["connected"] is True
            assert result["degraded"] is False
    
    def test_redis_health_function_with_mock(self):
        """Test Redis health function with mocked dependencies."""
        # Import the function
        from health_endpoints import _check_redis_health
        
        # Mock Redis manager
        with patch('ai_karen_engine.services.redis_connection_manager.get_redis_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.test_connection.return_value = True
            mock_manager.is_degraded.return_value = False
            mock_get_manager.return_value = mock_manager
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_redis_health())
            
            # Verify response structure
            assert "status" in result
            assert result["status"] == "healthy"
            assert result["connected"] is True
            assert result["degraded"] is False
    
    def test_system_resources_function_with_mock(self):
        """Test system resources function with mocked dependencies."""
        # Import the function
        from health_endpoints import _check_system_resources
        
        # Mock psutil
        with patch('health_endpoints.psutil') as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.5
            mock_psutil.virtual_memory.return_value = Mock(percent=60.2, available=8 * 1024**3)
            mock_psutil.disk_usage.return_value = Mock(percent=45.8, free=100 * 1024**3)
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_system_resources())
            
            # Verify response structure
            assert "status" in result
            assert result["status"] == "healthy"
            assert result["cpu_percent"] == 25.5
            assert result["memory_percent"] == 60.2
            assert result["disk_percent"] == 45.8
    
    def test_ai_providers_function_with_mock(self):
        """Test AI providers health function with mocked dependencies."""
        # Import the function
        from health_endpoints import _check_ai_providers_health
        
        # Mock provider registry
        with patch('ai_karen_engine.services.provider_registry.get_provider_registry_service') as mock_get_service:
            mock_service = Mock()
            mock_service.get_system_status.return_value = {
                "total_providers": 5,
                "available_providers": 4,
                "failed_providers": [],
                "provider_details": {}
            }
            mock_get_service.return_value = mock_service
            
            # Mock Path for models directory
            with patch('health_endpoints.Path') as mock_path:
                mock_path.return_value.exists.return_value = False
                mock_path.return_value.glob.return_value = []
                
                # Call the function
                import asyncio
                result = asyncio.run(_check_ai_providers_health())
                
                # Verify response structure
                assert "status" in result
                assert result["status"] == "healthy"
                assert result["total_providers"] == 5
                assert result["available_providers"] == 4
                assert result["local_models"] == 0
    
    def test_extension_system_health_function_with_mock(self):
        """Test extension system health function with mocked dependencies."""
        # Import the function
        from health_endpoints import _check_extension_system_health
        
        # Mock extension health monitor
        with patch('health_endpoints.get_extension_health_monitor') as mock_get_monitor:
            mock_monitor = Mock()
            mock_monitor.get_extension_health_for_api.return_value = {
                "status": "healthy",
                "extensions": {
                    "total": 8,
                    "healthy": 6,
                    "degraded": 2,
                    "unhealthy": 0,
                    "details": {}
                },
                "uptime_seconds": 3600,
                "supporting_services": ["database", "redis"]
            }
            mock_get_monitor.return_value = mock_monitor
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_extension_system_health())
            
            # Verify response structure
            assert "status" in result
            assert result["status"] == "healthy"
            assert result["total_extensions"] == 8
            assert result["healthy_extensions"] == 6
            assert result["degraded_extensions"] == 2
            assert result["unhealthy_extensions"] == 0
    
    def test_database_health_function_with_exception(self):
        """Test database health function with exception."""
        # Import the function
        from health_endpoints import _check_database_health
        
        # Mock database manager with exception
        with patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager') as mock_get_manager:
            mock_get_manager.side_effect = Exception("Connection failed")
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_database_health())
            
            # Verify error handling
            assert "status" in result
            assert result["status"] == "unhealthy"
            assert "error" in result
            assert result["connected"] is False
    
    def test_system_resources_function_with_exception(self):
        """Test system resources function with exception."""
        # Import the function
        from health_endpoints import _check_system_resources
        
        # Mock psutil with exception
        with patch('health_endpoints.psutil') as mock_psutil:
            mock_psutil.cpu_percent.side_effect = Exception("Failed to get CPU usage")
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_system_resources())
            
            # Verify error handling
            assert "status" in result
            assert result["status"] == "unknown"
            assert "error" in result


class TestHealthEndpointIntegration:
    """Test health endpoint integration with other components."""
    
    def test_health_endpoint_registration(self):
        """Test health endpoint registration with FastAPI app."""
        # Import the registration function
        from health_endpoints import register_health_endpoints
        
        # Create a mock FastAPI app
        mock_app = Mock()
        
        # Register endpoints
        register_health_endpoints(mock_app)
        
        # Verify that endpoints were registered
        assert hasattr(mock_app, 'add_route')
        
        # Check that the expected number of routes were added
        # We can't easily test the exact routes without more complex mocking,
        # but we can verify the function was called
        assert mock_app.add_route.called
    
    def test_health_endpoint_error_handling(self):
        """Test health endpoint error handling."""
        # Import the database health function
        from health_endpoints import _check_database_health
        
        # Mock database manager with exception
        with patch('ai_karen_engine.services.database.database_connection_manager.get_database_manager') as mock_get_manager:
            mock_get_manager.side_effect = Exception("Connection failed")
            
            # Call the function
            import asyncio
            result = asyncio.run(_check_database_health())
            
            # Verify error handling
            assert "status" in result
            assert result["status"] == "unhealthy"
            assert "error" in result
            assert result["connected"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])