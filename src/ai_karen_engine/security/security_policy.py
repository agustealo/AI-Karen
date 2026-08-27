"""
Security Policy and Configuration Management Service.

This service provides comprehensive security policy capabilities including:
- Policy definition and management
- Rule-based access control
- Policy enforcement
- Compliance monitoring
- Policy audit trails
"""

import asyncio
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import select, update, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.core.services.base import BaseService, ServiceConfig
from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.services.audit.audit_logging import (
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    get_audit_logger,
)

logger = get_logger(__name__)


class PolicyType(str, Enum):
    ACCESS_CONTROL = "access_control"
    DATA_PROTECTION = "data_protection"
    ENCRYPTION = "encryption"
    AUTHENTICATION = "authentication"
    SESSION_MANAGEMENT = "session_management"
    AUDIT_LOGGING = "audit_logging"
    COMPLIANCE = "compliance"
    INCIDENT_RESPONSE = "incident_response"
    SECURITY_MONITORING = "security_monitoring"


class PolicyAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_MFA = "require_mfa"
    REQUIRE_DEVICE_TRUST = "require_device_trust"
    LOG_ONLY = "log_only"
    ALERT_ADMIN = "alert_admin"
    BLOCK_IP = "block_ip"
    RATE_LIMIT = "rate_limit"
    ENCRYPT_DATA = "encrypt_data"


