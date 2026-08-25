"""
Canonical extension contracts for the EXTENSION-KERNEL-1 runtime.

These typed contracts replace raw dictionaries at every boundary:
  manifest -> registration -> discovery -> execution -> result
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:
    from ai_karen_engine.pydantic_stub import BaseModel, ConfigDict, Field


class TrustTier(str, Enum):
    BUILTIN_TRUSTED = "builtin_trusted"
    FIRST_PARTY = "first_party"
    SIGNED_THIRD_PARTY = "signed_third_party"
    UNTRUSTED = "untrusted"
    REMOTE = "remote"


class ExecutionIsolationMode(str, Enum):
    IN_PROCESS = "in_process"
    SUBPROCESS = "subprocess"
    CONTAINER = "container"
    WASM = "wasm"
    REMOTE = "remote"


class ExtensionLifecycleState(str, Enum):
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class SideEffectLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXTERNAL = "external"


class TenantScope(str, Enum):
    SINGLE = "single"
    MULTI = "multi"
    GLOBAL = "global"


class ResponseSource(str, Enum):
    MODEL = "model"
    TOOL = "tool"
    PLUGIN = "plugin"
    AGENT = "agent"
    WORKFLOW = "workflow"
    CACHED = "cached"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class Idempotency(str, Enum):
    UNKNOWN = "unknown"
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class RiskClass(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ResultTrust(str, Enum):
    SYSTEM_TRUSTED = "system_trusted"
    VERIFIED = "verified"
    UNTRUSTED_EXTERNAL = "untrusted_external"
    UNVERIFIED = "unverified"


class ExtensionCapability(BaseModel):
    """Declared capability of an extension with operation-specific contracts."""

    id: str
    version: str = "1.0.0"

    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)

    required_permissions: List[str] = Field(default_factory=list)
    optional_permissions: List[str] = Field(default_factory=list)
    required_roles: List[str] = Field(default_factory=list)

    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    risk_class: RiskClass = RiskClass.LOW
    idempotency: Idempotency = Idempotency.UNKNOWN

    retry_policy: Dict[str, Any] = Field(default_factory=lambda: {"max_retries": 3, "retryable": True})

    requires_network: bool = False
    requires_filesystem: bool = False
    requires_credentials: bool = False

    resource_profile: Dict[str, Any] = Field(default_factory=dict)

    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None

    supports_streaming: bool = False
    supports_cancellation: bool = False

    data_classification: DataClassification = DataClassification.PUBLIC
    result_trust: ResultTrust = ResultTrust.UNTRUSTED_EXTERNAL

    provides_ui: bool = False
    provides_api: bool = False
    provides_background_tasks: bool = False
    provides_webhooks: bool = False


class ExtensionDependency(BaseModel):
    """Declared dependency of an extension."""

    id: str
    version: Optional[str] = None
    optional: bool = False
    dependency_type: str = "extension"


class ExtensionPermissionGrant(BaseModel):
    """Resolved permission grant for an extension invocation."""

    permission_id: str
    granted: bool
    granted_by: str = "policy"
    reason: Optional[str] = None


class ExtensionManifest(BaseModel):
    """Canonical extension manifest.

    This is the typed boundary model. No raw manifest dicts past this point.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    plugin_api_version: str = "1.0"
    description: str
    entrypoint: str

    capabilities: List[ExtensionCapability] = Field(default_factory=list)
    intents: List[str] = Field(default_factory=list)

    required_permissions: List[str] = Field(default_factory=list)
    optional_permissions: List[str] = Field(default_factory=list)

    required_roles: List[str] = Field(default_factory=list)

    tenant_scope: TenantScope = TenantScope.SINGLE
    allowed_tenant_ids: List[str] = Field(default_factory=list)

    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)

    prompt_contract_id: Optional[str] = None
    prompt_version: Optional[str] = None

    requires_network: bool = False
    requires_filesystem: bool = False
    requires_credentials: bool = False
    requires_external_api: bool = False

    side_effect_level: SideEffectLevel = SideEffectLevel.NONE

    timeout_ms: int = 30000
    max_retries: int = 3

    enabled_by_default: bool = False
    trusted_ui: bool = False
    trust_tier: TrustTier = TrustTier.UNTRUSTED
    isolation_mode: ExecutionIsolationMode = ExecutionIsolationMode.IN_PROCESS

    dependencies: List[ExtensionDependency] = Field(default_factory=list)

    metadata: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class ExtensionRegistration:
    """Runtime registration record for an extension."""

    manifest: ExtensionManifest
    state: ExtensionLifecycleState
    health: str = "unknown"
    loaded_at: Optional[datetime] = None
    last_error: Optional[str] = None
    instance: Any = None
    checksum: Optional[str] = None


class ExtensionHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass
class ExtensionHealthRecord:
    plugin_id: str
    state: ExtensionLifecycleState
    health: ExtensionHealth
    last_check: Optional[datetime] = None
    reason_code: Optional[str] = None
    dependency_status: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExtensionExecutionContext:
    """Scoped execution context for an extension invocation."""

    request_id: str
    correlation_id: str
    user_id: str
    tenant_id: str = "default"
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    allowed_capabilities: List[str] = field(default_factory=list)
    resource_scope: Dict[str, Any] = field(default_factory=dict)
    budget: Optional[Dict[str, Any]] = None
    audit_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityInvocationRequest:
    """Intent-based capability invocation request.

    Represents WHAT the intelligence kernel requires, not WHO executes it.
    Runtime resolves the appropriate extension.
    """

    capability_id: str
    capability_version_constraint: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    context: ExtensionExecutionContext = field(default_factory=lambda: ExtensionExecutionContext(
        request_id="", correlation_id="", user_id=""
    ))
    provider_hint: Optional[str] = None
    authorized_plan: Optional[Dict[str, Any]] = None
    deadline: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class ResolvedCapability:
    """Resolved capability with chosen extension."""

    capability: ExtensionCapability
    extension_id: str
    extension_version: str
    extension_trust_tier: TrustTier
    extension_isolation_mode: ExecutionIsolationMode
    policy_decision_id: Optional[str] = None
    resource_budget: Optional[Dict[str, Any]] = None


@dataclass
class ExtensionExecutionRequest:
    """Typed execution request.

    Kept for compatibility during migration. New code should use
    CapabilityInvocationRequest which is capability-first, not plugin-first.
    """

    plugin_id: str
    capability: str
    payload: Dict[str, Any]
    context: ExtensionExecutionContext
    authorized_plan: Optional[Dict[str, Any]] = None
    timeout_override_ms: Optional[int] = None


@dataclass
class ExtensionExecutionResult:
    """Typed execution result with provenance and trust metadata."""

    request_id: str
    plugin_id: str
    plugin_version: str
    capability: str
    source: ResponseSource
    payload: Any
    latency_ms: float
    status: str
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    side_effects: List[str] = field(default_factory=list)
    permission_set: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    execution_id: Optional[str] = None
    degraded: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)

    trust_tier: TrustTier = TrustTier.UNTRUSTED
    result_trust: ResultTrust = ResultTrust.UNTRUSTED_EXTERNAL
    data_classification: DataClassification = DataClassification.PUBLIC

    backend: Optional[str] = None
    backend_version: Optional[str] = None
    requested_url: Optional[str] = None
    final_url: Optional[str] = None
    canonical_url: Optional[str] = None
    fetched_at: Optional[datetime] = None
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    content_hash: Optional[str] = None
    title: Optional[str] = None
    crawl_depth: Optional[int] = None
    parent_url: Optional[str] = None
    redirect_chain: List[str] = field(default_factory=list)
    extraction_method: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    raw_artifact_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "capability": self.capability,
            "source": self.source.value,
            "payload": self.payload,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "side_effects": list(self.side_effects),
            "permission_set": list(self.permission_set),
            "correlation_id": self.correlation_id,
            "policy_decision_id": self.policy_decision_id,
            "execution_id": self.execution_id,
            "degraded": self.degraded,
            "created_at": self.created_at.isoformat(),
            "trust_tier": self.trust_tier.value,
            "result_trust": self.result_trust.value,
            "data_classification": self.data_classification.value,
        }


__all__ = [
    "Idempotency",
    "RiskClass",
    "DataClassification",
    "ResultTrust",
    "TrustTier",
    "ExecutionIsolationMode",
    "ExtensionLifecycleState",
    "SideEffectLevel",
    "TenantScope",
    "ResponseSource",
    "ExtensionCapability",
    "ExtensionDependency",
    "ExtensionPermissionGrant",
    "ExtensionManifest",
    "ExtensionRegistration",
    "ExtensionHealth",
    "ExtensionHealthRecord",
    "ExtensionExecutionContext",
    "CapabilityInvocationRequest",
    "ResolvedCapability",
    "ExtensionExecutionRequest",
    "ExtensionExecutionResult",
]
