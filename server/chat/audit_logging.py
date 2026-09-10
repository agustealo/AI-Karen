"""
Audit logging and security monitoring for AI-Karen production chat system.
"""

import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
from pathlib import Path

from .security import ThreatLevel, SecurityLevel
# from .models import ChatConversation, ChatMessage, ChatProvider  # Commented out as these may not exist yet

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    # Authentication events
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    LOGIN_FAILED = "login_failed"
    PASSWORD_CHANGE = "password_change"
    PASSWORD_RESET = "password_reset"
    TWO_FACTOR_ENABLED = "two_factor_enabled"
    TWO_FACTOR_DISABLED = "two_factor_disabled"
    
    # Authorization events
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REMOVED = "role_removed"
    
    # Chat events
    MESSAGE_SENT = "message_sent"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_DELETED = "message_deleted"
    CONVERSATION_CREATED = "conversation_created"
    CONVERSATION_DELETED = "conversation_deleted"
    CONVERSATION_SHARED = "conversation_shared"
    
    # File events
    FILE_UPLOADED = "file_uploaded"
    FILE_DOWNLOADED = "file_downloaded"
    FILE_DELETED = "file_deleted"
    
    # Security events
    SECURITY_VIOLATION = "security_violation"
    THREAT_DETECTED = "threat_detected"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    ABUSE_DETECTED = "abuse_detected"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    BAN_ISSUED = "ban_issued"
    BAN_LIFTED = "ban_lifted"
    
    # System events
    SYSTEM_ERROR = "system_error"
    SYSTEM_WARNING = "system_warning"
    CONFIGURATION_CHANGE = "configuration_change"
    BACKUP_COMPLETED = "backup_completed"
    BACKUP_FAILED = "backup_failed"