class PolicyCondition(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_EQUAL = "greater_equal"
    LESS_EQUAL = "less_equal"
    IN_LIST = "in_list"
    NOT_IN_LIST = "not_in_list"
    REGEX_MATCH = "regex_match"
    TIME_RANGE = "time_range"
    IP_RANGE = "ip_range"
    GEO_LOCATION = "geo_location"


class PolicyStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    EXPIRED = "expired"
    SUPERSEDED = "superseeded"


@dataclass
class PolicyRule:
    rule_id: str
    policy_id: str
    name: str
    description: str
    condition_field: str
    condition_operator: PolicyCondition
    condition_value: Any
    action: PolicyAction
    priority: int = 0
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityPolicy:
    policy_id: str
    name: str
    description: str
    policy_type: PolicyType
    target_resource: str
    target_users: List[str] = field(default_factory=list)
    target_roles: List[str] = field(default_factory=list)
    rules: List[PolicyRule] = field(default_factory=list)
    status: PolicyStatus = PolicyStatus.ACTIVE
    priority: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluation:
    policy_id: str
    rule_id: Optional[str] = None
    user_id: str = ""
    resource: str = ""
    action: PolicyAction = PolicyAction.DENY
    allowed: bool = False
    matched_rules: List[str] = field(default_factory=list)
    evaluation_time: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityPolicyConfig(ServiceConfig):
    enable_policy_enforcement: bool = True
    policy_cache_ttl_minutes: int = 15
    max_policies_per_user: int = 50
    max_rules_per_policy: int = 100
    enable_policy_caching: bool = True
    evaluation_timeout_seconds: int = 5
    parallel_evaluation: bool = True
    enable_compliance_monitoring: bool = True
    compliance_check_interval_hours: int = 24
    auto_policy_updates: bool = True
    enable_policy_audit_logging: bool = True
    audit_retention_days: int = 2555

    def __post_init__(self):
        if not hasattr(self, "name") or not self.name:
            self.name = "security_policy_service"
        if not hasattr(self, "version") or not self.version:
            self.version = "1.0.0"


class SecurityPolicyService(BaseService):
    """Security Policy and Configuration Management Service."""

    def __init__(self, config: Optional[SecurityPolicyConfig] = None):
        super().__init__(config or SecurityPolicyConfig())
        self._initialized = False
        self._lock = asyncio.Lock()
        self._db_session: Optional[AsyncSession] = None
        self._policies: Dict[str, SecurityPolicy] = {}
        self._rules: Dict[str, PolicyRule] = {}
        self._policy_cache: Dict[str, List[PolicyEvaluation]] = {}
        self._compliance_data: Dict[str, Any] = {}
        self._audit_logger = get_audit_logger()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            try:
                self._validate_config()
                await self._load_default_policies()
                self._initialized = True
                logger.info("Security Policy Service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Security Policy Service: {e}")
                raise RuntimeError(f"Security Policy Service initialization failed: {e}")

    def _validate_config(self) -> None:
        if self.config.max_policies_per_user < 10:
            logger.warning("Max policies per user should be at least 10")
        if self.config.max_rules_per_policy < 10:
            logger.warning("Max rules per policy should be at least 10")

    async def _load_default_policies(self) -> None:
        default_policies = [
            SecurityPolicy(
                policy_id="default_access_control",
                name="Default Access Control",
                description="Default access control policy for all users",
                policy_type=PolicyType.ACCESS_CONTROL,
                target_resource="*",
                target_users=["*"],
                target_roles=["*"],
                rules=[
                    PolicyRule(
                        rule_id="require_auth",
                        policy_id="default_access_control",
                        name="Require Authentication",
                        description="All resources require authentication",
                        condition_field="authenticated",
                        condition_operator=PolicyCondition.EQUALS,
                        condition_value=True,
                        action=PolicyAction.ALLOW,
                        priority=100,
                    ),
                    PolicyRule(
                        rule_id="block_unauthenticated",
                        policy_id="default_access_control",
                        name="Block Unauthenticated",
                        description="Block unauthenticated access to sensitive resources",
                        condition_field="authenticated",
                        condition_operator=PolicyCondition.EQUALS,
                        condition_value=False,
                        action=PolicyAction.DENY,
                        priority=90,
                    ),
                ],
            ),
            SecurityPolicy(
                policy_id="default_data_protection",
                name="Default Data Protection",
                description="Default data protection policy",
                policy_type=PolicyType.DATA_PROTECTION,
                target_resource="sensitive_data",
                target_users=["*"],
                target_roles=["*"],
                rules=[
                    PolicyRule(
                        rule_id="encrypt_sensitive_data",
                        policy_id="default_data_protection",
                        name="Encrypt Sensitive Data",
                        description="Encrypt all sensitive data",
                        condition_field="data_classification",
                        condition_operator=PolicyCondition.IN_LIST,
                        condition_value=["confidential", "restricted"],
                        action=PolicyAction.ENCRYPT_DATA,
                        priority=100,
                    ),
                    PolicyRule(
                        rule_id="audit_data_access",
                        policy_id="default_data_protection",
                        name="Audit Data Access",
                        description="Log all access to sensitive data",
                        condition_field="data_classification",
                        condition_operator=PolicyCondition.IN_LIST,
                        condition_value=["confidential", "restricted"],
                        action=PolicyAction.LOG_ONLY,
                        priority=80,
                    ),
                ],
            ),
            SecurityPolicy(
                policy_id="default_session_management",
                name="Default Session Management",
                description="Default session management policy",
                policy_type=PolicyType.SESSION_MANAGEMENT,
                target_resource="session",
                target_users=["*"],
                target_roles=["*"],
                rules=[
                    PolicyRule(
                        rule_id="session_timeout",
                        policy_id="default_session_management",
                        name="Session Timeout",
                        description="Enforce session timeout",
                        condition_field="session_duration_minutes",
                        condition_operator=PolicyCondition.GREATER_THAN,
                        condition_value=480,
                        action=PolicyAction.DENY,
                        priority=90,
                    ),
                    PolicyRule(
                        rule_id="max_sessions",
                        policy_id="default_session_management",
                        name="Max Sessions",
                        description="Limit maximum concurrent sessions",
                        condition_field="concurrent_sessions",
                        condition_operator=PolicyCondition.GREATER_THAN,
                        condition_value=5,
                        action=PolicyAction.DENY,
                        priority=80,
                    ),
                ],
            ),
        ]
        for policy in default_policies:
            self._policies[policy.policy_id] = policy
            for rule in policy.rules:
                self._rules[rule.rule_id] = rule
        logger.info(f"Loaded {len(default_policies)} default security policies")

    def set_db_session(self, session: AsyncSession) -> None:
        self._db_session = session

    async def create_policy(
        self,
        name: str,
        description: str,
        policy_type: PolicyType,
        target_resource: str,
        *,
        target_users: Optional[List[str]] = None,
        target_roles: Optional[List[str]] = None,
        rules: Optional[List[PolicyRule]] = None,
        priority: int = 0,
        created_by: Optional[str] = None,
    ) -> Tuple[Optional[SecurityPolicy], Optional[str]]:
        try:
            if not name or not description or not policy_type or not target_resource:
                return None, "Missing required fields"
            user_policies = len([p for p in self._policies.values() if p.created_by == created_by])
            if user_policies >= self.config.max_policies_per_user:
                return None, f"Maximum policies per user ({self.config.max_policies_per_user}) reached"
            policy = SecurityPolicy(
                policy_id=secrets.token_urlsafe(32),
                name=name,
                description=description,
                policy_type=policy_type,
                target_resource=target_resource,
                target_users=target_users or ["*"],
                target_roles=target_roles or ["*"],
                rules=rules or [],
                priority=priority,
                created_by=created_by,
            )
            self._policies[policy.policy_id] = policy
            for rule in policy.rules:
                self._rules[rule.rule_id] = rule
            self._audit_logger.log_audit_event({
                "event_type": AuditEventType.SECURITY_EVENT,
                "severity": AuditSeverity.INFO,
                "message": f"Security policy created: {policy.policy_id}",
                "metadata": {
                    "policy_id": policy.policy_id,
                    "policy_name": policy.name,
                    "policy_type": policy.policy_type.value,
                    "created_by": created_by,
                },
            })
            return policy, None
        except Exception as e:
            logger.error(f"Error creating security policy: {e}")
            return None, str(e)

    async def update_policy(
        self,
        policy_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        rules: Optional[List[PolicyRule]] = None,
        status: Optional[PolicyStatus] = None,
    ) -> Tuple[Optional[SecurityPolicy], Optional[str]]:
        try:
            policy = self._policies.get(policy_id)
            if not policy:
                return None, f"Policy not found: {policy_id}"
            if name is not None:
                policy.name = name
            if description is not None:
                policy.description = description
            if status is not None:
                policy.status = status
            if rules is not None:
                policy.rules = rules
            policy.updated_at = datetime.utcnow()
            for rule in policy.rules:
                self._rules[rule.rule_id] = rule
            return policy, None
        except Exception as e:
            logger.error(f"Error updating security policy: {e}")
            return None, str(e)

    async def delete_policy(self, policy_id: str) -> bool:
        try:
            policy = self._policies.get(policy_id)
            if not policy:
                return False
            del self._policies[policy_id]
            for rule in policy.rules:
                self._rules.pop(rule.rule_id, None)
            for key in [k for k in self._policy_cache if k.startswith(f"{policy_id}:")]:
                del self._policy_cache[key]
            return True
        except Exception as e:
            logger.error(f"Error deleting security policy: {e}")
            return False

    async def add_policy_rule(
        self,
        policy_id: str,
        name: str,
        description: str,
        condition_field: str,
        condition_operator: PolicyCondition,
        condition_value: Any,
        action: PolicyAction,
        *,
        priority: int = 0,
    ) -> Tuple[Optional[PolicyRule], Optional[str]]:
        try:
            policy = self._policies.get(policy_id)
            if not policy:
                return None, f"Policy not found: {policy_id}"
            if len(policy.rules) >= self.config.max_rules_per_policy:
                return None, f"Maximum rules per policy ({self.config.max_rules_per_policy}) reached"
            rule = PolicyRule(
                rule_id=secrets.token_urlsafe(32),
                policy_id=policy_id,
                name=name,
                description=description,
                condition_field=condition_field,
                condition_operator=condition_operator,
                condition_value=condition_value,
                action=action,
                priority=priority,
            )
            policy.rules.append(rule)
            policy.updated_at = datetime.utcnow()
            self._rules[rule.rule_id] = rule
            return rule, None
        except Exception as e:
            logger.error(f"Error adding policy rule: {e}")
            return None, str(e)

    async def evaluate_policy(
        self,
        user_id: str,
        resource: str,
        context: Dict[str, Any],
    ) -> PolicyEvaluation:
        try:
            cache_key = f"{user_id}:{resource}"
            if cache_key in self._policy_cache and self._policy_cache[cache_key]:
                return self._policy_cache[cache_key][0]
            applicable_policies = [
                policy for policy in self._policies.values()
                if self._policy_applies(policy, user_id, resource, context)
            ]
            applicable_policies.sort(key=lambda p: p.priority, reverse=True)
            evaluations = [
                await self._evaluate_policy_rules(policy, user_id, resource, context)
                for policy in applicable_policies
            ]
            self._policy_cache[cache_key] = evaluations
            for evaluation in evaluations:
                if evaluation.action == PolicyAction.ALLOW:
                    return evaluation
            if evaluations:
                return evaluations[0]
            return PolicyEvaluation(
                policy_id="default",
                user_id=user_id,
                resource=resource,
                action=PolicyAction.ALLOW,
                allowed=True,
            )
        except Exception as e:
            logger.error(f"Error evaluating policy: {e}")
            return PolicyEvaluation(
                policy_id="error",
                user_id=user_id,
                resource=resource,
                action=PolicyAction.DENY,
                allowed=False,
                metadata={"error": str(e)},
            )

    async def _evaluate_policy_rules(
        self,
        policy: SecurityPolicy,
        user_id: str,
        resource: str,
        context: Dict[str, Any],
    ) -> PolicyEvaluation:
        matched_rules = []
        for rule in sorted(policy.rules, key=lambda r: r.priority, reverse=True):
            if not rule.is_active:
                continue
            if self._evaluate_rule_condition(rule, context):
                matched_rules.append(rule.rule_id)
                if rule.action == PolicyAction.DENY:
                    return PolicyEvaluation(
                        policy_id=policy.policy_id,
                        rule_id=rule.rule_id,
                        user_id=user_id,
                        resource=resource,
                        action=rule.action,
                        allowed=False,
                        matched_rules=[rule.rule_id],
                    )
        return PolicyEvaluation(
            policy_id=policy.policy_id,
            user_id=user_id,
            resource=resource,
            action=PolicyAction.ALLOW,
            allowed=True,
            matched_rules=matched_rules,
        )

    def _evaluate_rule_condition(self, rule: PolicyRule, context: Dict[str, Any]) -> bool:
        try:
            field_value = context.get(rule.condition_field)
            if field_value is None:
                return False
            if rule.condition_operator == PolicyCondition.EQUALS:
                return field_value == rule.condition_value
            if rule.condition_operator == PolicyCondition.NOT_EQUALS:
                return field_value != rule.condition_value
            if rule.condition_operator == PolicyCondition.CONTAINS:
                return rule.condition_value in field_value if isinstance(field_value, (list, str)) else str(rule.condition_value) in str(field_value)
            if rule.condition_operator == PolicyCondition.NOT_CONTAINS:
                return rule.condition_value not in field_value if isinstance(field_value, (list, str)) else str(rule.condition_value) not in str(field_value)
            if rule.condition_operator == PolicyCondition.GREATER_THAN:
                return float(field_value) > float(rule.condition_value)
            if rule.condition_operator == PolicyCondition.LESS_THAN:
                return float(field_value) < float(rule.condition_value)
            if rule.condition_operator == PolicyCondition.GREATER_EQUAL:
                return float(field_value) >= float(rule.condition_value)
            if rule.condition_operator == PolicyCondition.LESS_EQUAL:
                return float(field_value) <= float(rule.condition_value)
            if rule.condition_operator == PolicyCondition.IN_LIST:
                return field_value in rule.condition_value if isinstance(rule.condition_value, list) else field_value == rule.condition_value
            if rule.condition_operator == PolicyCondition.NOT_IN_LIST:
                return field_value not in rule.condition_value if isinstance(rule.condition_value, list) else field_value != rule.condition_value
            if rule.condition_operator == PolicyCondition.REGEX_MATCH:
                import re
                return bool(re.search(rule.condition_value, str(field_value)))
            logger.warning(f"Unsupported condition operator: {rule.condition_operator}")
            return False
        except (ValueError, TypeError):
            return False
        except Exception as e:
            logger.error(f"Error evaluating rule condition: {e}")
            return False

    def _policy_applies(
        self,
        policy: SecurityPolicy,
        user_id: str,
        resource: str,
        context: Dict[str, Any],
    ) -> bool:
        try:
            if policy.status != PolicyStatus.ACTIVE:
                return False
            if policy.target_resource != "*" and resource != policy.target_resource:
                return False
            if policy.target_users != ["*"] and user_id not in policy.target_users:
                return False
            if policy.target_roles != ["*"] and "user" not in policy.target_roles:
                return False
            return True
        except Exception as e:
            logger.error(f"Error checking policy applicability: {e}")
            return False

    async def get_policy(self, policy_id: str) -> Optional[SecurityPolicy]:
        return self._policies.get(policy_id)

    async def get_user_policies(self, user_id: str) -> List[SecurityPolicy]:
        return [
            policy for policy in self._policies.values()
            if policy.status == PolicyStatus.ACTIVE
            and (policy.target_users == ["*"] or user_id in policy.target_users)
        ]

    async def get_policy_statistics(self) -> Dict[str, Any]:
        try:
            type_counts: Dict[str, int] = {}
            rule_counts: Dict[str, int] = {}
            status_counts: Dict[str, int] = {}
            for policy in self._policies.values():
                type_counts[policy.policy_type.value] = type_counts.get(policy.policy_type.value, 0) + 1
                rule_counts[policy.policy_id] = len(policy.rules)
                status_counts[policy.status.value] = status_counts.get(policy.status.value, 0) + 1
            return {
                "total_policies": len(self._policies),
                "policies_by_type": type_counts,
                "policies_by_status": status_counts,
                "total_rules": len(self._rules),
                "rules_by_policy": rule_counts,
                "policy_enforcement_enabled": self.config.enable_policy_enforcement,
                "policy_caching_enabled": self.config.enable_policy_caching,
                "compliance_monitoring_enabled": self.config.enable_compliance_monitoring,
            }
        except Exception as e:
            logger.error(f"Error getting policy statistics: {e}")
            return {}

    async def health_check(self) -> bool:
        if not self._initialized:
            return False
        try:
            test_policy, error = await self.create_policy(
                name="Test Policy",
                description="Test policy for health check",
                policy_type=PolicyType.ACCESS_CONTROL,
                target_resource="test_resource",
                created_by="health_check",
            )
            if error or not test_policy:
                return False
            test_rule, error = await self.add_policy_rule(
                policy_id=test_policy.policy_id,
                name="Test Rule",
                description="Test rule for health check",
                condition_field="test_field",
                condition_operator=PolicyCondition.EQUALS,
                condition_value="test_value",
                action=PolicyAction.ALLOW,
            )
            if error or not test_rule:
                return False
            evaluation = await self.evaluate_policy(
                user_id="test_user",
                resource="test_resource",
                context={"test_field": "test_value"},
            )
            if not evaluation.allowed:
                return False
            await self.delete_policy(test_policy.policy_id)
            return True
        except Exception as e:
            logger.error(f"Security Policy Service health check failed: {e}")
            return False

    async def start(self) -> None:
        if not self._initialized:
            await self.initialize()
        logger.info("Security Policy Service started successfully")

    async def stop(self) -> None:
        if not self._initialized:
            return
        self._policies.clear()
        self._rules.clear()
        self._policy_cache.clear()
        self._compliance_data.clear()
        self._initialized = False
        logger.info("Security Policy Service stopped successfully")


__all__ = [
    "SecurityPolicyService",
    "SecurityPolicyConfig",
    "SecurityPolicy",
    "PolicyRule",
    "PolicyEvaluation",
    "PolicyType",
    "PolicyAction",
    "PolicyCondition",
    "PolicyStatus",
]
