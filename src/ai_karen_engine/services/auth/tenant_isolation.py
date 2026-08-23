"""
Multi-Tenant Data Isolation Service - Phase 4.1.c
Implements tenant filtering at SQL layers with security incident logging.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Union, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    from sqlalchemy import and_, or_, select, update, delete
    from sqlalchemy.ext.asyncio import AsyncSession
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

logger = logging.getLogger(__name__)

class TenantAccessLevel(str, Enum):
    """Tenant access levels for data isolation"""
    STRICT = "strict"      # Complete isolation - no cross-tenant access
    SHARED = "shared"      # Controlled sharing with explicit permissions
    PUBLIC = "public"      # Public data accessible to all tenants

class SecurityIncidentType(str, Enum):
    """Types of security incidents for logging"""
    CROSS_TENANT_ACCESS_ATTEMPT = "cross_tenant_access_attempt"
    UNAUTHORIZED_DATA_QUERY = "unauthorized_data_query"
    TENANT_FILTER_BYPASS = "tenant_filter_bypass"
    INVALID_TENANT_ID = "invalid_tenant_id"
    PERMISSION_ESCALATION = "permission_escalation"

@dataclass
class TenantContext:
    """Tenant context for data access"""
    tenant_id: str
    user_id: str
    org_id: Optional[str] = None
    access_level: TenantAccessLevel = TenantAccessLevel.STRICT
    allowed_tenants: Set[str] = None  # For shared access scenarios
    
    def __post_init__(self):
        if self.allowed_tenants is None:
            self.allowed_tenants = {self.tenant_id}

@dataclass
class SecurityIncident:
    """Security incident record"""
    incident_type: SecurityIncidentType
    tenant_context: TenantContext
    attempted_access: Dict[str, Any]
    timestamp: datetime
    correlation_id: Optional[str] = None
    additional_context: Optional[Dict[str, Any]] = None

class TenantIsolationError(Exception):
    """Tenant isolation specific error"""
    pass

class CrossTenantAccessError(TenantIsolationError):
    """Raised when cross-tenant access is attempted"""
    pass

class TenantValidator:
    """Validates tenant access and permissions"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.TenantValidator")
    
    def validate_tenant_id(self, tenant_id: str) -> str:
        """Validate tenant ID format"""
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantIsolationError("Invalid tenant ID: must be non-empty string")
        
        tenant_id = tenant_id.strip()
        if not tenant_id:
            raise TenantIsolationError("Invalid tenant ID: cannot be empty")
        
        # Basic format validation - UUID or alphanumeric with hyphens/underscores
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', tenant_id):
            raise TenantIsolationError(f"Invalid tenant ID format: {tenant_id}")
        
        return tenant_id
    
    def validate_user_id(self, user_id: str) -> str:
        """Validate user ID format"""
        if not user_id or not isinstance(user_id, str):
            raise TenantIsolationError("Invalid user ID: must be non-empty string")
        
        user_id = user_id.strip()
        if not user_id:
            raise TenantIsolationError("Invalid user ID: cannot be empty")
        
        return user_id
    
    def validate_tenant_context(self, context: TenantContext) -> TenantContext:
        """Validate complete tenant context"""
        context.tenant_id = self.validate_tenant_id(context.tenant_id)
        context.user_id = self.validate_user_id(context.user_id)
        
        if context.org_id:
            context.org_id = self.validate_tenant_id(context.org_id)
        
        # Ensure tenant_id is in allowed_tenants
        if context.tenant_id not in context.allowed_tenants:
            context.allowed_tenants.add(context.tenant_id)
        
        return context
    
    def check_tenant_access(
        self, 
        context: TenantContext, 
        target_tenant_id: str,
        resource_type: str = "data"
    ) -> bool:
        """Check if tenant has access to target tenant's data"""
        target_tenant_id = self.validate_tenant_id(target_tenant_id)
        
        # Strict isolation - only own tenant
        if context.access_level == TenantAccessLevel.STRICT:
            return target_tenant_id == context.tenant_id
        
        # Shared access - check allowed tenants
        if context.access_level == TenantAccessLevel.SHARED:
            return target_tenant_id in context.allowed_tenants
        
        # Public access - all tenants allowed
        if context.access_level == TenantAccessLevel.PUBLIC:
            return True
        
        return False

