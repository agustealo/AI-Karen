"""
Capsule Manifest Schema Validation - Production Standards

Pydantic models for validating capsule manifests and ensuring
consistent structure across all skill capsules.

Research Alignment:
- ISO 27001:2022 Configuration Management
- NIST SP 800-53 CM-2 Baseline Configuration
"""

from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class CapsuleType(str, Enum):
    """Classification of capsule cognitive functions"""
    REASONING = "reasoning"
    MEMORY = "memory"
    NEURO_RECALL = "neuro_recall"
    RESPONSE = "response"
    OBSERVATION = "observation"
    SECURITY = "security"
    INTEGRATION = "integration"
    PREDICTIVE = "predictive"
    UTILITY = "utility"
    METACOGNITIVE = "metacognitive"
    PERSONALIZATION = "personalization"
    CREATIVE = "creative"
    AUTONOMOUS = "autonomous"
    DEVOPS = "devops"


class PromptType(str, Enum):
    """Supported prompt template formats"""
    PLAINTEXT = "plaintext"
    JINJA2 = "jinja2"
    MARKDOWN = "markdown"


class SecurityPolicy(BaseModel):
    """Capsule security and isolation policies"""
    allow_network_access: bool = Field(default=False, description="Network access permission")
    allow_file_system_access: bool = Field(default=False, description="Filesystem access permission")
    allow_system_calls: bool = Field(default=False, description="System call permission")
    require_hardware_isolation: bool = Field(default=True, description="Hardware isolation requirement")
    max_execution_time: int = Field(default=60, ge=1, le=600, description="Max execution time in seconds")


class CapsuleManifest(BaseModel):
    """
    Complete capsule manifest specification.

    This schema defines all required and optional fields for a capsule
    to be discovered, validated, and executed by the orchestrator.
    """
    # Core Identity
    id: str = Field(..., min_length=3, max_length=100, pattern=r"^capsule\.[a-z][a-z0-9_\.]*$",
                    description="Unique capsule identifier (e.g., capsule.devops)")
    name: str = Field(..., min_length=3, max_length=200, description="Human-readable capsule name")
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", description="Semantic version (X.Y.Z)")
    description: str = Field(..., min_length=10, description="Detailed capsule description")

    # Classification
    type: CapsuleType = Field(..., description="Capsule cognitive classification")
    capabilities: List[str] = Field(default_factory=list, description="List of specific capabilities")

    # Execution Configuration
    entrypoint: str = Field(default="handler.py", description="Python module entrypoint")
    prompt_file: Optional[str] = Field(default="prompt.txt", description="Prompt template file")
    prompt_type: PromptType = Field(default=PromptType.JINJA2, description="Prompt template format")

    # Dependencies
    requires: List[str] = Field(default_factory=list, description="Required capsule dependencies")
    memory_scope: List[str] = Field(default_factory=list, description="Memory access scope (vector, short_term, long_term)")

    # Security & RBAC
    required_roles: List[str] = Field(..., min_items=1, description="Required RBAC roles")
    allowed_tools: List[str] = Field(default_factory=list, description="Whitelisted tool interfaces")
    security_policy: SecurityPolicy = Field(default_factory=SecurityPolicy, description="Security constraints")

    # Observability
    auditable: bool = Field(default=True, description="Enable audit logging")
    sandboxed: bool = Field(default=True, description="Execute in sandbox")
    prometheus_enabled: bool = Field(default=True, description="Enable Prometheus metrics")

    # LLM Configuration (if applicable)
    max_tokens: int = Field(
        default=256,
        ge=1,
        description="Max LLM tokens. Provider/model caps are enforced downstream.",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="LLM temperature")

    # Metadata
    author: str = Field(default="Unknown", description="Capsule author")
    created: str = Field(..., description="Creation date (YYYY-MM-DD)")
    updated: str = Field(..., description="Last update date (YYYY-MM-DD)")

    # Advanced Features
    schema_version: str = Field(default="1.0.0", description="Manifest schema version")
    tags: List[str] = Field(default_factory=list, description="Search tags")
    priority: int = Field(default=50, ge=0, le=100, description="Execution priority (0=lowest, 100=highest)")

    @field_validator('id')
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Ensure capsule ID follows naming convention"""
        if not v.startswith('capsule.'):
            raise ValueError("Capsule ID must start with 'capsule.'")
        return v

    @field_validator('version', 'schema_version')
    @classmethod
    def validate_semver(cls, v: str) -> str:
        """Validate semantic versioning"""
        parts = v.split('.')
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            raise ValueError("Version must follow semantic versioning (X.Y.Z)")
        return v


class CapsuleContext(BaseModel):
    """
    Runtime context passed to capsule execution.

    Provides all necessary information for a capsule to execute
    its task with full observability and security context.
    """
    user_ctx: Dict[str, Any] = Field(..., description="User session context")
    request: Dict[str, Any] = Field(..., description="Request payload")
    correlation_id: str = Field(..., description="Unique correlation ID for tracing")
    memory_context: Optional[List[Dict[str, Any]]] = Field(default=None, description="Retrieved memory context")
    audit_payload: Optional[Dict[str, Any]] = Field(default=None, description="Audit trail data")


class CapsuleResult(BaseModel):
    """
    Standardized capsule execution result.

    Ensures consistent output structure across all capsules
    for downstream processing and observability.
    """
    result: Any = Field(..., description="Primary execution result")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Result metadata")
    audit: Optional[Dict[str, Any]] = Field(default=None, description="Audit trail")
    security: Optional[Dict[str, Any]] = Field(default=None, description="Security metadata")
    metrics: Optional[Dict[str, Any]] = Field(default=None, description="Performance metrics")
    errors: Optional[List[str]] = Field(default=None, description="Non-fatal errors")


__all__ = [
    "CapsuleType",
    "PromptType",
    "SecurityPolicy",
    "CapsuleManifest",
    "CapsuleContext",
    "CapsuleResult",
]
