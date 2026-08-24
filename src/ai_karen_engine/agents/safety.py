"""
Safety and security module for agent architecture system.

.. deprecated::
    The legacy safety module is deprecated. Safety checks are now handled by
    ``ai_karen_engine.agent_medusa.safety`` and canonical policy enforcement.
"""

import html
import os
import logging
import re
import json
import time
import warnings
from enum import Enum
from typing import Dict, List, Any, Optional, Union, Tuple

warnings.warn(
    "ai_karen_engine.agents.safety is deprecated. "
    "Use ai_karen_engine.agent_medusa.safety instead.",
    DeprecationWarning,
    stacklevel=2,
)
from datetime import datetime, timedelta
from dataclasses import dataclass, field

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

# Import local application modules
try:
    from ..internal import agent_schemas, agent_validation
    from ..internal.agent_schemas import AgentSchema
    from ..internal.agent_validation import ValidationResult
    INTERNAL_MODULES_AVAILABLE = True
except ImportError:
    INTERNAL_MODULES_AVAILABLE = False


class SafetyLevel(Enum):
    """Enum representing different safety levels."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class SecurityLevel(Enum):
    """Enum representing different security levels."""
    BASIC = 1
    ENHANCED = 2
    RESTRICTED = 3
    LOCKDOWN = 4


class ThreatType(Enum):
    """Enum representing different types of threats."""
    MALICIOUS_INPUT = 1
    DATA_LEAK = 2
    UNAUTHORIZED_ACCESS = 3
    ANOMALOUS_BEHAVIOR = 4
    RESOURCE_ABUSE = 5
    PRIVACY_VIOLATION = 6
    INJECTION_ATTACK = 7
    DENIAL_OF_SERVICE = 8


@dataclass
class SecurityEvent:
    """Data class for security events."""
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    severity: SafetyLevel = SafetyLevel.MEDIUM
    agent_id: Optional[str] = None
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    threat_type: Optional[ThreatType] = None


class SafetyManager:
    """
    Safety and security manager for agent operations.
    
    This class provides comprehensive safety and security measures including
    input validation, threat detection, access control, and security event logging.
    
    Attributes:
        config (Dict[str, Any]): Configuration for the safety manager
        safety_level (SafetyLevel): Current safety level
        security_level (SecurityLevel): Current security level
        logger (logging.Logger): Logger for security events
        security_events (List[SecurityEvent]): List of security events
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        safety_level: SafetyLevel = SafetyLevel.MEDIUM,
        security_level: SecurityLevel = SecurityLevel.ENHANCED,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize the SafetyManager.
        
        Args:
            config: Configuration dictionary for safety and security settings
            safety_level: Initial safety level
            security_level: Initial security level
            logger: Optional logger instance, will create one if not provided
        """
        self.config = config
        self.safety_level = safety_level
        self.security_level = security_level
        
        # Setup logging
        if logger is None:
            self.logger = logging.getLogger(__name__)
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
                handler.setFormatter(formatter)
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)
        else:
            self.logger = logger
        
        # Initialize security event storage
        self.security_events: List[SecurityEvent] = []
        
        # Initialize encryption if available
        self.encryption_key = None
        self.cipher_suite = None
        if CRYPTOGRAPHY_AVAILABLE:
            self._initialize_encryption()
        
        # Load security patterns and rules
        self.malicious_patterns = self._load_malicious_patterns()
        self.sensitive_data_patterns = self._load_sensitive_data_patterns()
        
        # Initialize access control matrices
        self.access_control_matrix = self._initialize_access_control()
        
        self.logger.info(
            f"SafetyManager initialized with safety level {safety_level.name} "
            f"and security level {security_level.name}"
        )
    
    def _initialize_encryption(self) -> None:
        """Initialize encryption capabilities if available."""
        try:
            # Generate or load encryption key
            key = self.config.get("encryption_key")
            if not key:
                key = Fernet.generate_key()  # type: ignore
                self.config["encryption_key"] = key.decode()
            
            # Create cipher suite
            self.encryption_key = key if isinstance(key, bytes) else key.encode()
            self.cipher_suite = Fernet(self.encryption_key)  # type: ignore
            
            self.logger.info("Encryption capabilities initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize encryption: {str(e)}")
            self.encryption_key = None
            self.cipher_suite = None
    
    def _load_malicious_patterns(self) -> List[re.Pattern]:
        """Load patterns for detecting malicious input."""
        patterns = [
            # SQL Injection patterns
            re.compile(r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|EXEC|ALTER)\b)", re.IGNORECASE),
            re.compile(r"(''|\';|';|\"|\";|\"|--|#|\/\*|\*\/|0x)", re.IGNORECASE),
            
            # XSS patterns
            re.compile(r"(<script|javascript:|on\w+\s*=|eval\(|expression\()", re.IGNORECASE),
            
            # Command injection patterns
            re.compile(r"(;|\||&|\$\(|`|>|<|\${)", re.IGNORECASE),
            
            # Path traversal patterns
            re.compile(r"(\.\./|\.\.\\\)", re.IGNORECASE),
            
            # Additional patterns from config
        ]
        
        # Add custom patterns from config if available
        custom_patterns = self.config.get("malicious_patterns", [])
        for pattern in custom_patterns:
            try:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                self.logger.warning(f"Invalid malicious pattern '{pattern}': {str(e)}")
        
        return patterns
    
    def _load_sensitive_data_patterns(self) -> List[re.Pattern]:
        """Load patterns for detecting sensitive data in output."""
        patterns = [
            # Credit card patterns
            re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
            
            # SSN patterns
            re.compile(r"\b\d{3}[ -]?\d{2}[ -]?\d{4}\b"),
            
            # API key patterns
            re.compile(r"\b[A-Za-z0-9]{32,}\b"),
            
            # Email patterns
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            
            # Phone number patterns
            re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b"),
        ]
        
        # Add custom patterns from config if available
        custom_patterns = self.config.get("sensitive_data_patterns", [])
        for pattern in custom_patterns:
            try:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                self.logger.warning(f"Invalid sensitive data pattern '{pattern}': {str(e)}")
        
        return patterns
    
    def _initialize_access_control(self) -> Dict[str, Dict[str, List[str]]]:
        """Initialize access control matrix."""
        # Default access control matrix
        default_matrix = {
            "admin": {
                "read": ["all"],
                "write": ["all"],
                "execute": ["all"],
                "delete": ["all"]
            },
            "user": {
                "read": ["public_data", "user_data"],
                "write": ["user_data"],
                "execute": ["basic_tools"],
                "delete": ["user_data"]
            },
            "guest": {
                "read": ["public_data"],
                "write": [],
                "execute": ["limited_tools"],
                "delete": []
            }
        }
        
        # Merge with config if available
        config_matrix = self.config.get("access_control_matrix", {})
        for role, permissions in config_matrix.items():
            if role in default_matrix:
                for perm_type, resources in permissions.items():
                    if perm_type in default_matrix[role]:
                        default_matrix[role][perm_type] = resources
            else:
                default_matrix[role] = permissions
        
        return default_matrix
    
    def validate_input(self, input_data: Any, agent_id: Optional[str] = None) -> 'ValidationResult':
        """
        Validate input against safety rules.
        
        Args:
            input_data: Input data to validate
            agent_id: Optional ID of the agent providing the input
            
        Returns:
            ValidationResult with validation status and details
        """
        if INTERNAL_MODULES_AVAILABLE:
            result = agent_validation.validate_input(input_data)  # type: ignore
        else:
            # Basic validation if internal modules not available
            result = ValidationResult(is_valid=True, errors=[], warnings=[])  # type: ignore
            
            if isinstance(input_data, str):
                # Check for malicious patterns
                malicious_detected = self.detect_malicious_input(input_data)
                if malicious_detected:
                    result.is_valid = False
                    result.errors.append("Malicious input detected")
                    
                    # Log security event
                    self.log_security_event(
                        event_type="MALICIOUS_INPUT_DETECTED",
                        severity=SafetyLevel.HIGH,
                        agent_id=agent_id,
                        description="Malicious input patterns detected in validation",
                        threat_type=ThreatType.MALICIOUS_INPUT,
                        details={"input_preview": input_data[:100] + "..." if len(input_data) > 100 else input_data}
                    )
        
        return result
    
    def sanitize_input(self, input_data: Any, agent_id: Optional[str] = None) -> Any:
        """
        Sanitize input to remove potentially harmful content.
        
        Args:
            input_data: Input data to sanitize
            agent_id: Optional ID of the agent providing the input
            
        Returns:
            Sanitized input data
        """
        if not isinstance(input_data, str):
            return input_data
        
        # Remove potentially harmful characters and patterns
        sanitized = input_data
        
        # Remove null bytes
        sanitized = sanitized.replace('\x00', '')
        
        # Remove control characters except for common whitespace
        sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\n\r\t')
        
        # Escape HTML fragments and normalize quotes
        sanitized = html.escape(sanitized, quote=True)
        # Using character code instead of HTML entity for more reliable replacement
        sanitized = sanitized.replace("'", chr(39))
        
        # Log sanitization if changes were made
        if sanitized != input_data:
            self.log_security_event(
                event_type="INPUT_SANITIZED",
                severity=SafetyLevel.LOW,
                agent_id=agent_id,
                description="Input was sanitized to remove potentially harmful content",
                threat_type=ThreatType.MALICIOUS_INPUT,
                details={
                    "original_length": len(input_data),
                    "sanitized_length": len(sanitized)
                }
            )
        
        return sanitized
    
    def validate_output(self, output_data: Any, agent_id: Optional[str] = None) -> 'ValidationResult':
        """
        Validate output to ensure it doesn't contain sensitive information.
        
        Args:
            output_data: Output data to validate
            agent_id: Optional ID of the agent generating the output
            
        Returns:
            ValidationResult with validation status and details
        """
        if INTERNAL_MODULES_AVAILABLE:
            result = agent_validation.validate_output(output_data)  # type: ignore
        else:
            # Basic validation if internal modules not available
            result = ValidationResult(is_valid=True, errors=[], warnings=[])  # type: ignore
            
            if isinstance(output_data, str):
                # Check for sensitive data patterns
                data_leak_detected = self.detect_data_leak(output_data)
                if data_leak_detected:
                    result.is_valid = False
                    result.errors.append("Potential data leak detected")
                    
                    # Log security event
                    self.log_security_event(
                        event_type="DATA_LEAK_DETECTED",
                        severity=SafetyLevel.HIGH,
                        agent_id=agent_id,
                        description="Sensitive data patterns detected in output",
                        threat_type=ThreatType.DATA_LEAK,
                        details={"output_preview": output_data[:100] + "..." if len(output_data) > 100 else output_data}
                    )
        
        return result
    
    def sanitize_output(self, output_data: Any, agent_id: Optional[str] = None) -> Any:
        """
        Sanitize output to remove sensitive information.
        
        Args:
            output_data: Output data to sanitize
            agent_id: Optional ID of the agent generating the output
            
        Returns:
            Sanitized output data
        """
        if not isinstance(output_data, str):
            return output_data
        
        # Redact sensitive information
        sanitized = output_data
        
        # Apply sensitive data patterns
        for pattern in self.sensitive_data_patterns:
            sanitized = pattern.sub("[REDACTED]", sanitized)
        
        # Log sanitization if changes were made
        if sanitized != output_data:
            self.log_security_event(
                event_type="OUTPUT_SANITIZED",
                severity=SafetyLevel.LOW,
                agent_id=agent_id,
                description="Output was sanitized to remove sensitive information",
                threat_type=ThreatType.DATA_LEAK,
                details={
                    "original_length": len(output_data),
                    "sanitized_length": len(sanitized)
                }
            )
        
        return sanitized
    
    def detect_malicious_input(self, input_data: str) -> bool:
        """
        Detect potentially malicious input patterns.
        
        Args:
            input_data: Input string to analyze
            
        Returns:
            True if malicious patterns are detected, False otherwise
        """
        if not isinstance(input_data, str):
            return False
        
        # Check against malicious patterns
        for pattern in self.malicious_patterns:
            if pattern.search(input_data):
                return True
        
        return False
    
    def detect_data_leak(self, output_data: str) -> bool:
        """
        Detect potential data leaks in output.
        
        Args:
            output_data: Output string to analyze
            
        Returns:
            True if sensitive data patterns are detected, False otherwise
        """
        if not isinstance(output_data, str):
            return False
        
        # Check against sensitive data patterns
        for pattern in self.sensitive_data_patterns:
            if pattern.search(output_data):
                return True
        
        return False
    
    def detect_unauthorized_access(self, agent_id: str, resource: str, action: str) -> bool:
        """
        Detect unauthorized access attempts.
        
        Args:
            agent_id: ID of the agent attempting access
            resource: Resource being accessed
            action: Action being performed
            
        Returns:
            True if access is unauthorized, False otherwise
        """
        # Get agent role (simplified for this example)
        agent_role = self._get_agent_role(agent_id)
        
        # Check if role exists in access control matrix
        if agent_role not in self.access_control_matrix:
            return True  # Unauthorized if role not defined
        
        # Check if action is allowed for this role
        if action not in self.access_control_matrix[agent_role]:
            return True  # Unauthorized if action not defined
        
        # Check if resource is accessible for this action
        allowed_resources = self.access_control_matrix[agent_role][action]
        if "all" not in allowed_resources and resource not in allowed_resources:
            return True  # Unauthorized if resource not in allowed list
        
        return False  # Authorized
    
    def _get_agent_role(self, agent_id: str) -> str:
        """
        Get the role of an agent (simplified implementation).
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Role of the agent
        """
        # In a real implementation, this would query a database or other storage
        # For this example, we'll use a simple mapping
        agent_roles = self.config.get("agent_roles", {})
        return agent_roles.get(agent_id, "guest")  # Default to guest role
    
    def detect_anomalous_behavior(self, agent_id: str, behavior_data: Dict[str, Any]) -> bool:
        """
        Detect anomalous behavior patterns.
        
        Args:
            agent_id: ID of the agent to analyze
            behavior_data: Dictionary containing behavior metrics
            
        Returns:
            True if anomalous behavior is detected, False otherwise
        """
        # Get baseline behavior for this agent
        baseline = self._get_agent_baseline(agent_id)
        
        if not baseline:
            # No baseline available, cannot detect anomalies
            return False
        
        # Simple anomaly detection based on deviation from baseline
        anomalies = []
        
        # Check request rate
        if "requests_per_minute" in behavior_data and "requests_per_minute" in baseline:
            current_rate = behavior_data["requests_per_minute"]
            baseline_rate = baseline["requests_per_minute"]
            threshold = baseline.get("requests_per_minute_threshold", 5.0)  # 5x threshold
            
            if current_rate > baseline_rate * threshold:
                anomalies.append(f"High request rate: {current_rate} vs baseline {baseline_rate}")
        
        # Check error rate
        if "error_rate" in behavior_data and "error_rate" in baseline:
            current_error_rate = behavior_data["error_rate"]
            baseline_error_rate = baseline["error_rate"]
            threshold = baseline.get("error_rate_threshold", 3.0)  # 3x threshold
            
            if current_error_rate > baseline_error_rate * threshold:
                anomalies.append(f"High error rate: {current_error_rate} vs baseline {baseline_error_rate}")
        
        # Check resource usage
        if "cpu_usage" in behavior_data and "cpu_usage" in baseline:
            current_cpu = behavior_data["cpu_usage"]
            baseline_cpu = baseline["cpu_usage"]
            threshold = baseline.get("cpu_usage_threshold", 2.0)  # 2x threshold
            
            if current_cpu > baseline_cpu * threshold:
                anomalies.append(f"High CPU usage: {current_cpu}% vs baseline {baseline_cpu}%")
        
        # Log anomalies if detected
        if anomalies:
            self.log_security_event(
                event_type="ANOMALOUS_BEHAVIOR_DETECTED",
                severity=SafetyLevel.MEDIUM,
                agent_id=agent_id,
                description=f"Anomalous behavior detected: {', '.join(anomalies)}",
                threat_type=ThreatType.ANOMALOUS_BEHAVIOR,
                details={
                    "anomalies": anomalies,
                    "behavior_data": behavior_data,
                    "baseline": baseline
                }
            )
            return True
        
        return False
    
    def _get_agent_baseline(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get baseline behavior for an agent (simplified implementation).
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Dictionary containing baseline behavior metrics or None if not available
        """
        # In a real implementation, this would query a database or other storage
        # For this example, we'll use a simple mapping
        agent_baselines = self.config.get("agent_baselines", {})
        return agent_baselines.get(agent_id)
    
    def check_permission(self, agent_id: str, resource: str, action: str) -> bool:
        """
        Check if an agent has permission to perform an action.
        
        Args:
            agent_id: ID of the agent
            resource: Resource to access
            action: Action to perform
            
        Returns:
            True if permission is granted, False otherwise
        """
        # Check if access is unauthorized
        if self.detect_unauthorized_access(agent_id, resource, action):
            # Log security event
            self.log_security_event(
                event_type="UNAUTHORIZED_ACCESS_ATTEMPT",
                severity=SafetyLevel.HIGH,
                agent_id=agent_id,
                description=f"Unauthorized access attempt: {action} on {resource}",
                threat_type=ThreatType.UNAUTHORIZED_ACCESS,
                details={
                    "agent_id": agent_id,
                    "resource": resource,
                    "action": action
                }
            )
            return False
        
        return True
    
    def enforce_permission(self, agent_id: str, resource: str, action: str) -> bool:
        """
        Enforce permission checks for agent actions.
        
        Args:
            agent_id: ID of the agent
            resource: Resource to access
            action: Action to perform
            
        Returns:
            True if action is allowed, False otherwise
            
        Raises:
            PermissionError: If action is not allowed and enforcement is strict
        """
        has_permission = self.check_permission(agent_id, resource, action)
        
        if not has_permission:
            # Get enforcement level from config
            enforcement_level = self.config.get("permission_enforcement_level", "strict")
            
            if enforcement_level == "strict":
                raise PermissionError(f"Agent {agent_id} does not have permission to {action} on {resource}")
            
            return False
        
        return True
    
    def validate_agent_access(self, agent_id: str, resource: str) -> bool:
        """
        Validate agent access to resources.
        
        Args:
            agent_id: ID of the agent
            resource: Resource to access
            
        Returns:
            True if access is allowed, False otherwise
        """
        return self.check_permission(agent_id, resource, "read")
    
    def validate_tool_access(self, agent_id: str, tool_name: str) -> bool:
        """
        Validate agent access to tools.
        
        Args:
            agent_id: ID of the agent
            tool_name: Name of the tool to access
            
        Returns:
            True if access is allowed, False otherwise
        """
        return self.check_permission(agent_id, tool_name, "execute")
    
    def log_security_event(
        self,
        event_type: str,
        severity: SafetyLevel,
        agent_id: Optional[str] = None,
        description: str = "",
        threat_type: Optional[ThreatType] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log security events with appropriate severity levels.
        
        Args:
            event_type: Type of security event
            severity: Severity level of the event
            agent_id: Optional ID of the agent involved
            description: Description of the event
            threat_type: Optional type of threat
            details: Optional dictionary with additional details
        """
        # Create security event
        event = SecurityEvent(
            event_type=event_type,
            severity=severity,
            agent_id=agent_id,
            description=description,
            details=details or {},
            threat_type=threat_type
        )
        
        # Add to security events list
        self.security_events.append(event)
        
        # Log based on severity
        if severity == SafetyLevel.CRITICAL:
            self.logger.critical(f"SECURITY EVENT: {event_type} - {description}")
        elif severity == SafetyLevel.HIGH:
            self.logger.error(f"SECURITY EVENT: {event_type} - {description}")
        elif severity == SafetyLevel.MEDIUM:
            self.logger.warning(f"SECURITY EVENT: {event_type} - {description}")
        else:  # LOW
            self.logger.info(f"SECURITY EVENT: {event_type} - {description}")
    
    def get_security_events(
        self,
        agent_id: Optional[str] = None,
        threat_type: Optional[ThreatType] = None,
        severity: Optional[SafetyLevel] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: Optional[int] = None
    ) -> List[SecurityEvent]:
        """
        Retrieve security events based on filters.
        
        Args:
            agent_id: Optional filter by agent ID
            threat_type: Optional filter by threat type
            severity: Optional filter by severity level
            start_time: Optional filter by start time
            end_time: Optional filter by end time
            limit: Optional maximum number of events to return
            
        Returns:
            List of filtered security events
        """
        # Start with all events
        filtered_events = self.security_events.copy()
        
        # Apply filters
        if agent_id is not None:
            filtered_events = [e for e in filtered_events if e.agent_id == agent_id]
        
        if threat_type is not None:
            filtered_events = [e for e in filtered_events if e.threat_type == threat_type]
        
        if severity is not None:
            filtered_events = [e for e in filtered_events if e.severity == severity]
        
        if start_time is not None:
            filtered_events = [e for e in filtered_events if e.timestamp >= start_time]
        
        if end_time is not None:
            filtered_events = [e for e in filtered_events if e.timestamp <= end_time]
        
        # Sort by timestamp (newest first)
        filtered_events.sort(key=lambda e: e.timestamp, reverse=True)
        
        # Apply limit
        if limit is not None:
            filtered_events = filtered_events[:limit]
        
        return filtered_events
    
    def clear_security_events(
        self,
        retention_days: Optional[int] = None,
        agent_id: Optional[str] = None,
        severity: Optional[SafetyLevel] = None
    ) -> int:
        """
        Clear old security events based on retention policy.
        
        Args:
            retention_days: Number of days to retain events (None for no retention)
            agent_id: Optional filter by agent ID
            severity: Optional filter by severity level
            
        Returns:
            Number of events cleared
        """
        original_count = len(self.security_events)
        
        # Calculate cutoff time if retention_days is specified
        cutoff_time = None
        if retention_days is not None:
            cutoff_time = datetime.now() - timedelta(days=retention_days)
        
        # Apply filters
        events_to_keep = []
        
        for event in self.security_events:
            # Check retention period
            if cutoff_time is not None and event.timestamp < cutoff_time:
                continue  # Don't keep this event
            
            # Check agent filter
            if agent_id is not None and event.agent_id != agent_id:
                continue  # Don't keep this event
            
            # Check severity filter
            if severity is not None and event.severity != severity:
                continue  # Don't keep this event
            
            events_to_keep.append(event)
        
        # Update security events list
        self.security_events = events_to_keep
        
        # Return number of cleared events
        return original_count - len(self.security_events)
    
    def handle_security_violation(
        self,
        agent_id: str,
        violation_type: ThreatType,
        severity: SafetyLevel,
        description: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Handle security violations with appropriate actions.
        
        Args:
            agent_id: ID of the agent violating security
            violation_type: Type of security violation
            severity: Severity level of the violation
            description: Description of the violation
            details: Optional dictionary with additional details
        """
        # Log security event
        self.log_security_event(
            event_type="SECURITY_VIOLATION",
            severity=severity,
            agent_id=agent_id,
            description=description,
            threat_type=violation_type,
            details=details or {}
        )
        
        # Get violation handling configuration
        handling_config = self.config.get("violation_handling", {})
        
        # Get actions based on violation type and severity
        actions = []
        violation_key = f"{violation_type.name}_{severity.name}"
        
        if violation_key in handling_config:
            actions = handling_config[violation_key]
        elif violation_type.name in handling_config:
            actions = handling_config[violation_type.name]
        elif severity.name in handling_config:
            actions = handling_config[severity.name]
        else:
            # Default actions based on severity
            if severity == SafetyLevel.CRITICAL:
                actions = ["quarantine", "escalate", "alert"]
            elif severity == SafetyLevel.HIGH:
                actions = ["restrict", "escalate", "log"]
            elif severity == SafetyLevel.MEDIUM:
                actions = ["warn", "log"]
            else:  # LOW
                actions = ["log"]
        
        # Execute actions
        for action in actions:
            try:
                if action == "quarantine":
                    self.quarantine_agent(agent_id, description)
                elif action == "escalate":
                    self.escalate_security_violation(agent_id, violation_type, severity, description, details)
                elif action == "alert":
                    self.logger.error(f"SECURITY ALERT: Agent {agent_id} - {description}")
                elif action == "restrict":
                    self._restrict_agent(agent_id)
                elif action == "warn":
                    self.logger.warning(f"SECURITY WARNING: Agent {agent_id} - {description}")
                elif action == "log":
                    # Already logged above
                    pass
            except Exception as e:
                self.logger.error(f"Error executing security action '{action}': {str(e)}")
    
    def escalate_security_violation(
        self,
        agent_id: str,
        violation_type: ThreatType,
        severity: SafetyLevel,
        description: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Escalate security violations to higher authorities.
        
        Args:
            agent_id: ID of the agent violating security
            violation_type: Type of security violation
            severity: Severity level of the violation
            description: Description of the violation
            details: Optional dictionary with additional details
        """
        # Create escalation details
        escalation_details = {
            "agent_id": agent_id,
            "violation_type": violation_type.name,
            "severity": severity.name,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        
        # Log escalation
        self.log_security_event(
            event_type="SECURITY_VIOLATION_ESCALATED",
            severity=severity,
            agent_id=agent_id,
            description=f"Security violation escalated: {description}",
            threat_type=violation_type,
            details=escalation_details
        )
        
        # In a real implementation, this would send notifications to security teams
        # or trigger other escalation mechanisms
        escalation_recipients = self.config.get("escalation_recipients", [])
        if escalation_recipients:
            self.logger.info(
                f"Security violation escalated to: {', '.join(escalation_recipients)}"
            )
    
    def quarantine_agent(self, agent_id: str, reason: str) -> None:
        """
        Quarantine an agent that violates security policies.
        
        Args:
            agent_id: ID of the agent to quarantine
            reason: Reason for quarantine
        """
        # Log quarantine event
        self.log_security_event(
            event_type="AGENT_QUARANTINED",
            severity=SafetyLevel.HIGH,
            agent_id=agent_id,
            description=f"Agent quarantined: {reason}",
            threat_type=ThreatType.UNAUTHORIZED_ACCESS,
            details={
                "agent_id": agent_id,
                "reason": reason,
                "quarantine_time": datetime.now().isoformat()
            }
        )
        
        # In a real implementation, this would update the agent's status in a database
        # or take other measures to restrict the agent's activities
        self.logger.warning(f"Agent {agent_id} quarantined: {reason}")
        
        # Add to quarantined agents list
        if "quarantined_agents" not in self.config:
            self.config["quarantined_agents"] = {}
        
        self.config["quarantined_agents"][agent_id] = {
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
    
    def _restrict_agent(self, agent_id: str) -> None:
        """
        Restrict an agent's capabilities due to security violations.
        
        Args:
            agent_id: ID of the agent to restrict
        """
        # Log restriction event
        self.log_security_event(
            event_type="AGENT_RESTRICTED",
            severity=SafetyLevel.MEDIUM,
            agent_id=agent_id,
            description="Agent capabilities restricted due to security violations",
            threat_type=ThreatType.UNAUTHORIZED_ACCESS,
            details={
                "agent_id": agent_id,
                "restriction_time": datetime.now().isoformat()
            }
        )
        
        # In a real implementation, this would update the agent's permissions
        # or take other measures to restrict the agent's activities
        self.logger.warning(f"Agent {agent_id} capabilities restricted")
        
        # Add to restricted agents list
        if "restricted_agents" not in self.config:
            self.config["restricted_agents"] = {}
        
        self.config["restricted_agents"][agent_id] = {
            "timestamp": datetime.now().isoformat()
        }
    
    def is_agent_quarantined(self, agent_id: str) -> bool:
        """
        Check if an agent is quarantined.
        
        Args:
            agent_id: ID of the agent to check
            
        Returns:
            True if agent is quarantined, False otherwise
        """
        quarantined_agents = self.config.get("quarantined_agents", {})
        return agent_id in quarantined_agents
    
    def is_agent_restricted(self, agent_id: str) -> bool:
        """
        Check if an agent is restricted.
        
        Args:
            agent_id: ID of the agent to check
            
        Returns:
            True if agent is restricted, False otherwise
        """
        restricted_agents = self.config.get("restricted_agents", {})
        return agent_id in restricted_agents