class SecurityIncidentLogger:
    """Logs security incidents for audit purposes"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.SecurityIncidentLogger")
    
    def log_incident(self, incident: SecurityIncident):
        """Log security incident with structured data"""
        incident_data = {
            "incident_type": incident.incident_type.value,
            "tenant_id": incident.tenant_context.tenant_id,
            "user_id": incident.tenant_context.user_id,
            "org_id": incident.tenant_context.org_id,
            "access_level": incident.tenant_context.access_level.value,
            "attempted_access": incident.attempted_access,
            "timestamp": incident.timestamp.isoformat(),
            "correlation_id": incident.correlation_id,
            "additional_context": incident.additional_context or {}
        }
        
        self.logger.warning(
            f"Security incident: {incident.incident_type.value}",
            extra={
                "security_incident": True,
                **incident_data
            }
        )
        
        # In production, this could also send to SIEM or security monitoring system
        self._send_to_security_monitoring(incident_data)
    
    def _send_to_security_monitoring(self, incident_data: Dict[str, Any]):
        """Send incident to security monitoring system (placeholder)"""
        # This would integrate with actual security monitoring in production
        pass

class VectorStoreTenantFilter:
    """Handles tenant filtering for vector store operations."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.VectorStoreTenantFilter")
        self.validator = TenantValidator()
        self.incident_logger = SecurityIncidentLogger()
    
    def create_tenant_filter(self, context: TenantContext) -> Dict[str, Any]:
        """Create vector store filter for tenant isolation"""
        validated_context = self.validator.validate_tenant_context(context)
        
        # Create filter based on access level
        if validated_context.access_level == TenantAccessLevel.STRICT:
            return {
                "tenant_id": validated_context.tenant_id,
                "user_id": validated_context.user_id
            }
        elif validated_context.access_level == TenantAccessLevel.SHARED:
            return {
                "tenant_id": {"$in": list(validated_context.allowed_tenants)},
                "user_id": validated_context.user_id
            }
        else:  # PUBLIC
            return {
                "user_id": validated_context.user_id
            }
    
    def validate_vector_query(
        self, 
        context: TenantContext, 
        query_filter: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Validate and enhance vector query with tenant filters"""
        try:
            validated_context = self.validator.validate_tenant_context(context)
            
            # Check if query attempts to access other tenants
            query_tenant_id = query_filter.get("tenant_id")
            if query_tenant_id and not self.validator.check_tenant_access(
                validated_context, query_tenant_id, "vector_data"
            ):
                # Log security incident
                incident = SecurityIncident(
                    incident_type=SecurityIncidentType.CROSS_TENANT_ACCESS_ATTEMPT,
                    tenant_context=validated_context,
                    attempted_access={
                        "query_filter": query_filter,
                        "attempted_tenant_id": query_tenant_id,
                        "resource_type": "vector_data"
                    },
                    timestamp=datetime.utcnow(),
                    correlation_id=correlation_id
                )
                self.incident_logger.log_incident(incident)
                
                raise CrossTenantAccessError(
                    f"Cross-tenant access denied: {validated_context.tenant_id} -> {query_tenant_id}"
                )
            
            # Create secure filter
            tenant_filter = self.create_tenant_filter(validated_context)
            
            # Merge with existing filter
            secure_filter = {**query_filter, **tenant_filter}
            
            return secure_filter
            
        except TenantIsolationError:
            raise
        except Exception as e:
            self.logger.error(f"Vector query validation failed: {e}")
            raise TenantIsolationError(f"Query validation failed: {e}")

class SQLTenantFilter:
    """Handles tenant filtering for SQL operations"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.SQLTenantFilter")
        self.validator = TenantValidator()
        self.incident_logger = SecurityIncidentLogger()
    
    def create_tenant_conditions(self, context: TenantContext, table_alias=None):
        """Create SQL conditions for tenant isolation"""
        if not SQLALCHEMY_AVAILABLE:
            raise TenantIsolationError("SQLAlchemy not available for SQL filtering")
        
        validated_context = self.validator.validate_tenant_context(context)
        
        # Determine table prefix
        prefix = f"{table_alias}." if table_alias else ""
        
        conditions = []
        
        # Tenant ID condition
        if validated_context.access_level == TenantAccessLevel.STRICT:
            # Use text() for raw SQL conditions since we don't have table objects
            from sqlalchemy import text
            conditions.append(text(f"{prefix}tenant_id = :tenant_id"))
            conditions.append(text(f"{prefix}user_id = :user_id"))
        elif validated_context.access_level == TenantAccessLevel.SHARED:
            from sqlalchemy import text
            tenant_list = "','".join(validated_context.allowed_tenants)
            conditions.append(text(f"{prefix}tenant_id IN ('{tenant_list}')"))
            conditions.append(text(f"{prefix}user_id = :user_id"))
        # For PUBLIC access, only filter by user_id
        else:
            from sqlalchemy import text
            conditions.append(text(f"{prefix}user_id = :user_id"))
        
        return and_(*conditions) if len(conditions) > 1 else conditions[0]
    
    def get_query_parameters(self, context: TenantContext) -> Dict[str, Any]:
        """Get parameters for SQL query"""
        validated_context = self.validator.validate_tenant_context(context)
        
        params = {
            "user_id": validated_context.user_id,
            "tenant_id": validated_context.tenant_id
        }
        
        if validated_context.org_id:
            params["org_id"] = validated_context.org_id
        
        return params
    
    def validate_sql_query(
        self,
        context: TenantContext,
        query_conditions: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> bool:
        """Validate SQL query for tenant isolation compliance"""
        try:
            validated_context = self.validator.validate_tenant_context(context)
            
            # Check for potential cross-tenant access
            query_tenant_id = query_conditions.get("tenant_id")
            if query_tenant_id and not self.validator.check_tenant_access(
                validated_context, query_tenant_id, "sql_data"
            ):
                # Log security incident
                incident = SecurityIncident(
                    incident_type=SecurityIncidentType.UNAUTHORIZED_DATA_QUERY,
                    tenant_context=validated_context,
                    attempted_access={
                        "query_conditions": query_conditions,
                        "attempted_tenant_id": query_tenant_id,
                        "resource_type": "sql_data"
                    },
                    timestamp=datetime.utcnow(),
                    correlation_id=correlation_id
                )
                self.incident_logger.log_incident(incident)
                
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"SQL query validation failed: {e}")
            return False