class AuditSeverity(Enum):
    """Severity levels for audit events."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """Audit event record."""
    event_type: AuditEventType
    severity: AuditSeverity
    user_id: Optional[str] = field(default=None)
    ip_address: Optional[str] = field(default=None)
    session_id: Optional[str] = field(default=None)
    resource_id: Optional[str] = field(default=None)
    resource_type: Optional[str] = field(default=None)
    details: Dict[str, Any] = field(default_factory=dict)
    threat_level: Optional[ThreatLevel] = field(default=None)
    action_taken: Optional[str] = field(default=None)
    outcome: Optional[str] = field(default=None)
    metadata: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SecurityAlert:
    """Security alert record."""
    alert_type: str
    severity: AuditSeverity
    description: str
    threat_level: ThreatLevel
    user_id: Optional[str] = field(default=None)
    ip_address: Optional[str] = field(default=None)
    details: Dict[str, Any] = field(default_factory=dict)
    status: str = field(default="active")  # active, resolved, false_positive
    resolved_at: Optional[datetime] = field(default=None)
    resolved_by: Optional[str] = field(default=None)
    resolution_notes: Optional[str] = field(default=None)
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ComplianceReport:
    """Compliance report record."""
    report_type: str
    period_start: datetime
    period_end: datetime
    total_events: int = field(default=0)
    events_by_type: Dict[str, int] = field(default_factory=dict)
    events_by_severity: Dict[str, int] = field(default_factory=dict)
    top_users: List[Dict[str, Any]] = field(default_factory=list)
    top_ips: List[Dict[str, Any]] = field(default_factory=list)
    threats_detected: List[Dict[str, Any]] = field(default_factory=list)
    compliance_score: float = field(default=100.0)
    recommendations: List[str] = field(default_factory=list)
    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = field(default_factory=datetime.now)


class AuditLogger:
    """Audit logging system."""
    
    def __init__(self, log_file_path: Optional[str] = None):
        self.log_file_path = log_file_path or "logs/chat_audit.log"
        self.events: List[AuditEvent] = []
        self.alerts: List[SecurityAlert] = []
        self._lock = asyncio.Lock()
        
        # Ensure log directory exists
        Path(self.log_file_path).parent.mkdir(parents=True, exist_ok=True)
    
    async def log_event(
        self,
        event_type: AuditEventType,
        severity: AuditSeverity,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        session_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        threat_level: Optional[ThreatLevel] = None,
        action_taken: Optional[str] = None,
        outcome: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log an audit event."""
        async with self._lock:
            event = AuditEvent(
                event_type=event_type,
                severity=severity,
                user_id=user_id,
                ip_address=ip_address,
                session_id=session_id,
                resource_id=resource_id,
                resource_type=resource_type,
                details=details or {},
                threat_level=threat_level,
                action_taken=action_taken,
                outcome=outcome,
                metadata=metadata or {}
            )
            
            self.events.append(event)
            
            # Write to file
            await self._write_event_to_file(event)
            
            # Log to standard logger
            log_message = f"Audit: {event_type.value} - {severity.value.upper()}"
            if user_id:
                log_message += f" - User: {user_id}"
            if ip_address:
                log_message += f" - IP: {ip_address}"
            
            if severity == AuditSeverity.CRITICAL:
                logger.critical(log_message)
            elif severity == AuditSeverity.HIGH:
                logger.error(log_message)
            elif severity == AuditSeverity.MEDIUM:
                logger.warning(log_message)
            else:
                logger.info(log_message)
    
    async def log_security_alert(
        self,
        alert_type: str,
        severity: AuditSeverity,
        description: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        threat_level: ThreatLevel = ThreatLevel.MEDIUM
    ):
        """Log a security alert."""
        async with self._lock:
            alert = SecurityAlert(
                alert_type=alert_type,
                severity=severity,
                description=description,
                threat_level=threat_level,
                user_id=user_id,
                ip_address=ip_address,
                details=details or {}
            )
            
            self.alerts.append(alert)
            
            # Write to file
            await self._write_alert_to_file(alert)
            
            # Log to standard logger
            log_message = f"Security Alert: {alert_type} - {severity.value.upper()}"
            if user_id:
                log_message += f" - User: {user_id}"
            if ip_address:
                log_message += f" - IP: {ip_address}"
            
            if severity == AuditSeverity.CRITICAL:
                logger.critical(log_message)
            elif severity == AuditSeverity.HIGH:
                logger.error(log_message)
            elif severity == AuditSeverity.MEDIUM:
                logger.warning(log_message)
            else:
                logger.info(log_message)
    
    async def resolve_alert(
        self,
        alert_id: str,
        resolved_by: str,
        resolution_notes: str,
        status: str = "resolved"
    ):
        """Resolve a security alert."""
        async with self._lock:
            for alert in self.alerts:
                if alert.alert_id == alert_id:
                    alert.status = status
                    alert.resolved_at = datetime.now()
                    alert.resolved_by = resolved_by
                    alert.resolution_notes = resolution_notes
                    
                    # Update file
                    await self._write_alert_to_file(alert)
                    
                    logger.info(f"Security alert {alert_id} resolved by {resolved_by}")
                    break
    
    async def _write_event_to_file(self, event: AuditEvent):
        """Write audit event to file."""
        try:
            event_data = asdict(event)
            # Convert datetime to string for JSON serialization
            event_data['timestamp'] = event.timestamp.isoformat()
            
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event_data) + '\n')
                
        except Exception as e:
            logger.error(f"Failed to write audit event to file: {e}")
    
    async def _write_alert_to_file(self, alert: SecurityAlert):
        """Write security alert to file."""
        try:
            alert_file_path = self.log_file_path.replace('.log', '_alerts.log')
            alert_data = asdict(alert)
            
            # Convert datetime to string for JSON serialization
            alert_data['timestamp'] = alert.timestamp.isoformat()
            if alert.resolved_at:
                alert_data['resolved_at'] = alert.resolved_at.isoformat()
            
            with open(alert_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(alert_data) + '\n')
                
        except Exception as e:
            logger.error(f"Failed to write security alert to file: {e}")
    
    def get_events(
        self,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """Get filtered audit events."""
        filtered_events = self.events
        
        if event_type:
            filtered_events = [e for e in filtered_events if e.event_type == event_type]
        
        if user_id:
            filtered_events = [e for e in filtered_events if e.user_id == user_id]
        
        if start_time:
            filtered_events = [e for e in filtered_events if e.timestamp >= start_time]
        
        if end_time:
            filtered_events = [e for e in filtered_events if e.timestamp <= end_time]
        
        # Sort by timestamp (newest first) and limit
        filtered_events.sort(key=lambda x: str(x.timestamp or ""), reverse=True)
        return filtered_events[:limit]
    
    def get_alerts(
        self,
        alert_type: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        status: Optional[str] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[SecurityAlert]:
        """Get filtered security alerts."""
        filtered_alerts = self.alerts
        
        if alert_type:
            filtered_alerts = [a for a in filtered_alerts if a.alert_type == alert_type]
        
        if severity:
            filtered_alerts = [a for a in filtered_alerts if a.severity == severity]
        
        if status:
            filtered_alerts = [a for a in filtered_alerts if a.status == status]
        
        if user_id:
            filtered_alerts = [a for a in filtered_alerts if a.user_id == user_id]
        
        if start_time:
            filtered_alerts = [a for a in filtered_alerts if a.timestamp >= start_time]
        
        if end_time:
            filtered_alerts = [a for a in filtered_alerts if a.timestamp <= end_time]
        
        # Sort by timestamp (newest first) and limit
        filtered_alerts.sort(key=lambda x: x.timestamp, reverse=True)
        return filtered_alerts[:limit]
    
    def get_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get audit statistics."""
        events = self.get_events(start_time=start_time, end_time=end_time)
        alerts = self.get_alerts(start_time=start_time, end_time=end_time)
        
        stats = {
            "total_events": len(events),
            "total_alerts": len(alerts),
            "events_by_type": {},
            "events_by_severity": {},
            "alerts_by_type": {},
            "alerts_by_severity": {},
            "unique_users": len(set(e.user_id for e in events if e.user_id)),
            "unique_ips": len(set(e.ip_address for e in events if e.ip_address)),
            "resolved_alerts": len([a for a in alerts if a.status == "resolved"]),
            "active_alerts": len([a for a in alerts if a.status == "active"])
        }
        
        # Event type statistics
        for event in events:
            event_type = event.event_type.value
            stats["events_by_type"][event_type] = stats["events_by_type"].get(event_type, 0) + 1
        
        # Event severity statistics
        for event in events:
            severity = event.severity.value
            stats["events_by_severity"][severity] = stats["events_by_severity"].get(severity, 0) + 1
        
        # Alert type statistics
        for alert in alerts:
            alert_type = alert.alert_type
            stats["alerts_by_type"][alert_type] = stats["alerts_by_type"].get(alert_type, 0) + 1
        
        # Alert severity statistics
        for alert in alerts:
            severity = alert.severity.value
            stats["alerts_by_severity"][severity] = stats["alerts_by_severity"].get(severity, 0) + 1
        
        return stats
    
    async def generate_compliance_report(
        self,
        report_type: str = "security",
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None
    ) -> ComplianceReport:
        """Generate compliance report."""
        if not period_start:
            period_start = datetime.now() - timedelta(days=30)
        if not period_end:
            period_end = datetime.now()
        
        events = self.get_events(start_time=period_start, end_time=period_end)
        alerts = self.get_alerts(start_time=period_start, end_time=period_end)
        
        # Calculate statistics
        events_by_type = {}
        events_by_severity = {}
        top_users = []
        top_ips = []
        threats_detected = []
        
        # Event type statistics
        for event in events:
            event_type = event.event_type.value
            events_by_type[event_type] = events_by_type.get(event_type, 0) + 1
        
        # Event severity statistics
        for event in events:
            severity = event.severity.value
            events_by_severity[severity] = events_by_severity.get(severity, 0) + 1
        
        # Top users
        user_counts = {}
        for event in events:
            if event.user_id:
                user_counts[event.user_id] = user_counts.get(event.user_id, 0) + 1
        
        top_users = [
            {"user_id": user_id, "count": count}
            for user_id, count in sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        # Top IPs
        ip_counts = {}
        for event in events:
            if event.ip_address:
                ip_counts[event.ip_address] = ip_counts.get(event.ip_address, 0) + 1
        
        top_ips = [
            {"ip_address": ip, "count": count}
            for ip, count in sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        # Threats detected
        for alert in alerts:
            if alert.threat_level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL]:
                threats_detected.append({
                    "alert_id": alert.alert_id,
                    "type": alert.alert_type,
                    "severity": alert.severity.value,
                    "description": alert.description,
                    "timestamp": alert.timestamp.isoformat(),
                    "user_id": alert.user_id,
                    "ip_address": alert.ip_address
                })
        
        # Calculate compliance score
        total_events = len(events)
        critical_events = events_by_severity.get("critical", 0)
        high_events = events_by_severity.get("high", 0)
        medium_events = events_by_severity.get("medium", 0)
        
        # Score calculation (100 = perfect, lower scores for more issues)
        compliance_score = 100.0
        compliance_score -= (critical_events * 10)  # -10 points per critical
        compliance_score -= (high_events * 5)      # -5 points per high
        compliance_score -= (medium_events * 2)     # -2 points per medium
        compliance_score = max(0.0, compliance_score)
        
        # Generate recommendations
        recommendations = []
        if critical_events > 0:
            recommendations.append("Address critical security events immediately")
        if high_events > 5:
            recommendations.append("Review and mitigate high-severity events")
        if len(threats_detected) > 10:
            recommendations.append("Implement additional threat detection measures")
        if compliance_score < 80:
            recommendations.append("Overall security posture needs improvement")
        
        return ComplianceReport(
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            total_events=total_events,
            events_by_type=events_by_type,
            events_by_severity=events_by_severity,
            top_users=top_users,
            top_ips=top_ips,
            threats_detected=threats_detected,
            compliance_score=compliance_score,
            recommendations=recommendations
        )
    
    async def cleanup_old_events(self, days_to_keep: int = 90):
        """Clean up old audit events and alerts."""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        async with self._lock:
            # Clean events
            original_count = len(self.events)
            self.events = [e for e in self.events if e.timestamp >= cutoff_date]
            events_removed = original_count - len(self.events)
            
            # Clean alerts
            original_alert_count = len(self.alerts)
            self.alerts = [a for a in self.alerts if a.timestamp >= cutoff_date]
            alerts_removed = original_alert_count - len(self.alerts)
            
            if events_removed > 0 or alerts_removed > 0:
                logger.info(f"Cleaned up {events_removed} old events and {alerts_removed} old alerts")


class SecurityMonitoringService:
    """Comprehensive security monitoring service."""
    
    def __init__(self, audit_logger: AuditLogger):
        self.audit_logger = audit_logger
        self.monitoring_active = True
        self.alert_thresholds = {
            "failed_logins_per_minute": 5,
            "security_events_per_hour": 10,
            "critical_alerts_per_day": 3,
            "abuse_reports_per_hour": 2
        }
        self._lock = asyncio.Lock()
    
    async def monitor_failed_logins(self, ip_address: str, user_id: Optional[str] = None):
        """Monitor failed login attempts."""
        recent_events = self.audit_logger.get_events(
            event_type=AuditEventType.LOGIN_FAILED,
            start_time=datetime.now() - timedelta(minutes=1)
        )
        
        ip_failures = [e for e in recent_events if e.ip_address == ip_address]
        
        if len(ip_failures) >= self.alert_thresholds["failed_logins_per_minute"]:
            await self.audit_logger.log_security_alert(
                alert_type="brute_force_attack",
                severity=AuditSeverity.HIGH,
                description=f"Multiple failed login attempts from IP: {ip_address}",
                user_id=user_id,
                ip_address=ip_address,
                details={"failure_count": len(ip_failures)},
                threat_level=ThreatLevel.HIGH
            )
    
    async def monitor_security_events(self):
        """Monitor for unusual security event patterns."""
        recent_events = self.audit_logger.get_events(
            start_time=datetime.now() - timedelta(hours=1)
        )
        
        security_events = [e for e in recent_events if e.event_type in [
            AuditEventType.SECURITY_VIOLATION,
            AuditEventType.THREAT_DETECTED,
            AuditEventType.RATE_LIMIT_EXCEEDED,
            AuditEventType.ABUSE_DETECTED
        ]]
        
        if len(security_events) >= self.alert_thresholds["security_events_per_hour"]:
            await self.audit_logger.log_security_alert(
                alert_type="elevated_security_activity",
                severity=AuditSeverity.MEDIUM,
                description=f"High volume of security events detected: {len(security_events)} in last hour",
                details={"event_count": len(security_events)},
                threat_level=ThreatLevel.MEDIUM
            )
    
    async def monitor_critical_alerts(self):
        """Monitor for critical alerts."""
        recent_alerts = self.audit_logger.get_alerts(
            severity=AuditSeverity.CRITICAL,
            start_time=datetime.now() - timedelta(days=1)
        )
        
        if len(recent_alerts) >= self.alert_thresholds["critical_alerts_per_day"]:
            await self.audit_logger.log_security_alert(
                alert_type="critical_alert_threshold",
                severity=AuditSeverity.CRITICAL,
                description=f"Critical alert threshold exceeded: {len(recent_alerts)} in last day",
                details={"alert_count": len(recent_alerts)},
                threat_level=ThreatLevel.CRITICAL
            )
    
    async def monitor_abuse_reports(self):
        """Monitor for abuse reports."""
        recent_events = self.audit_logger.get_events(
            event_type=AuditEventType.ABUSE_DETECTED,
            start_time=datetime.now() - timedelta(hours=1)
        )
        
        if len(recent_events) >= self.alert_thresholds["abuse_reports_per_hour"]:
            await self.audit_logger.log_security_alert(
                alert_type="abuse_spike",
                severity=AuditSeverity.HIGH,
                description=f"Abuse report spike detected: {len(recent_events)} in last hour",
                details={"abuse_count": len(recent_events)},
                threat_level=ThreatLevel.HIGH
            )
    
    async def start_monitoring(self):
        """Start security monitoring."""
        self.monitoring_active = True
        
        # Start monitoring tasks
        asyncio.create_task(self._monitoring_loop())
        
        logger.info("Security monitoring started")
    
    async def stop_monitoring(self):
        """Stop security monitoring."""
        self.monitoring_active = False
        logger.info("Security monitoring stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                # Skip monitor_failed_logins here as it needs IP address parameter
                await self.monitor_security_events()
                await self.monitor_critical_alerts()
                await self.monitor_abuse_reports()
                
                # Wait before next check
                await asyncio.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Continue even if error occurs


# Global audit logger
audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    """Get global audit logger."""
    return audit_logger


def get_security_monitoring_service() -> SecurityMonitoringService:
    """Get security monitoring service."""
    return SecurityMonitoringService(get_audit_logger())


# Convenience functions for common audit operations
async def log_user_login(user_id: str, ip_address: str, session_id: Optional[str] = None):
    """Log successful user login."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.USER_LOGIN,
        severity=AuditSeverity.LOW,
        user_id=user_id,
        ip_address=ip_address,
        session_id=session_id,
        details={"login_method": "password"}
    )


async def log_user_logout(user_id: str, session_id: Optional[str] = None):
    """Log user logout."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.USER_LOGOUT,
        severity=AuditSeverity.LOW,
        user_id=user_id,
        session_id=session_id
    )


async def log_failed_login(ip_address: str, user_id: Optional[str] = None, reason: Optional[str] = None):
    """Log failed login attempt."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.LOGIN_FAILED,
        severity=AuditSeverity.MEDIUM,
        user_id=user_id,
        ip_address=ip_address,
        details={"reason": reason} if reason else {}
    )


