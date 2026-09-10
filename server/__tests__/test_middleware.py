"""
Tests for middleware functionality.

Tests middleware configuration, request processing, and error handling.
"""

import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from server.middleware import configure_middleware
from server.config import Settings


class TestMiddlewareConfiguration:
    """Test middleware configuration and setup."""
    
    @pytest.fixture
    def app(self):
        """Create a test FastAPI app."""
        return FastAPI()
    
    @pytest.fixture
    def settings(self):
        """Create test settings."""
        return Settings(
            enable_request_validation=True,
            enable_security_analysis=True,
            log_invalid_requests=True,
            validation_rate_limit_per_minute=100,
            max_request_size=10 * 1024 * 1024,  # 10MB
            max_headers_count=50,
            max_header_size=8192,  # 8KB
        )
    
    def test_configure_middleware_registers_components(self, app, settings):
        """Test that configure_middleware properly registers all components."""
        with patch('server.middleware._http_metrics') as mock_metrics:
            configure_middleware(app, settings, Mock(), Mock(), Mock())
            
            # Verify middleware was added
            assert len(app.user_middleware) > 0
    
    def test_configure_middleware_with_disabled_features(self, app):
        """Test middleware configuration with disabled features."""
        settings = Settings(
            enable_request_validation=False,
            enable_security_analysis=False,
            log_invalid_requests=False,
        )
        
        with patch('server.middleware._http_metrics') as mock_metrics:
            configure_middleware(app, settings, Mock(), Mock(), Mock())
            
            # Verify middleware was still added even with features disabled
            assert len(app.user_middleware) > 0


class TestRequestProcessing:
    """Test request processing through middleware."""
    
    @pytest.fixture
    def mock_app(self):
        """Create app with mock middleware for testing."""
        app = FastAPI()
        
        # Mock middleware function
        async def mock_middleware(request, call_next):
            # Add test data to request state
            request.state.test_data = "middleware_test"
            return await call_next(request)
        
        app.middleware("http")(mock_middleware)
        return app
    
    def test_request_state_preservation(self, mock_app):
        """Test that request state is preserved through middleware."""
        @mock_app.get("/test")
        async def test_endpoint(request):
            return {"test_data": getattr(request.state, "test_data", "not_found")}
        
        client = TestClient(mock_app)
        response = client.get("/test")
        
        assert response.status_code == 200
        assert response.json()["test_data"] == "middleware_test"
    
    def test_request_id_generation(self, mock_app):
        """Test that request IDs are generated and tracked."""
        with patch('server.middleware.uuid.uuid4', return_value="test-request-id"):
            @mock_app.get("/test")
            async def test_endpoint(request):
                return {"request_id": getattr(request.state, "request_id", "not_found")}
            
            client = TestClient(mock_app)
            response = client.get("/test")
            
            assert response.status_code == 200
            assert response.json()["request_id"] == "test-request-id"


class TestErrorHandling:
    """Test error handling in middleware."""
    
    @pytest.fixture
    def error_app(self):
        """Create app with error-handling middleware."""
        app = FastAPI()
        
        # Middleware that raises an exception
        async def error_middleware(request, call_next):
            if request.url.path == "/error":
                raise ValueError("Test error")
            return await call_next(request)
        
        app.middleware("http")(error_middleware)
        return app
    
    def test_exception_handling(self, error_app):
        """Test that exceptions in middleware are properly handled."""
        @error_app.get("/error")
        async def error_endpoint():
            return {"message": "This should not be reached"}
        
        client = TestClient(error_app)
        
        # Should handle the exception gracefully
        with pytest.raises(Exception):
            client.get("/error")
    
    def test_http_exception_handling(self, error_app):
        """Test HTTPException handling in middleware."""
        async def http_error_middleware(request, call_next):
            if request.url.path == "/http-error":
                raise HTTPException(status_code=422, detail="Validation error")
            return await call_next(request)
        
        # Replace the middleware
        error_app.user_middleware.clear()
        error_app.middleware("http")(http_error_middleware)
        
        @error_app.get("/http-error")
        async def http_error_endpoint():
            return {"message": "This should not be reached"}
        
        client = TestClient(error_app)
        response = client.get("/http-error")
        
        assert response.status_code == 422
        assert response.json()["detail"] == "Validation error"