class TenantIsolationService:
    """Main service for multi-tenant data isolation"""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.TenantIsolationService")
        self.validator = TenantValidator()
        self.vector_filter = VectorStoreTenantFilter()
        self.sql_filter = SQLTenantFilter()
        self.incident_logger = SecurityIncidentLogger()
    
    def create_tenant_context(
        self,
        tenant_id: str,
        user_id: str,
        org_id: Optional[str] = None,
        access_level: TenantAccessLevel = TenantAccessLevel.STRICT,
        allowed_tenants: Optional[Set[str]] = None
    ) -> TenantContext:
        """Create and validate tenant context"""
        context = TenantContext(
            tenant_id=tenant_id,
            user_id=user_id,
            org_id=org_id,
            access_level=access_level,
            allowed_tenants=allowed_tenants
        )
        
        return self.validator.validate_tenant_context(context)
    
    def filter_vector_query(
        self,
        context: TenantContext,
        query_filter: Dict[str, Any],
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Apply tenant filtering to vector store query"""
        return self.vector_filter.validate_vector_query(
            context, query_filter, correlation_id
        )
    
    def filter_sql_query(
        self,
        context: TenantContext,
        table_alias: Optional[str] = None
    ) -> Tuple[Any, Dict[str, Any]]:
        """Apply tenant filtering to SQL query"""
        conditions = self.sql_filter.create_tenant_conditions(context, table_alias)
        parameters = self.sql_filter.get_query_parameters(context)
        
        return conditions, parameters
    
    def validate_data_access(
        self,
        context: TenantContext,
        target_tenant_id: str,
        resource_type: str = "data",
        correlation_id: Optional[str] = None
    ) -> bool:
        """Validate if tenant can access specific data"""
        try:
            has_access = self.validator.check_tenant_access(
                context, target_tenant_id, resource_type
            )
            
            if not has_access:
                # Log security incident
                incident = SecurityIncident(
                    incident_type=SecurityIncidentType.CROSS_TENANT_ACCESS_ATTEMPT,
                    tenant_context=context,
                    attempted_access={
                        "target_tenant_id": target_tenant_id,
                        "resource_type": resource_type
                    },
                    timestamp=datetime.utcnow(),
                    correlation_id=correlation_id
                )
                self.incident_logger.log_incident(incident)
            
            return has_access
            
        except Exception as e:
            self.logger.error(f"Data access validation failed: {e}")
            return False
    
    def log_security_incident(
        self,
        incident_type: SecurityIncidentType,
        context: TenantContext,
        attempted_access: Dict[str, Any],
        correlation_id: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ):
        """Log security incident"""
        incident = SecurityIncident(
            incident_type=incident_type,
            tenant_context=context,
            attempted_access=attempted_access,
            timestamp=datetime.utcnow(),
            correlation_id=correlation_id,
            additional_context=additional_context
        )
        
        self.incident_logger.log_incident(incident)

# Global service instance
_tenant_isolation_service = None

def get_tenant_isolation_service() -> TenantIsolationService:
    """Get or create tenant isolation service instance"""
    global _tenant_isolation_service
    
    if _tenant_isolation_service is None:
        _tenant_isolation_service = TenantIsolationService()
    
    return _tenant_isolation_service

# Utility functions for easy integration
def create_tenant_context(
    tenant_id: str,
    user_id: str,
    org_id: Optional[str] = None,
    access_level: TenantAccessLevel = TenantAccessLevel.STRICT
) -> TenantContext:
    """Create tenant context with validation"""
    service = get_tenant_isolation_service()
    return service.create_tenant_context(tenant_id, user_id, org_id, access_level)

def validate_tenant_access(
    context: TenantContext,
    target_tenant_id: str,
    correlation_id: Optional[str] = None
) -> bool:
    """Validate tenant access with security logging"""
    service = get_tenant_isolation_service()
    return service.validate_data_access(context, target_tenant_id, correlation_id=correlation_id)

# Export public interface
__all__ = [
    "TenantIsolationService",
    "TenantContext",
    "TenantAccessLevel",
    "SecurityIncidentType",
    "TenantIsolationError",
    "CrossTenantAccessError",
    "VectorStoreTenantFilter",
    "SQLTenantFilter",
    "get_tenant_isolation_service",
    "create_tenant_context",
    "validate_tenant_access"
]