async def log_message_sent(
    user_id: str,
    conversation_id: str,
    message_id: str,
    ip_address: Optional[str] = None
):
    """Log message sent."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.MESSAGE_SENT,
        severity=AuditSeverity.LOW,
        user_id=user_id,
        ip_address=ip_address,
        resource_id=message_id,
        resource_type="message",
        details={"conversation_id": conversation_id}
    )


async def log_file_uploaded(
    user_id: str,
    file_id: str,
    filename: str,
    file_size: int,
    ip_address: Optional[str] = None
):
    """Log file upload."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.FILE_UPLOADED,
        severity=AuditSeverity.LOW,
        user_id=user_id,
        ip_address=ip_address,
        resource_id=file_id,
        resource_type="file",
        details={
            "filename": filename,
            "file_size": file_size
        }
    )


async def log_security_violation(
    user_id: Optional[str],
    violation_type: str,
    description: str,
    ip_address: Optional[str] = None,
    threat_level: ThreatLevel = ThreatLevel.MEDIUM,
    details: Optional[Dict[str, Any]] = None
):
    """Log security violation."""
    logger = get_audit_logger()
    await logger.log_event(
        event_type=AuditEventType.SECURITY_VIOLATION,
        severity=AuditSeverity.HIGH if threat_level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL] else AuditSeverity.MEDIUM,
        user_id=user_id,
        ip_address=ip_address,
        details={
            "violation_type": violation_type,
            "description": description,
            **(details or {})
        },
        threat_level=threat_level
    )


async def log_threat_detected(
    threat_type: str,
    description: str,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    threat_level: ThreatLevel = ThreatLevel.MEDIUM,
    details: Optional[Dict[str, Any]] = None
):
    """Log threat detection."""
    logger = get_audit_logger()
    await logger.log_security_alert(
        alert_type=threat_type,
        severity=AuditSeverity.HIGH if threat_level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL] else AuditSeverity.MEDIUM,
        description=description,
        user_id=user_id,
        ip_address=ip_address,
        details=details,
        threat_level=threat_level
    )