"""
Security tests for AI-Karen production chat system.
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi import HTTPException, WebSocket
from fastapi.testclient import TestClient
from jose import jwt, JWTError

from server.chat.middleware import (
    ChatAuthenticationMiddleware,
    get_current_chat_user,
    require_chat_permission,
    check_message_rate_limit
)
from server.chat.security import (
    ContentValidator,
    EncryptionManager,
    SecurityMonitor,
    SecurityLevel,
    ThreatLevel
)
from server.chat.audit_logging import (
    AuditLogger,
    SecurityMonitoringService,
    AuditEventType,
    AuditSeverity,
    ThreatLevel as AuditThreatLevel
)
from server.chat.rate_limiting import (
    RateLimiter,
    AbuseDetector,
    RateLimitConfig,
    AbuseDetectionConfig,
    ChatRateLimitingService,
    RateLimitType
)


class TestJWTAuthentication:
    """Test JWT authentication functionality."""
    
    def test_valid_jwt_token(self):
        """Test verification of valid JWT token."""
        # Create a valid token
        payload = {
            "sub": "test_user",
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "role": "user"
        }
        token = jwt.encode(payload, "test_secret", algorithm="HS256")
        
        # Create middleware instance
        middleware = ChatAuthenticationMiddleware(Mock())
        
        # Verify token using middleware's internal method
        with patch('server.chat.middleware.SECRET_KEY', "test_secret"):
            result = asyncio.run(middleware._validate_jwt_token(token))
            
        assert result is not None
        assert result["sub"] == "test_user"
        assert result["role"] == "user"
    
    def test_invalid_jwt_token(self):
        """Test verification of invalid JWT token."""
        # Create an invalid token
        token = "invalid.token.here"
        
        # Create middleware instance
        middleware = ChatAuthenticationMiddleware(Mock())
        
        # Verify token using middleware's internal method
        with patch('server.chat.middleware.SECRET_KEY', "test_secret"):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(middleware._validate_jwt_token(token))
            
        assert exc_info.value.status_code == 401
        assert "Invalid token" in str(exc_info.value.detail)
    
    def test_expired_jwt_token(self):
        """Test verification of expired JWT token."""
        # Create an expired token
        payload = {
            "sub": "test_user",
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=2),
            "role": "user"
        }
        token = jwt.encode(payload, "test_secret", algorithm="HS256")
        
        # Create middleware instance
        middleware = ChatAuthenticationMiddleware(Mock())
        
        # Verify token using middleware's internal method
        with patch('server.chat.middleware.SECRET_KEY', "test_secret"):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(middleware._validate_jwt_token(token))
            
        assert exc_info.value.status_code == 401
        assert "Token expired" in str(exc_info.value.detail)
    
    @pytest.mark.asyncio
    async def test_get_current_chat_user_success(self):
        """Test successful user extraction from request state."""
        # Mock request with user context in state
        mock_request = Mock()
        mock_request.state.user_context = {
            "user_id": "test_user",
            "role": "user",
            "permissions": ["chat:read", "chat:write"]
        }
        
        result = await get_current_chat_user(mock_request)
        
        assert result["user_id"] == "test_user"
        assert result["role"] == "user"
        assert "chat:read" in result["permissions"]
    
    @pytest.mark.asyncio
    async def test_get_current_chat_user_no_context(self):
        """Test user extraction with no context in request state."""
        # Mock request with no user context
        mock_request = Mock()
        del mock_request.state.user_context
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_chat_user(mock_request)
        
        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)


class TestSecurityValidation:
    """Test security validation functionality."""
    
    def test_content_validation_safe(self):
        """Test validation of safe content."""
        content = "This is a safe message."
        validator = ContentValidator(SecurityLevel.MEDIUM)
        result = validator.validate_content(content)
        
        assert result.is_valid is True
        assert len(result.threats_detected) == 0
    
    def test_content_validation_xss(self):
        """Test validation of content with XSS."""
        content = "<script>alert('xss')</script>"
        validator = ContentValidator(SecurityLevel.MEDIUM)
        result = validator.validate_content(content)
        
        assert result.is_valid is False
        assert any("xss" in threat.lower() for threat in result.threats_detected)
    
    def test_content_validation_sql_injection(self):
        """Test validation of content with SQL injection."""
        content = "'; DROP TABLE users; --"
        validator = ContentValidator(SecurityLevel.MEDIUM)
        result = validator.validate_content(content)
        
        assert result.is_valid is False
        assert any("sql" in threat.lower() for threat in result.threats_detected)
    
    def test_input_sanitization(self):
        """Test input sanitization."""
        from server.chat.security import sanitize_content as sanitize_input
        input_text = "<script>alert('xss')</script>Hello World"
        result = sanitize_input(input_text)
        
        assert "<script>" not in result
        assert "Hello World" in result
    
    def test_validate_content_function(self):
        """Test global validate_content function."""
        from server.chat.security import validate_content
        
        content = "This is a safe message."
        result = validate_content(content)
        
        assert result.is_valid is True
        assert len(result.threats_detected) == 0


class TestRateLimiting:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_within_limit(self):
        """Test rate limiter within allowed limits."""
        config = RateLimitConfig(
            limit_type=RateLimitType.MESSAGES_PER_MINUTE,
            max_requests=5,
            window_seconds=60
        )
        limiter = RateLimiter(config)
        
        # Make requests within limit
        for i in range(5):
            allowed, retry_seconds = await limiter.is_allowed("test_user")
            assert allowed is True
            assert retry_seconds is None
    
    @pytest.mark.asyncio
    async def test_rate_limiter_exceeds_limit(self):
        """Test rate limiter when limit is exceeded."""
        config = RateLimitConfig(
            limit_type=RateLimitType.MESSAGES_PER_MINUTE,
            max_requests=5,
            window_seconds=60
        )
        limiter = RateLimiter(config)
        
        # Make requests within limit
        for i in range(5):
            await limiter.is_allowed("test_user")
        
        # Next request should be blocked
        allowed, retry_seconds = await limiter.is_allowed("test_user")
        assert allowed is False
        assert retry_seconds is not None
        assert retry_seconds > 0
    
    @pytest.mark.asyncio
    async def test_abuse_detector(self):
        """Test abuse detection."""
        config = AbuseDetectionConfig()
        detector = AbuseDetector(config)
        
        # Simulate suspicious activity
        content = "SELECT * FROM users WHERE 1=1"
        allowed, patterns = await detector.check_content("test_ip", content)
        
        assert allowed is False
        assert len(patterns) > 0
        assert any("select" in pattern.lower() for pattern in patterns)
    
    @pytest.mark.asyncio
    async def test_chat_rate_limiting_service(self):
        """Test chat rate limiting service."""
        service = ChatRateLimitingService()
        
        # Check rate limit for new user
        allowed, retry_seconds, message = await service.check_rate_limit(
            "test_user", RateLimitType.MESSAGES_PER_MINUTE
        )
        
        assert allowed is True
        assert retry_seconds is None
        assert message is None


class TestAuditLogging:
    """Test audit logging functionality."""
    
    @pytest.mark.asyncio
    async def test_log_event(self):
        """Test logging an audit event."""
        audit_logger = AuditLogger()
        
        await audit_logger.log_event(
            event_type=AuditEventType.USER_LOGIN,
            severity=AuditSeverity.LOW,
            user_id="test_user",
            ip_address="127.0.0.1"
        )
        
        assert len(audit_logger.events) == 1
        assert audit_logger.events[0].event_type == AuditEventType.USER_LOGIN
        assert audit_logger.events[0].user_id == "test_user"
        assert audit_logger.events[0].ip_address == "127.0.0.1"
    
    @pytest.mark.asyncio
    async def test_log_security_alert(self):
        """Test logging a security alert."""
        audit_logger = AuditLogger()
        
        await audit_logger.log_security_alert(
            alert_type="brute_force_attack",
            severity=AuditSeverity.HIGH,
            description="Multiple failed login attempts",
            ip_address="127.0.0.1",
            threat_level=AuditThreatLevel.HIGH
        )
        
        assert len(audit_logger.alerts) == 1
        assert audit_logger.alerts[0].alert_type == "brute_force_attack"
        assert audit_logger.alerts[0].severity == AuditSeverity.HIGH
        assert audit_logger.alerts[0].ip_address == "127.0.0.1"
    
    def test_get_events_filtered(self):
        """Test getting filtered audit events."""
        audit_logger = AuditLogger()
        
        # Add test events
        audit_logger.events = [
            Mock(event_type=AuditEventType.USER_LOGIN, user_id="user1"),
            Mock(event_type=AuditEventType.MESSAGE_SENT, user_id="user1"),
            Mock(event_type=AuditEventType.USER_LOGIN, user_id="user2"),
        ]
        
        # Get events for user1
        events = audit_logger.get_events(user_id="user1")
        assert len(events) == 2
        
        # Get login events
        events = audit_logger.get_events(event_type=AuditEventType.USER_LOGIN)
        assert len(events) == 2
    
    def test_get_statistics(self):
        """Test getting audit statistics."""
        audit_logger = AuditLogger()
        
        # Add test events
        audit_logger.events = [
            Mock(event_type=AuditEventType.USER_LOGIN, severity=AuditSeverity.LOW),
            Mock(event_type=AuditEventType.MESSAGE_SENT, severity=AuditSeverity.LOW),
            Mock(event_type=AuditEventType.SECURITY_VIOLATION, severity=AuditSeverity.HIGH),
        ]
        
        stats = audit_logger.get_statistics()
        
        assert stats["total_events"] == 3
        assert stats["events_by_type"]["user_login"] == 1
        assert stats["events_by_type"]["message_sent"] == 1
        assert stats["events_by_type"]["security_violation"] == 1
        assert stats["events_by_severity"]["low"] == 2
        assert stats["events_by_severity"]["high"] == 1


class TestSecurityMonitoring:
    """Test security monitoring functionality."""
    
    @pytest.mark.asyncio
    async def test_monitor_failed_logins(self):
        """Test monitoring of failed logins."""
        audit_logger = AuditLogger()
        monitoring_service = SecurityMonitoringService(audit_logger)
        
        # Add failed login events
        for i in range(6):  # Exceed threshold of 5
            await audit_logger.log_event(
                event_type=AuditEventType.LOGIN_FAILED,
                severity=AuditSeverity.MEDIUM,
                ip_address="127.0.0.1"
            )
        
        # Monitor failed logins
        await monitoring_service.monitor_failed_logins("127.0.0.1")
        
        # Should have generated a security alert
        assert len(audit_logger.alerts) == 1
        assert audit_logger.alerts[0].alert_type == "brute_force_attack"
        assert audit_logger.alerts[0].ip_address == "127.0.0.1"
    
    @pytest.mark.asyncio
    async def test_monitor_security_events(self):
        """Test monitoring of security events."""
        audit_logger = AuditLogger()
        monitoring_service = SecurityMonitoringService(audit_logger)
        
        # Add security events
        for i in range(11):  # Exceed threshold of 10
            await audit_logger.log_event(
                event_type=AuditEventType.SECURITY_VIOLATION,
                severity=AuditSeverity.MEDIUM
            )
        
        # Monitor security events
        await monitoring_service.monitor_security_events()
        
        # Should have generated a security alert
        assert len(audit_logger.alerts) == 1
        assert audit_logger.alerts[0].alert_type == "elevated_security_activity"


class TestEncryption:
    """Test encryption functionality."""
    
    def test_encrypt_decrypt(self):
        """Test encryption and decryption."""
        manager = EncryptionManager()
        
        original_data = "This is sensitive data"
        encrypted_data = manager.encrypt(original_data)
        decrypted_data = manager.decrypt(encrypted_data)
        
        assert encrypted_data != original_data
        assert decrypted_data == original_data
    
    def test_encrypt_sensitive_fields(self):
        """Test encrypting specific fields in a dictionary."""
        manager = EncryptionManager()
        
        data = {
            "user_id": "123",
            "email": "user@example.com",
            "password": "secret123"
        }
        
        encrypted_data = manager.encrypt_sensitive_fields(data, ["password"])
        
        assert encrypted_data["user_id"] == "123"
        assert encrypted_data["email"] == "user@example.com"
        assert encrypted_data["password"] != "secret123"
        assert encrypted_data["password"].startswith("gAAAA")  # Fernet encrypted format
    
    def test_decrypt_sensitive_fields(self):
        """Test decrypting specific fields in a dictionary."""
        manager = EncryptionManager()
        
        data = {
            "user_id": "123",
            "email": "user@example.com",
            "password": "gAAAA..."  # Encrypted password
        }
        
        # First encrypt a password to have valid encrypted data
        original_data = {
            "user_id": "123",
            "email": "user@example.com",
            "password": "secret123"
        }
        encrypted_data = manager.encrypt_sensitive_fields(original_data, ["password"])
        
        # Now decrypt it
        decrypted_data = manager.decrypt_sensitive_fields(encrypted_data, ["password"])
        
        assert decrypted_data["user_id"] == "123"
        assert decrypted_data["email"] == "user@example.com"
        assert decrypted_data["password"] == "secret123"


class TestSecurityMonitor:
    """Test security monitor functionality."""
    
    def test_log_event(self):
        """Test logging a security event."""
        from server.chat.security import SecurityEvent, get_security_monitor
        
        monitor = get_security_monitor()
        
        event = SecurityEvent(
            timestamp=datetime.utcnow(),
            event_type="test_event",
            threat_level=ThreatLevel.MEDIUM,
            user_id="test_user",
            ip_address="127.0.0.1",
            user_agent="test_agent",
            details={"test": "data"}
        )
        
        monitor.log_event(event)
        
        assert len(monitor.events) == 1
        assert monitor.events[0].event_type == "test_event"
    
    def test_get_threat_summary(self):
        """Test getting threat summary."""
        from server.chat.security import SecurityEvent, get_security_monitor
        
        monitor = get_security_monitor()
        monitor.events = []
        
        # Add test events
        now = datetime.utcnow()
        events = [
            SecurityEvent(now, "event1", ThreatLevel.LOW, "user1", "1.1.1.1", "agent1", {}),
            SecurityEvent(now, "event2", ThreatLevel.HIGH, "user2", "1.1.1.2", "agent2", {}),
            SecurityEvent(now, "event3", ThreatLevel.MEDIUM, "user3", "1.1.1.3", "agent3", {}),
        ]
        
        for event in events:
            monitor.log_event(event)
        
        summary = monitor.get_threat_summary(hours=24)
        
        assert summary["total_events"] == 3
        assert summary["threat_levels"]["low"] == 1
        assert summary["threat_levels"]["medium"] == 1
        assert summary["threat_levels"]["high"] == 1
        assert len(summary["most_active_ips"]) == 3


class TestMiddlewareIntegration:
    """Test middleware integration."""
    
    @pytest.mark.asyncio
    async def test_rate_limit_middleware(self):
        """Test rate limiting middleware."""
        # Mock request and call_next
        mock_request = Mock()
        mock_request.client = Mock(host="127.0.0.1")
        mock_request.headers = {}
        mock_request.url = Mock(path="/api/chat/messages")
        mock_request.method = "POST"
        
        mock_response = Mock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        
        # Create middleware
        middleware = ChatAuthenticationMiddleware(Mock())
        middleware.rate_limits = {"requests_per_minute": 5, "message_per_minute": 5, "burst_limit": 5}
        
        with patch.object(middleware, "_validate_jwt_token", new_callable=AsyncMock, return_value={"sub": "test_user"}):
            # Make requests within limit
            for i in range(5):
                response = await middleware._process_request(mock_request, mock_call_next)
                assert response == mock_response
            
            # Next request should be rate limited
            response = await middleware._process_request(mock_request, mock_call_next)
            assert response.status_code == 429
    
    @pytest.mark.asyncio
    async def test_security_headers_middleware(self):
        """Test security headers middleware."""
        # Mock request and call_next
        mock_request = Mock()
        mock_request.client = Mock(host="127.0.0.1")
        mock_request.headers = {}
        mock_request.url = Mock(path="/health")
        mock_request.method = "GET"
        mock_response = Mock()
        mock_response.headers = {}
        mock_call_next = AsyncMock(return_value=mock_response)
        
        # Create middleware
        middleware = ChatAuthenticationMiddleware(Mock())
        
        # Apply middleware
        response = await middleware._process_request(mock_request, mock_call_next)
        middleware._add_security_headers(response)
        
        # Check security headers
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert "Content-Security-Policy" in response.headers


class TestWebSocketSecurity:
    """Test WebSocket security functionality."""
    
    @pytest.mark.asyncio
    async def test_websocket_authentication(self):
        """Test WebSocket authentication."""
        from server.chat.websocket import ConnectionManager, get_current_user_websocket
        
        manager = ConnectionManager()
        
        # Mock WebSocket with valid token
        mock_websocket = Mock(spec=WebSocket)
        mock_websocket.headers = {"authorization": "Bearer valid_token"}
        
        payload = {
            "sub": "test_user",
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow(),
            "role": "user"
        }
        
        with patch('server.chat.websocket.verify_jwt_token') as mock_verify:
            mock_verify.return_value = payload
            
            # This should not raise an exception
            user_context = await get_current_user_websocket(mock_websocket)
            
        assert user_context is not None
        assert user_context["sub"] == "test_user"
    
    @pytest.mark.asyncio
    async def test_websocket_authentication_invalid_token(self):
        """Test WebSocket authentication with invalid token."""
        from server.chat.websocket import ConnectionManager, get_current_user_websocket
        
        manager = ConnectionManager()
        
        # Mock WebSocket with invalid token
        mock_websocket = Mock(spec=WebSocket)
        mock_websocket.headers = {"authorization": "Bearer invalid_token"}
        mock_websocket.close = AsyncMock()
        
        with patch('server.chat.websocket.verify_jwt_token') as mock_verify:
            mock_verify.return_value = None
            
            # This should close websocket
            user_context = await get_current_user_websocket(mock_websocket)
            
        assert user_context is None
        mock_websocket.close.assert_called_once()


class TestRateLimitingIntegration:
    """Test rate limiting integration."""
    
    @pytest.mark.asyncio
    async def test_check_message_rate_limit(self):
        """Test message rate limit check."""
        # Mock successful check
        with patch('server.chat.rate_limiting.get_rate_limiting_service') as mock_service:
            mock_service_instance = Mock()
            mock_service_instance.check_rate_limit = AsyncMock(return_value=(True, None, None))
            mock_service.return_value = mock_service_instance
            
            result = await check_message_rate_limit("test_user")
            
            assert result[0] is True  # allowed
            assert result[1] is None  # retry_seconds
            assert result[2] is None  # message


if __name__ == "__main__":
    pytest.main([__file__])