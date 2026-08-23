"""
Deployment Configuration Validator

This module provides comprehensive validation and safety checks for deployment
configurations, especially for production environments.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Any
import re
import os

from .deployment_config_manager import (
    ServiceConfig, DeploymentProfile, DeploymentMode, 
    ServiceClassification, ResourceRequirements
)
from .config_manager import resolve_jwt_secret

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Validation issue severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    """Validation issue details"""
    severity: ValidationSeverity
    category: str
    message: str
    service_name: Optional[str] = None
    suggested_fix: Optional[str] = None
    auto_fixable: bool = False


@dataclass
class ValidationResult:
    """Validation result summary"""
    is_valid: bool
    issues: List[ValidationIssue]
    warnings_count: int = 0
    errors_count: int = 0
    critical_count: int = 0
    
    def __post_init__(self):
        """Calculate issue counts"""
        self.warnings_count = sum(1 for issue in self.issues if issue.severity == ValidationSeverity.WARNING)
        self.errors_count = sum(1 for issue in self.issues if issue.severity == ValidationSeverity.ERROR)
        self.critical_count = sum(1 for issue in self.issues if issue.severity == ValidationSeverity.CRITICAL)
        
        # Configuration is valid if no errors or critical issues
        self.is_valid = self.errors_count == 0 and self.critical_count == 0


class DeploymentValidator:
    """
    Comprehensive deployment configuration validator with production safety checks.
    
    Features:
    - Resource allocation validation
    - Security configuration checks
    - Production-specific requirements
    - Service dependency validation
    - Performance optimization checks
    """
    
    def __init__(self):
        """Initialize deployment validator"""
        self.production_requirements = {
            'min_memory_per_service': 32,  # MB
            'max_memory_per_service': 8192,  # MB
            'min_cpu_per_service': 0.05,
            'max_cpu_per_service': 4.0,
            'max_idle_timeout': 3600,  # seconds
            'min_health_check_interval': 30,  # seconds
            'max_health_check_interval': 300,  # seconds
            'max_restart_attempts': 5,
            'min_shutdown_timeout': 5,  # seconds
            'max_shutdown_timeout': 60  # seconds
        }
        
        self.security_requirements = {
            'required_env_vars': [
                'AUTH_JWT_SECRET_KEY',
                'DATABASE_PASSWORD'
            ],
            'forbidden_defaults': {
                'AUTH_JWT_SECRET_KEY': ['change-me', 'default', 'secret', ''],
                'DATABASE_PASSWORD': ['', 'password', 'admin', 'root']
            }
        }
    
    async def validate_deployment_configuration(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> ValidationResult:
        """
        Validate complete deployment configuration.
        
        Args:
            services: Service configurations
            profiles: Deployment profiles
            current_mode: Current deployment mode
            
        Returns:
            ValidationResult with all issues found
        """
        issues = []
        
        # Validate services
        service_issues = await self._validate_services(services)
        issues.extend(service_issues)
        
        # Validate deployment profiles
        profile_issues = await self._validate_profiles(profiles)
        issues.extend(profile_issues)
        
        # Validate service dependencies
        dependency_issues = await self._validate_dependencies(services)
        issues.extend(dependency_issues)
        
        # Validate resource allocation
        resource_issues = await self._validate_resource_allocation(services, profiles, current_mode)
        issues.extend(resource_issues)
        
        # Production-specific validation
        if current_mode == DeploymentMode.PRODUCTION:
            production_issues = await self._validate_production_requirements(services, profiles)
            issues.extend(production_issues)
            
            security_issues = await self._validate_security_configuration()
            issues.extend(security_issues)
        
        # Performance validation
        performance_issues = await self._validate_performance_configuration(services, profiles, current_mode)
        issues.extend(performance_issues)
        
        return ValidationResult(
            is_valid=False,  # Will be calculated in __post_init__
            issues=issues
        )
    
    async def validate_service_config(self, service: ServiceConfig) -> ValidationResult:
        """
        Validate individual service configuration.
        
        Args:
            service: Service configuration to validate
            
        Returns:
            ValidationResult for the service
        """
        issues = []
        
        # Validate resource requirements
        issues.extend(self._validate_service_resources(service))
        
        # Validate timeouts and intervals
        issues.extend(self._validate_service_timeouts(service))
        
        # Validate service naming
        issues.extend(self._validate_service_naming(service))
        
        # Validate classification consistency
        issues.extend(self._validate_service_classification(service))
        
        return ValidationResult(
            is_valid=False,  # Will be calculated in __post_init__
            issues=issues
        )
    
    async def validate_profile_config(self, profile: DeploymentProfile) -> ValidationResult:
        """
        Validate deployment profile configuration.
        
        Args:
            profile: Deployment profile to validate
            
        Returns:
            ValidationResult for the profile
        """
        issues = []
        
        # Validate resource limits
        issues.extend(self._validate_profile_resources(profile))
        
        # Validate classification settings
        issues.extend(self._validate_profile_classifications(profile))
        
        # Validate profile consistency
        issues.extend(self._validate_profile_consistency(profile))
        
        return ValidationResult(
            is_valid=False,  # Will be calculated in __post_init__
            issues=issues
        )
    
    async def get_optimization_suggestions(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> List[ValidationIssue]:
        """
        Get optimization suggestions for current configuration.
        
        Args:
            services: Service configurations
            profiles: Deployment profiles
            current_mode: Current deployment mode
            
        Returns:
            List of optimization suggestions
        """
        suggestions = []
        
        # Resource optimization suggestions
        suggestions.extend(self._suggest_resource_optimizations(services, profiles, current_mode))
        
        # Service consolidation suggestions
        suggestions.extend(self._suggest_service_consolidations(services))
        
        # Performance optimization suggestions
        suggestions.extend(self._suggest_performance_optimizations(services, profiles, current_mode))
        
        # Security optimization suggestions
        suggestions.extend(self._suggest_security_optimizations())
        
        return suggestions
    
    # Private validation methods
    
    async def _validate_services(self, services: Dict[str, ServiceConfig]) -> List[ValidationIssue]:
        """Validate all services"""
        issues = []
        
        for service in services.values():
            service_result = await self.validate_service_config(service)
            issues.extend(service_result.issues)
        
        return issues
    
    async def _validate_profiles(self, profiles: Dict[str, DeploymentProfile]) -> List[ValidationIssue]:
        """Validate all deployment profiles"""
        issues = []
        
        # Check required profiles exist
        required_profiles = ['minimal', 'development', 'production']
        for profile_name in required_profiles:
            if profile_name not in profiles:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="profile_completeness",
                    message=f"Missing recommended deployment profile: {profile_name}",
                    suggested_fix=f"Add {profile_name} profile configuration"
                ))
        
        for profile in profiles.values():
            profile_result = await self.validate_profile_config(profile)
            issues.extend(profile_result.issues)
        
        return issues
    
    async def _validate_dependencies(self, services: Dict[str, ServiceConfig]) -> List[ValidationIssue]:
        """Validate service dependencies"""
        issues = []
        
        # Check for circular dependencies
        def find_circular_deps(service_name: str, visited: Set[str], path: Set[str]) -> Optional[List[str]]:
            if service_name in path:
                return list(path) + [service_name]
            if service_name in visited:
                return None
            
            visited.add(service_name)
            path.add(service_name)
            
            service = services.get(service_name)
            if service:
                for dep in service.dependencies:
                    cycle = find_circular_deps(dep, visited, path)
                    if cycle:
                        return cycle
            
            path.remove(service_name)
            return None
        
        visited = set()
        for service_name in services:
            cycle = find_circular_deps(service_name, visited, set())
            if cycle:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    category="dependency_validation",
                    message=f"Circular dependency detected: {' -> '.join(cycle)}",
                    suggested_fix="Remove circular dependency by restructuring service dependencies"
                ))
        
        # Check for missing dependencies
        for service_name, service in services.items():
            for dep in service.dependencies:
                if dep not in services:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        category="dependency_validation",
                        message=f"Service {service_name} depends on non-existent service: {dep}",
                        service_name=service_name,
                        suggested_fix=f"Add service {dep} or remove dependency"
                    ))
        
        # Check dependency classification consistency
        for service_name, service in services.items():
            for dep in service.dependencies:
                dep_service = services.get(dep)
                if dep_service:
                    # Essential services should not depend on optional/background services
                    if (service.classification == ServiceClassification.ESSENTIAL and
                        dep_service.classification != ServiceClassification.ESSENTIAL):
                        issues.append(ValidationIssue(
                            severity=ValidationSeverity.WARNING,
                            category="dependency_validation",
                            message=f"Essential service {service_name} depends on non-essential service {dep}",
                            service_name=service_name,
                            suggested_fix=f"Consider making {dep} essential or restructuring dependencies"
                        ))
        
        return issues
    
    async def _validate_resource_allocation(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> List[ValidationIssue]:
        """Validate resource allocation"""
        issues = []
        
        current_profile = profiles.get(current_mode.value)
        if not current_profile:
            return issues
        
        # Calculate total resource usage
        total_memory = 0
        total_cpu = 0.0
        enabled_services = []
        
        for service in services.values():
            if (service.enabled and 
                service.classification in current_profile.enabled_classifications):
                total_memory += service.resource_requirements.memory_mb
                total_cpu += service.resource_requirements.cpu_cores
                enabled_services.append(service.name)
        
        # Check against profile limits
        if total_memory > current_profile.max_memory_mb:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="resource_allocation",
                message=f"Total memory usage ({total_memory}MB) exceeds profile limit ({current_profile.max_memory_mb}MB)",
                suggested_fix="Reduce service memory requirements or increase profile limit"
            ))
        
        if total_cpu > current_profile.max_cpu_cores:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="resource_allocation",
                message=f"Total CPU usage ({total_cpu}) exceeds profile limit ({current_profile.max_cpu_cores})",
                suggested_fix="Reduce service CPU requirements or increase profile limit"
            ))
        
        if len(enabled_services) > current_profile.max_services:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="resource_allocation",
                message=f"Number of services ({len(enabled_services)}) exceeds profile limit ({current_profile.max_services})",
                suggested_fix="Disable some services or increase profile limit"
            ))
        
        # Check for resource efficiency
        memory_utilization = (total_memory / current_profile.max_memory_mb) * 100
        if memory_utilization < 20:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="resource_optimization",
                message=f"Low memory utilization ({memory_utilization:.1f}%)",
                suggested_fix="Consider using a smaller deployment profile"
            ))
        elif memory_utilization > 90:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="resource_allocation",
                message=f"High memory utilization ({memory_utilization:.1f}%)",
                suggested_fix="Consider increasing memory limits or optimizing services"
            ))
        
        return issues
    
    async def _validate_production_requirements(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile]
    ) -> List[ValidationIssue]:
        """Validate production-specific requirements"""
        issues = []
        
        production_profile = profiles.get('production')
        if not production_profile:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                category="production_requirements",
                message="Production deployment profile is missing",
                suggested_fix="Add production profile configuration"
            ))
            return issues
        
        # Check production profile settings
        if production_profile.debug_services:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="production_requirements",
                message="Debug services are enabled in production profile",
                suggested_fix="Disable debug services for production"
            ))
        
        if not production_profile.performance_optimized:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="production_requirements",
                message="Performance optimization is not enabled in production profile",
                suggested_fix="Enable performance optimization for production"
            ))
        
        # Check essential services
        essential_services = [s for s in services.values() if s.classification == ServiceClassification.ESSENTIAL]
        if len(essential_services) < 3:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="production_requirements",
                message=f"Only {len(essential_services)} essential services defined",
                suggested_fix="Ensure critical services are marked as essential"
            ))
        
        # Check service configurations for production readiness
        for service in services.values():
            if service.classification == ServiceClassification.ESSENTIAL:
                # Essential services should have reasonable restart attempts
                if service.max_restart_attempts < 3:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        category="production_requirements",
                        message=f"Essential service {service.name} has low restart attempts ({service.max_restart_attempts})",
                        service_name=service.name,
                        suggested_fix="Increase max_restart_attempts for essential services"
                    ))
                
                # Essential services should have health checks
                if service.health_check_interval > 120:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        category="production_requirements",
                        message=f"Essential service {service.name} has infrequent health checks ({service.health_check_interval}s)",
                        service_name=service.name,
                        suggested_fix="Reduce health_check_interval for essential services"
                    ))
        
        return issues
    
    async def _validate_security_configuration(self) -> List[ValidationIssue]:
        """Validate security configuration"""
        issues = []
        
        # Check required environment variables
        for env_var in self.security_requirements['required_env_vars']:
            value = os.getenv(env_var)
            if not value:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.CRITICAL,
                    category="security_configuration",
                    message=f"Required security environment variable {env_var} is not set",
                    suggested_fix=f"Set {env_var} environment variable"
                ))
            else:
                # Check for forbidden default values
                forbidden_values = self.security_requirements['forbidden_defaults'].get(env_var, [])
                if value in forbidden_values:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.CRITICAL,
                        category="security_configuration",
                        message=f"Environment variable {env_var} uses insecure default value",
                        suggested_fix=f"Set a secure value for {env_var}"
                    ))
        
        # Check JWT secret strength
        jwt_secret = resolve_jwt_secret()
        if jwt_secret and len(jwt_secret) < 32:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="security_configuration",
                message="JWT secret is too short (minimum 32 characters recommended)",
                suggested_fix="Use a longer, more secure JWT secret"
            ))
        
        return issues
    
    async def _validate_performance_configuration(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> List[ValidationIssue]:
        """Validate performance configuration"""
        issues = []
        
        # Check for services with excessive resource requirements
        for service in services.values():
            if service.resource_requirements.memory_mb > 2048:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="performance_configuration",
                    message=f"Service {service.name} has high memory requirement ({service.resource_requirements.memory_mb}MB)",
                    service_name=service.name,
                    suggested_fix="Consider optimizing memory usage or splitting service"
                ))
            
            if service.resource_requirements.cpu_cores > 2.0:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="performance_configuration",
                    message=f"Service {service.name} has high CPU requirement ({service.resource_requirements.cpu_cores} cores)",
                    service_name=service.name,
                    suggested_fix="Consider optimizing CPU usage or using async processing"
                ))
        
        # Check for services without idle timeout
        optional_services = [s for s in services.values() if s.classification == ServiceClassification.OPTIONAL]
        for service in optional_services:
            if service.idle_timeout is None:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    category="performance_configuration",
                    message=f"Optional service {service.name} has no idle timeout",
                    service_name=service.name,
                    suggested_fix="Add idle timeout to save resources when not in use"
                ))
        
        return issues
    
    def _validate_service_resources(self, service: ServiceConfig) -> List[ValidationIssue]:
        """Validate service resource requirements"""
        issues = []
        
        req = self.production_requirements
        
        # Memory validation
        if service.resource_requirements.memory_mb < req['min_memory_per_service']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="resource_validation",
                message=f"Service {service.name} has very low memory allocation ({service.resource_requirements.memory_mb}MB)",
                service_name=service.name,
                suggested_fix=f"Consider increasing memory to at least {req['min_memory_per_service']}MB"
            ))
        
        if service.resource_requirements.memory_mb > req['max_memory_per_service']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="resource_validation",
                message=f"Service {service.name} has excessive memory allocation ({service.resource_requirements.memory_mb}MB)",
                service_name=service.name,
                suggested_fix=f"Reduce memory allocation to under {req['max_memory_per_service']}MB"
            ))
        
        # CPU validation
        if service.resource_requirements.cpu_cores < req['min_cpu_per_service']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="resource_validation",
                message=f"Service {service.name} has very low CPU allocation ({service.resource_requirements.cpu_cores})",
                service_name=service.name,
                suggested_fix=f"Consider increasing CPU to at least {req['min_cpu_per_service']}"
            ))
        
        if service.resource_requirements.cpu_cores > req['max_cpu_per_service']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="resource_validation",
                message=f"Service {service.name} has excessive CPU allocation ({service.resource_requirements.cpu_cores})",
                service_name=service.name,
                suggested_fix=f"Reduce CPU allocation to under {req['max_cpu_per_service']}"
            ))
        
        return issues
    
    def _validate_service_timeouts(self, service: ServiceConfig) -> List[ValidationIssue]:
        """Validate service timeout configurations"""
        issues = []
        
        req = self.production_requirements
        
        # Idle timeout validation
        if service.idle_timeout is not None:
            if service.idle_timeout > req['max_idle_timeout']:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="timeout_validation",
                    message=f"Service {service.name} has very long idle timeout ({service.idle_timeout}s)",
                    service_name=service.name,
                    suggested_fix=f"Consider reducing idle timeout to under {req['max_idle_timeout']}s"
                ))
        
        # Health check interval validation
        if service.health_check_interval < req['min_health_check_interval']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="timeout_validation",
                message=f"Service {service.name} has very frequent health checks ({service.health_check_interval}s)",
                service_name=service.name,
                suggested_fix=f"Consider increasing health check interval to at least {req['min_health_check_interval']}s"
            ))
        
        if service.health_check_interval > req['max_health_check_interval']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="timeout_validation",
                message=f"Service {service.name} has infrequent health checks ({service.health_check_interval}s)",
                service_name=service.name,
                suggested_fix=f"Consider reducing health check interval to under {req['max_health_check_interval']}s"
            ))
        
        # Shutdown timeout validation
        if service.graceful_shutdown_timeout < req['min_shutdown_timeout']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="timeout_validation",
                message=f"Service {service.name} has very short shutdown timeout ({service.graceful_shutdown_timeout}s)",
                service_name=service.name,
                suggested_fix=f"Consider increasing shutdown timeout to at least {req['min_shutdown_timeout']}s"
            ))
        
        if service.graceful_shutdown_timeout > req['max_shutdown_timeout']:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="timeout_validation",
                message=f"Service {service.name} has very long shutdown timeout ({service.graceful_shutdown_timeout}s)",
                service_name=service.name,
                suggested_fix=f"Consider reducing shutdown timeout to under {req['max_shutdown_timeout']}s"
            ))
        
        return issues
    
    def _validate_service_naming(self, service: ServiceConfig) -> List[ValidationIssue]:
        """Validate service naming conventions"""
        issues = []
        
        # Check naming convention
        if not re.match(r'^[a-z][a-z0-9_]*[a-z0-9]$', service.name):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="naming_convention",
                message=f"Service name '{service.name}' doesn't follow naming convention",
                service_name=service.name,
                suggested_fix="Use lowercase letters, numbers, and underscores only"
            ))
        
        # Check for reserved names
        reserved_names = ['system', 'admin', 'root', 'config', 'health', 'status']
        if service.name.lower() in reserved_names:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="naming_convention",
                message=f"Service name '{service.name}' is reserved",
                service_name=service.name,
                suggested_fix="Choose a different service name"
            ))
        
        return issues
    
    def _validate_service_classification(self, service: ServiceConfig) -> List[ValidationIssue]:
        """Validate service classification consistency"""
        issues = []
        
        # Essential services should have higher priority
        if (service.classification == ServiceClassification.ESSENTIAL and 
            service.startup_priority > 50):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="classification_consistency",
                message=f"Essential service {service.name} has low startup priority ({service.startup_priority})",
                service_name=service.name,
                suggested_fix="Set startup priority below 50 for essential services"
            ))
        
        # Background services should have idle timeout
        if (service.classification == ServiceClassification.BACKGROUND and 
            service.idle_timeout is None):
            issues.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="classification_consistency",
                message=f"Background service {service.name} has no idle timeout",
                service_name=service.name,
                suggested_fix="Add idle timeout for background services"
            ))
        
        return issues
    
    def _validate_profile_resources(self, profile: DeploymentProfile) -> List[ValidationIssue]:
        """Validate deployment profile resource limits"""
        issues = []
        
        # Check reasonable limits
        if profile.max_memory_mb < 256:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="profile_validation",
                message=f"Profile {profile.name} has very low memory limit ({profile.max_memory_mb}MB)",
                suggested_fix="Consider increasing memory limit"
            ))
        
        if profile.max_cpu_cores < 0.5:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="profile_validation",
                message=f"Profile {profile.name} has very low CPU limit ({profile.max_cpu_cores})",
                suggested_fix="Consider increasing CPU limit"
            ))
        
        if profile.max_services < 5:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                category="profile_validation",
                message=f"Profile {profile.name} has very low service limit ({profile.max_services})",
                suggested_fix="Consider increasing service limit"
            ))
        
        return issues
    
    def _validate_profile_classifications(self, profile: DeploymentProfile) -> List[ValidationIssue]:
        """Validate profile classification settings"""
        issues = []
        
        # Essential classification should always be enabled
        if ServiceClassification.ESSENTIAL not in profile.enabled_classifications:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                category="profile_validation",
                message=f"Profile {profile.name} doesn't enable essential services",
                suggested_fix="Add 'essential' to enabled_classifications"
            ))
        
        return issues
    
    def _validate_profile_consistency(self, profile: DeploymentProfile) -> List[ValidationIssue]:
        """Validate profile internal consistency"""
        issues = []
        
        # Check profile name consistency
        if profile.name == 'production':
            if not profile.performance_optimized:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="profile_consistency",
                    message="Production profile should have performance optimization enabled",
                    suggested_fix="Set performance_optimized to true for production profile"
                ))
            
            if profile.debug_services:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    category="profile_consistency",
                    message="Production profile should not have debug services enabled",
                    suggested_fix="Set debug_services to false for production profile"
                ))
        
        if profile.name == 'development':
            if not profile.debug_services:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    category="profile_consistency",
                    message="Development profile could benefit from debug services",
                    suggested_fix="Consider enabling debug_services for development profile"
                ))
        
        return issues
    
    # Optimization suggestion methods
    
    def _suggest_resource_optimizations(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> List[ValidationIssue]:
        """Suggest resource optimizations"""
        suggestions = []
        
        # Find over-allocated services
        for service in services.values():
            if service.resource_requirements.memory_mb > 1024:
                suggestions.append(ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    category="optimization_suggestion",
                    message=f"Service {service.name} may be over-allocated memory",
                    service_name=service.name,
                    suggested_fix="Consider memory profiling and optimization"
                ))
        
        return suggestions
    
    def _suggest_service_consolidations(self, services: Dict[str, ServiceConfig]) -> List[ValidationIssue]:
        """Suggest service consolidation opportunities"""
        suggestions = []
        
        # Find services in same consolidation group
        consolidation_groups = {}
        for service in services.values():
            if service.consolidation_group:
                if service.consolidation_group not in consolidation_groups:
                    consolidation_groups[service.consolidation_group] = []
                consolidation_groups[service.consolidation_group].append(service.name)
        
        for group, service_names in consolidation_groups.items():
            if len(service_names) > 1:
                suggestions.append(ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    category="consolidation_suggestion",
                    message=f"Services in group '{group}' could be consolidated: {', '.join(service_names)}",
                    suggested_fix="Consider merging these services to reduce overhead"
                ))
        
        return suggestions
    
    def _suggest_performance_optimizations(
        self,
        services: Dict[str, ServiceConfig],
        profiles: Dict[str, DeploymentProfile],
        current_mode: DeploymentMode
    ) -> List[ValidationIssue]:
        """Suggest performance optimizations"""
        suggestions = []
        
        # Suggest GPU utilization
        gpu_compatible_services = [s for s in services.values() if s.gpu_compatible]
        if gpu_compatible_services:
            suggestions.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="performance_suggestion",
                message=f"{len(gpu_compatible_services)} services support GPU acceleration",
                suggested_fix="Consider enabling GPU compute offloading for better performance"
            ))
        
        return suggestions
    
    def _suggest_security_optimizations(self) -> List[ValidationIssue]:
        """Suggest security optimizations"""
        suggestions = []
        
        # Check for security best practices
        if not os.getenv('CORS_ORIGINS'):
            suggestions.append(ValidationIssue(
                severity=ValidationSeverity.INFO,
                category="security_suggestion",
                message="CORS origins not configured",
                suggested_fix="Set CORS_ORIGINS environment variable for better security"
            ))
        
        return suggestions