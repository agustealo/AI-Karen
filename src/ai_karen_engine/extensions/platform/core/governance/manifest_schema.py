"""
Governance models for plugin manifest enforcement.

These models extend the canonical ExtensionManifest with fields required
for the PLUGIN-GOVERNANCE-1 closure: prompt contracts, versioned schemas,
side-effect classification, audit requirements, tenant scoping, secret/network
access declarations, and deprecation metadata.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field


class SideEffectLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"


class SideEffectClassification(BaseModel):
    level: SideEffectLevel = SideEffectLevel.NONE
    description: Optional[str] = None
    affected_resources: List[str] = Field(default_factory=list)
    reversible: bool = True


class AuditRequirement(str, Enum):
    STANDARD = "standard"
    ELEVATED = "elevated"
    FULL = "full"


class AuditRequirements(BaseModel):
    requirement: AuditRequirement = AuditRequirement.STANDARD
    log_input: bool = True
    log_output: bool = True
    log_metadata: bool = True
    retention_days: int = 90
    include_correlation_id: bool = True


class TenantScope(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    GLOBAL = "global"


class TenantIsolation(BaseModel):
    scope: TenantScope = TenantScope.SINGLE
    allowed_tenant_ids: List[str] = Field(default_factory=list)
    deny_cross_tenant: bool = True
    data_partition_key: Optional[str] = None


class SecretAccessRequirement(BaseModel):
    required_secrets: List[str] = Field(default_factory=list)
    allow_runtime_resolution: bool = False
    allow_environment_fallback: bool = False
    max_secret_age_seconds: Optional[int] = None


class NetworkAccessRequirement(BaseModel):
    allow_external: bool = False
    allowed_domains: List[str] = Field(default_factory=list)
    allowed_hosts: List[str] = Field(default_factory=list)
    allowed_ports: List[int] = Field(default_factory=list)
    require_tls: bool = True
    max_request_size_kb: int = 1024
    timeout_seconds: int = 30


class DeprecationInfo(BaseModel):
    deprecated: bool = False
    deprecation_date: Optional[datetime] = None
    removal_date: Optional[datetime] = None
    replacement_plugin_id: Optional[str] = None
    migration_guide: Optional[str] = None


class PluginGovernanceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None
    input_schema_version: Optional[str] = None
    output_schema_version: Optional[str] = None
    side_effects: SideEffectClassification = Field(
        default_factory=SideEffectClassification
    )
    audit: AuditRequirements = Field(default_factory=AuditRequirements)
    tenant: TenantIsolation = Field(default_factory=TenantIsolation)
    secrets: SecretAccessRequirement = Field(default_factory=SecretAccessRequirement)
    network: NetworkAccessRequirement = Field(default_factory=NetworkAccessRequirement)
    deprecation: DeprecationInfo = Field(default_factory=DeprecationInfo)


__all__ = [
    "SideEffectLevel",
    "SideEffectClassification",
    "AuditRequirement",
    "AuditRequirements",
    "TenantScope",
    "TenantIsolation",
    "SecretAccessRequirement",
    "NetworkAccessRequirement",
    "DeprecationInfo",
    "PluginGovernanceManifest",
]