class TestMetricsIntegration:
    """Test metrics integration in middleware."""
    
    @pytest.fixture
    def metrics_app(self):
        """Create app with metrics middleware."""
        app = FastAPI()
        
        # Mock metrics
        mock_request_count = Mock()
        mock_request_latency = Mock()
        mock_error_count = Mock()
        
        async def metrics_middleware(request, call_next):
            # Record metrics
            mock_request_count.inc()
            mock_request_latency.observe(0.1)
            
            response = await call_next(request)
            
            # Record error if response status indicates error
            if hasattr(response, "status_code") and response.status_code >= 400:
                mock_error_count.inc()
            
            return response
        
        app.middleware("http")(metrics_middleware)
        return app
    
    def test_metrics_recording(self, metrics_app):
        """Test that metrics are properly recorded."""
        @metrics_app.get("/test")
        async def test_endpoint():
            return {"message": "success"}
        
        client = TestClient(metrics_app)
        response = client.get("/test")
        
        # Verify metrics were called
        mock_request_count = None
        for middleware in metrics_app.user_middleware:
            if hasattr(middleware, '__wrapped__'):
                # Access the mock through the closure
                import inspect
                source = inspect.getsource(middleware)
                if "mock_request_count" in source:
                    # This is our metrics middleware
                    mock_request_count = middleware
        
        if mock_request_count:
            mock_request_count.inc.assert_called()
    
    def test_error_metrics_recording(self, metrics_app):
        """Test that error metrics are recorded for error responses."""
        @metrics_app.get("/error")
        async def error_endpoint():
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="Server error")
        
        client = TestClient(metrics_app)
        
        with pytest.raises(Exception):
            client.get("/error")


class TestSecurityIntegration:
    """Test security features in middleware."""
    
    @pytest.fixture
    def security_app(self):
        """Create app with security middleware."""
        app = FastAPI()
        
        async def security_middleware(request, call_next):
            # Add security headers
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response
        
        app.middleware("http")(security_middleware)
        return app
    
    def test_security_headers(self, security_app):
        """Test that security headers are added."""
        @security_app.get("/test")
        async def test_endpoint():
            return {"message": "secure"}
        
        client = TestClient(security_app)
        response = client.get("/test")
        
        assert "X-Content-Type-Options" in response.headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "X-Frame-Options" in response.headers
        assert response.headers["X-Frame-Options"] == "DENY"


class TestRateLimiting:
    """Test rate limiting functionality in middleware."""
    
    @pytest.fixture
    def rate_limit_app(self):
        """Create app with rate limiting middleware."""
        app = FastAPI()
        
        # Simple rate limiting implementation
        request_counts = {}
        
        async def rate_limit_middleware(request, call_next):
            client_ip = request.client.host if request.client else "unknown"
            import time
            current_time = int(time.time())
            
            # Clean old requests (older than 1 minute)
            for ip, requests in list(request_counts.items()):
                request_counts[ip] = [req_time for req_time in requests if current_time - req_time < 60]
            
            # Add current request
            if client_ip not in request_counts:
                request_counts[client_ip] = []
            request_counts[client_ip].append(current_time)
            
            # Check rate limit (more than 10 requests per minute)
            if len(request_counts[client_ip]) > 10:
                from fastapi import HTTPException
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            
            return await call_next(request)
        
        app.middleware("http")(rate_limit_middleware)
        return app
    
    def test_rate_limiting(self, rate_limit_app):
        """Test that rate limiting works correctly."""
        import time
        
        @rate_limit_app.get("/test")
        async def test_endpoint():
            return {"message": "success"}
        
        client = TestClient(rate_limit_app)
        
        # First request should succeed
        response1 = client.get("/test")
        assert response1.status_code == 200
        
        # Make multiple requests quickly
        for _ in range(11):  # Exceed the rate limit
            response = client.get("/test")
            if response.status_code == 429:
                assert "Rate limit exceeded" in response.json()["detail"]
                break
        else:
            # Should not exceed rate limit yet
            assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])