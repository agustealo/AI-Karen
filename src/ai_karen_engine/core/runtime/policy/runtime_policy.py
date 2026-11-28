"""
Runtime Policy — global execution authorization outside LangGraph.

CORTEX decides what execution and reasoning are cognitively desirable.
RuntimePolicy decides what is authorized. Runtime executes the resulting plan.
LangGraph remains a workflow executor and never owns global policy.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, NotRequired, Optional, TypedDict
from weakref import WeakValueDictionary, finalize

from ai_karen_engine.core.runtime.contracts import (
    GENERATED_TEXT_ARTIFACT_CAPABILITY,
    AuthorizedExecutionPlan,
    DegradationState,
    ExecutionBudget,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.policy.reasoning_policy import (
    ReasoningModePolicyResult,
    authorize_reasoning_modes,
)

if TYPE_CHECKING:
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
    from ai_karen_engine.core.runtime.document_consent_approval import (
        DocumentConsentApprovalScope,
    )
    from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
        PluginLifecycleApprovalScope,
    )

logger = logging.getLogger(__name__)


def chat_tool_call_limit(tool_requirements: list[str]) -> int:
    """Preserve the existing chat allowance for declared tools and retries."""
    return len(tool_requirements) + 5

class RuntimeLevel(str, Enum):
    FULL = "FULL"
    REDUCED = "REDUCED"
    SAFE = "SAFE"
    EMERGENCY = "EMERGENCY"


class PolicyReasonCode(str, Enum):
    ALLOWED = "allowed"
    MISSING_IDENTITY = "missing_identity"
    CAPABILITY_CONFLICT = "capability_conflict"
    INSUFFICIENT_PERMISSION = "insufficient_permission"
    TOOL_RISK_DENIED = "tool_risk_denied"
    RUNTIME_LEVEL_DENIED = "runtime_level_denied"
    RESOURCE_SCOPE_DENIED = "resource_scope_denied"
    REASONING_MODE_RESTRICTED = "reasoning_mode_restricted"
    POLICY_CHECK_PASSED = "policy_check_passed"


@dataclass
class PolicyResourceScope:
    """Trusted resource scope for policy decisions."""

    allowed_paths: List[str] = field(default_factory=list)
    forbidden_paths: List[str] = field(default_factory=list)
    max_file_size_mb: int = 10
    allowed_networks: List[str] = field(default_factory=lambda: ["internal"])
    forbidden_networks: List[str] = field(default_factory=list)


class FileExplorerOperationScope(TypedDict):
    """Exact owner-organization operation arguments, not filesystem paths."""

    operation: str
    availability_only: NotRequired[bool]
    name: NotRequired[str]
    folder_id: NotRequired[str]
    parent_folder_id: NotRequired[str | None]
    source_id: NotRequired[str]
    destination_id: NotRequired[str | None]
    expected_revision: NotRequired[int]


@dataclass
class ProviderConstraints:
    """Typed provider constraints from policy decision."""

    eligible_providers: List[str] = field(default_factory=list)
    forbidden_providers: List[str] = field(default_factory=list)
    local_only: bool = False
    external_allowed: bool = True
    capability_restrictions: List[str] = field(default_factory=list)
    resource_constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceConstraints:
    """Typed resource constraints from policy decision."""

    max_memory_mb: int = 256
    max_cpu_time_seconds: int = 30
    max_wall_time_seconds: int = 60
    max_output_size_kb: int = 1024
    max_file_descriptors: int = 64
    max_processes: int = 1
    max_threads: int = 4


@dataclass
class PolicyEvaluationRequest:
    """Typed request for RuntimePolicy evaluation."""

    user_id: str
    tenant_id: str
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    action: str = "general_assist"
    resource: Optional[str] = None
    # Host-normalized selected artifact revisions, not client-granted access.
    attachment_references: List[Dict[str, str]] = field(default_factory=list)
    requested_capabilities: List[str] = field(default_factory=list)
    forbidden_capabilities: List[str] = field(default_factory=list)
    requested_reasoning_modes: List[str] = field(default_factory=list)
    max_model_calls: int = 0
    risk_signals: Dict[str, Any] = field(default_factory=dict)
    runtime_level: RuntimeLevel = RuntimeLevel.FULL
    extension_id: Optional[str] = None
    plugin_id: Optional[str] = None
    tool_id: Optional[str] = None
    provider_constraints: Optional[ProviderConstraints] = None
    environment: str = "production"
    resource_scope: PolicyResourceScope | FileExplorerOperationScope | None = None
    execution_topology: Dict[str, Any] = field(default_factory=dict)
    # Explicit host-selected operation; never a capability or source grant by itself.
    document_operation: Optional[Dict[str, Any]] = field(default=None, repr=False)


@dataclass
class PolicyDecision:
    """Typed RuntimePolicy authorization decision."""

    decision_id: str
    policy_version: str
    allowed: bool
    reason_codes: List[PolicyReasonCode] = field(default_factory=list)
    allowed_capabilities: List[str] = field(default_factory=list)
    denied_capabilities: List[str] = field(default_factory=list)
    allowed_reasoning_modes: List[str] = field(default_factory=list)
    denied_reasoning_modes: List[str] = field(default_factory=list)
    reasoning_denial_reasons: Dict[str, List[str]] = field(default_factory=dict)
    requires_human_gate: bool = False
    runtime_constraints: Dict[str, Any] = field(default_factory=dict)
    resource_scope: PolicyResourceScope | FileExplorerOperationScope | None = None
    provider_constraints: Optional[ProviderConstraints] = None
    resource_constraints: Optional[ResourceConstraints] = None
    risk_level: Optional[str] = None
    evaluated_at: Optional[float] = None

    @property
    def forbidden_capabilities(self) -> List[str]:
        """Backward-compatible alias for denied_capabilities."""
        return self.denied_capabilities

    @forbidden_capabilities.setter
    def forbidden_capabilities(self, value: List[str]) -> None:
        self.denied_capabilities = list(value)

    def to_authorized_plan(self) -> AuthorizedExecutionPlan:
        """Convert policy truth to the canonical runtime execution plan."""
        topology = ExecutionTopology.DIRECT
        if self.requires_human_gate:
            topology = ExecutionTopology.WORKFLOW
        if self.runtime_constraints.get("agent_delegation"):
            topology = ExecutionTopology.MULTI_AGENT
        if self.allowed_reasoning_modes:
            topology = ExecutionTopology.REASONING
        elif self.runtime_constraints.get("workflow_id"):
            topology = ExecutionTopology.WORKFLOW

        resource = self.resource_constraints
        scope = self.resource_scope
        plan_scope: Dict[str, Any] = {}
        if isinstance(scope, PolicyResourceScope):
            plan_scope = {
                "allowed_paths": list(scope.allowed_paths),
                "forbidden_paths": list(scope.forbidden_paths),
                "max_file_size_mb": scope.max_file_size_mb,
            }
        elif isinstance(scope, dict):
            # Explorer's exact mutation arguments are a different contract
            # from path/network constraints. Never forward arbitrary maps
            # into another plugin's authorization plan.
            from ai_karen_engine.auth.rbac_middleware import (
                FILE_EXPLORER_MUTATION_PERMISSIONS, Permission,
            )

            operation = scope.get("operation")
            entitlement = (FILE_EXPLORER_MUTATION_PERMISSIONS.get(operation)
                           if isinstance(operation, str) else None)
            if self.allowed and scope:
                if (
                    entitlement is None
                    or "file-explorer" not in (self.runtime_constraints.get("allowed_plugins") or [])
                    or not {"file-explorer", Permission.DATA_READ.value,
                            entitlement.value, operation}.issubset(self.allowed_capabilities)
                ):
                    raise ValueError("policy_operation_scope_invalid")
                plan_scope = deepcopy(dict(scope))
        elif scope is not None:
            raise ValueError("policy_resource_scope_invalid")
        document_digest = self.runtime_constraints.get("document_operation_digest")
        if self.allowed and document_digest is not None:
            if plan_scope or not {"content-intelligence", "data:read"}.issubset(self.allowed_capabilities):
                raise ValueError("policy_operation_scope_invalid")
            plan_scope = {
                "attachment_references": deepcopy(self.runtime_constraints["attachment_references"]),
                "document_operation_digest": document_digest,
            }
        return AuthorizedExecutionPlan(
            execution_id=self.decision_id,
            policy_decision_id=self.decision_id,
            authorized_user_id=str(
                self.runtime_constraints.get("authorized_user_id") or ""
            ),
            authorized_tenant_id=str(
                self.runtime_constraints.get("authorized_tenant_id") or ""
            ),
            authorized_session_id=self.runtime_constraints.get(
                "authorized_session_id"
            ),
            topology=topology,
            allowed_capabilities=list(self.allowed_capabilities),
            allowed_tools=list(self.runtime_constraints.get("allowed_tools") or []),
            allowed_plugins=list(self.runtime_constraints.get("allowed_plugins") or []),
            allowed_agents=list(self.runtime_constraints.get("allowed_agents") or []),
            provider_constraints=(
                {
                    "eligible_providers": self.provider_constraints.eligible_providers,
                    "forbidden_providers": self.provider_constraints.forbidden_providers,
                    "local_only": self.provider_constraints.local_only,
                    "external_allowed": self.provider_constraints.external_allowed,
                }
                if self.provider_constraints
                else {}
            ),
            memory_scope=str(self.runtime_constraints.get("memory_scope", "session")),
            resource_scope=plan_scope,
            budget=ExecutionBudget(
                max_duration_ms=(resource.max_wall_time_seconds * 1000 if resource else 30000),
                max_model_calls=int(self.runtime_constraints.get("max_model_calls", 10)),
                max_tool_calls=self.runtime_constraints.get(
                    "max_tool_calls", ExecutionBudget().max_tool_calls,
                ),
                max_reasoning_steps=int(self.runtime_constraints.get("max_reasoning_steps", 10)),
                max_output_tokens=(resource.max_output_size_kb * 1024 if resource else 4096),
            ),
            approval_requirements=["human_gate"] if self.requires_human_gate else [],
            reasoning_modes=list(self.allowed_reasoning_modes),
            workflow_id=self.runtime_constraints.get("workflow_id"),
            agent_topology=self.runtime_constraints.get("agent_topology"),
            degraded_allowed=bool(self.runtime_constraints.get("degraded_allowed", True)),
            degradation_state=(
                DegradationState(
                    degraded=True,
                    reason_code=self.reason_codes[0].value if self.reason_codes else None,
                    level=str(self.risk_level or "none").lower(),
                )
                if not self.allowed
                else None
            ),
            audit_context={
                "decision_id": self.decision_id,
                "policy_version": self.policy_version,
                "evaluated_at": self.evaluated_at,
                "risk_level": self.risk_level,
                "correlation_id": self.runtime_constraints.get("correlation_id"),
                "allowed_reasoning_modes": list(self.allowed_reasoning_modes),
                "denied_reasoning_modes": list(self.denied_reasoning_modes),
                "reasoning_denial_reasons": dict(self.reasoning_denial_reasons),
            },
        )


@dataclass(frozen=True, slots=True)
class ResponseStrategyPolicyProbe:
    """Read-only policy permission; never action eligibility or OPE evidence.

    This does not authorize any change to the CORTEX-selected execution plan.
    Provider availability, actual execution and reward remain unverified.
    """

    source_decision_id: str
    source_policy_version: str
    selected_action: str
    policy_permitted_actions: tuple[str, ...]
    status: str
    alternative_policy_decision_id: Optional[str] = None
    alternative_policy_version: Optional[str] = None

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "schema_version": "response_strategy_policy_probe_v1",
            "source_decision_id": self.source_decision_id,
            "source_policy_version": self.source_policy_version,
            "selected_action": self.selected_action,
            "policy_permitted_actions": list(self.policy_permitted_actions),
            "status": self.status,
            "alternative_policy_decision_id": self.alternative_policy_decision_id,
            "alternative_policy_version": self.alternative_policy_version,
            "execution_eligibility_established": False,
            "randomized_selection": False,
            "ope_eligible": False,
        }


class PolicyCheckResult:
    def __init__(self, allowed: bool, reason: str, severity: str = "info"):
        self.allowed = allowed
        self.reason = reason
        self.severity = severity


@dataclass
class RuntimePolicyConfig:
    default_level: RuntimeLevel = RuntimeLevel.FULL
    enable_degraded_mode: bool = True
    enable_routing_restrictions: bool = True
    enable_execution_constraints: bool = True
    enable_safety_overrides: bool = True


class RuntimePolicyEnforcer:
    """Enforce authorization across direct, reasoning, tool and graph paths."""

    def __init__(self, config: Optional[RuntimePolicyConfig] = None):
        self.config = config or RuntimePolicyConfig()
        # The existing RuntimePolicy is the sole issuer. A policy ID or a
        # caller-constructed PolicyDecision is never an execution grant.
        # Weak values expire with the actual issuer-returned decision.
        self._issued_model_decisions: WeakValueDictionary[str, PolicyDecision] = (
            WeakValueDictionary()
        )
        # Immutable issuer-time content, retained only as long as the
        # original weakly held decision exists. An in-process mutation of
        # PolicyDecision.runtime_constraints cannot increase privileges.
        self._issued_model_claims: Dict[str, Any] = {}
        self._issued_model_lock = threading.RLock()
        self.level_transitions = {
            RuntimeLevel.FULL: [RuntimeLevel.REDUCED],
            RuntimeLevel.REDUCED: [RuntimeLevel.SAFE, RuntimeLevel.FULL],
            RuntimeLevel.SAFE: [RuntimeLevel.EMERGENCY, RuntimeLevel.REDUCED],
            RuntimeLevel.EMERGENCY: [RuntimeLevel.SAFE],
        }

    @staticmethod
    def authorize_external_provider_execution(
        *,
        context: "ChatExecutionContext",
        plan: AuthorizedExecutionPlan,
        expression_policies: object,
    ) -> bool:
        """Verify a cloud attempt against the original authenticated chat plan.

        RuntimePolicy is the only authority. This is called immediately before
        every eligible cloud-engine attempt, including fallback, so a forged
        request role, detached task, or revoked permission cannot act as a grant.
        No model, endpoint, or credential selection occurs here.
        """
        if (
            not plan.policy_decision_id
            or not plan.matches_execution_scope(
                user_id=str(context.user_id),
                tenant_id=str(context.tenant_id),
                session_id=context.session_id,
            )
            or getattr(expression_policies, "allow_external_engines", None) is not True
        ):
            return False
        try:
            principal = context.require_authenticated_user()
        except (PermissionError, AttributeError):
            return False
        require_admin = getattr(expression_policies, "require_admin_for_external", None)
        if require_admin is False:
            return True
        if require_admin is not True:
            return False
        from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

        return get_rbac_manager().has_permission(
            principal, Permission.ADMIN_PROVIDERS_MANAGE,
        )

    async def probe_optional_verification(
        self,
        request: PolicyEvaluationRequest,
        selected_policy: PolicyDecision,
        *,
        direct_plan_authorized: bool,
    ) -> ResponseStrategyPolicyProbe:
        """Independently check *policy permission* for optional verification.

        Only the already authorized direct reply can be considered a chosen
        strategy. A second, isolated RuntimePolicy evaluation checks whether a
        verification reasoning mode would be permitted with the same trusted
        principal, capability restrictions, risk signals and model budget.
        Neither result proves that the alternative is executable; callers must
        not use this probe for sampling, eligibility, or an OPE receipt.
        """
        # The selected policy must belong to the exact authenticated context.
        # Matching only the shadow decision would allow cross-principal source
        # lineage to be relabelled as a valid optional-verification probe.
        selected_scope = selected_policy.runtime_constraints
        if (
            not direct_plan_authorized
            or not selected_policy.allowed
            or selected_scope.get("authorized_user_id") != request.user_id
            or selected_scope.get("authorized_tenant_id") != request.tenant_id
            or selected_scope.get("authorized_session_id") != request.session_id
            or selected_scope.get("correlation_id") != request.correlation_id
        ):
            return ResponseStrategyPolicyProbe(
                source_decision_id=selected_policy.decision_id,
                source_policy_version=selected_policy.policy_version,
                selected_action="",
                policy_permitted_actions=(),
                status="not_authorized",
            )
        selected_only = ResponseStrategyPolicyProbe(
            source_decision_id=selected_policy.decision_id,
            source_policy_version=selected_policy.policy_version,
            selected_action="respond_direct",
            policy_permitted_actions=("respond_direct",),
            status="selected_only",
        )
        topology = request.execution_topology
        if (
            selected_policy.requires_human_gate
            or selected_policy.risk_level not in {"low", "medium"}
            or not selected_policy.decision_id
            or not selected_policy.policy_version
            or request.runtime_level not in {RuntimeLevel.FULL, RuntimeLevel.REDUCED}
            or request.max_model_calls < 2
            or request.requested_reasoning_modes
            or selected_policy.allowed_reasoning_modes
            or selected_policy.denied_reasoning_modes
            or request.tool_id
            or request.plugin_id
            or request.extension_id
            or request.resource
            or topology.get("tool_requirements")
            or topology.get("plugin_candidates")
            or topology.get("requested_agents")
            or topology.get("requires_human_gate")
            or topology.get("agent_delegation")
            or topology.get("workflow_id")
            or any(
                capability.startswith(
                    ("channel.", "automation.", "model.personal_key.")
                )
                for capability in request.requested_capabilities
            )
        ):
            return selected_only

        # A separate permission evaluation does not touch the selected plan.
        alt_request = replace(
            request,
            requested_reasoning_modes=["verification"],
            execution_topology={
                **topology,
                "reasoning_modes": ["verification"],
            },
        )
        alternative = await self.evaluate(alt_request)
        if (
            not alternative.allowed
            or alternative.requires_human_gate
            or alternative.risk_level != selected_policy.risk_level
            or alternative.policy_version != selected_policy.policy_version
            or alternative.allowed_reasoning_modes != ["verification"]
            or alternative.denied_reasoning_modes
            or alternative.runtime_constraints.get("authorized_user_id") != request.user_id
            or alternative.runtime_constraints.get("authorized_tenant_id") != request.tenant_id
            or alternative.runtime_constraints.get("authorized_session_id") != request.session_id
        ):
            return selected_only

        return ResponseStrategyPolicyProbe(
            source_decision_id=selected_policy.decision_id,
            source_policy_version=selected_policy.policy_version,
            selected_action="respond_direct",
            policy_permitted_actions=("respond_direct", "verify_then_respond"),
            status="alternative_reasoning_mode_policy_permitted",
            alternative_policy_decision_id=alternative.decision_id,
            alternative_policy_version=alternative.policy_version,
        )

    async def authorize_document_consent_preflight(
        self,
        *,
        context: "ChatExecutionContext",
        scope: "DocumentConsentApprovalScope",
    ) -> PolicyDecision:
        """Host-only document author admission; NEVER an executable grant.

        A generic PolicyEvaluationRequest remains categorically denied.
        Runtime executes only after independently revalidating the bearer,
        canonical source revision and an approved, one-shot PostgreSQL CAS.
        """
        from ai_karen_engine.core.runtime.document_consent_approval import (
            DocumentConsentApprovalScope,
        )

        reason = PolicyReasonCode.RESOURCE_SCOPE_DENIED
        valid_scope = isinstance(scope, DocumentConsentApprovalScope)
        if self.config.default_level is not RuntimeLevel.FULL:
            reason = PolicyReasonCode.RUNTIME_LEVEL_DENIED
        elif not valid_scope:
            reason = PolicyReasonCode.RESOURCE_SCOPE_DENIED
        else:
            try:
                principal = context.require_authenticated_user()
                scope.require_matching_context(context)
                if (
                    scope.action != "issue"
                    or not principal.is_active
                    or not principal.is_verified
                    or scope.analysis_allowed is not True
                    or type(scope.style_use_allowed) is not bool
                    or scope.expires_at <= datetime.now(timezone.utc)
                ):
                    reason = PolicyReasonCode.RESOURCE_SCOPE_DENIED
                else:
                    reason = PolicyReasonCode.ALLOWED
            except (AttributeError, PermissionError, TypeError, ValueError):
                reason = PolicyReasonCode.MISSING_IDENTITY

        allowed = reason is PolicyReasonCode.ALLOWED
        action = "writing_style.document_consent.issue"
        return PolicyDecision(
            decision_id=f"policy-document-consent-preflight-{time.time_ns()}",
            policy_version="v2-document-author-preflight",
            allowed=allowed,
            reason_codes=[reason],
            # This policy permits proceeding to durable author evidence; it
            # is not a right to mint a receipt without that evidence.
            allowed_capabilities=[],
            denied_capabilities=[] if allowed else [action],
            requires_human_gate=True,
            risk_level="high",
            evaluated_at=time.time(),
            runtime_constraints=(
                {
                    "authorized_user_id": scope.author_actor_id,
                    "authorized_tenant_id": scope.tenant_id,
                    "authorized_session_id": scope.session_id,
                    "document_consent_approval_only": True,
                    "document_consent_source_sha256": scope.source_sha256,
                    "document_consent_fingerprint": scope.fingerprint(),
                } if allowed else {}
            ),
        )

    async def authorize_document_consent_revocation(
        self,
        *,
        context: "ChatExecutionContext",
        tenant_id: str,
        actor_id: str,
    ) -> PolicyDecision:
        """Host-only owner revocation preflight, not a consent mutation grant.

        The issuer must revalidate the bearer and update only the author's
        existing receipt under PostgreSQL RLS and the one-way revoke trigger.
        """
        reason = PolicyReasonCode.INSUFFICIENT_PERMISSION
        if self.config.default_level is not RuntimeLevel.FULL:
            reason = PolicyReasonCode.RUNTIME_LEVEL_DENIED
        else:
            try:
                principal = context.require_authenticated_user()
                if (
                    context.tenant_id == tenant_id
                    and context.user_id == actor_id
                    and principal.tenant_id == tenant_id
                    and principal.user_id == actor_id
                    and principal.is_active
                    and principal.is_verified
                ):
                    reason = PolicyReasonCode.ALLOWED
            except (AttributeError, PermissionError, TypeError, ValueError):
                reason = PolicyReasonCode.MISSING_IDENTITY
        allowed = reason is PolicyReasonCode.ALLOWED
        action = "writing_style.document_consent.revoke"
        return PolicyDecision(
            decision_id=f"policy-document-consent-revoke-{time.time_ns()}",
            policy_version="v2-document-author-revoke",
            allowed=allowed,
            reason_codes=[reason],
            allowed_capabilities=[],
            denied_capabilities=[] if allowed else [action],
            requires_human_gate=True,
            risk_level="high",
            evaluated_at=time.time(),
            runtime_constraints=(
                {
                    "authorized_user_id": actor_id,
                    "authorized_tenant_id": tenant_id,
                    "authorized_session_id": context.session_id,
                    "document_consent_revocation_only": True,
                } if allowed else {}
            ),
        )

    def _plugin_lifecycle_preflight_reason(
        self,
        *,
        context: "ChatExecutionContext",
        scope: "PluginLifecycleApprovalScope",
        observed_state: str,
        manifest_checksum: str,
        revision: int,
        disposition: str,
    ) -> PolicyReasonCode:
        """One RuntimePolicy owner for both prepare and post-consent evidence."""
        from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )

        if not isinstance(scope, PluginLifecycleApprovalScope):
            return PolicyReasonCode.RESOURCE_SCOPE_DENIED
        if self.config.default_level is not RuntimeLevel.FULL:
            return PolicyReasonCode.RUNTIME_LEVEL_DENIED
        try:
            principal = context.require_authenticated_user()
            scope.require_matching_context(context)
        except (PermissionError, AttributeError, TypeError, ValueError):
            return PolicyReasonCode.MISSING_IDENTITY
        if not get_rbac_manager().has_permission(
            principal, Permission.ADMIN_PLUGINS_MANAGE,
        ):
            return PolicyReasonCode.INSUFFICIENT_PERMISSION
        if (
            observed_state != scope.expected_state
            or manifest_checksum != scope.manifest_checksum
            or type(revision) is not int
            or revision != scope.expected_revision
            or disposition != "ready"
        ):
            return PolicyReasonCode.RESOURCE_SCOPE_DENIED
        return PolicyReasonCode.ALLOWED

    async def authorize_plugin_lifecycle_preflight(
        self,
        *,
        context: "ChatExecutionContext",
        scope: "PluginLifecycleApprovalScope",
        observed_state: str,
        manifest_checksum: str,
        revision: int,
        disposition: str,
    ) -> PolicyDecision:
        """Authorize requesting consent, never executing a physical transition.

        Host-only callers must first obtain scope from a verified kernel
        observation and the global ledger. Deliberately grant zero executable
        capabilities. ActionExecutionGate must deny this decision even when
        RuntimePolicy allows asking a human for approval.
        """
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )

        reason = self._plugin_lifecycle_preflight_reason(
            context=context,
            scope=scope,
            observed_state=observed_state,
            manifest_checksum=manifest_checksum,
            revision=revision,
            disposition=disposition,
        )
        allowed = reason is PolicyReasonCode.ALLOWED
        action = (
            "plugin.lifecycle." + scope.action
            if isinstance(scope, PluginLifecycleApprovalScope)
            else "plugin.lifecycle.invalid"
        )
        return PolicyDecision(
            decision_id=f"policy-plugin-lifecycle-preflight-{time.time_ns()}",
            policy_version="v2-lifecycle-preflight",
            allowed=allowed,
            reason_codes=[reason],
            # A preapproval is not a capability grant. Consent and a fresh
            # post-approval decision are required before ActionExecutionGate.
            allowed_capabilities=[],
            denied_capabilities=[] if allowed else [action],
            requires_human_gate=True,
            risk_level="high",
            evaluated_at=time.time(),
            runtime_constraints=(
                {
                    "authorized_user_id": scope.user_id,
                    "authorized_tenant_id": scope.tenant_id,
                    "authorized_session_id": scope.session_id,
                    "plugin_lifecycle_approval_only": True,
                    "plugin_lifecycle_installation_id": scope.installation_id,
                    "plugin_lifecycle_expected_revision": scope.expected_revision,
                    "plugin_lifecycle_manifest_checksum": scope.manifest_checksum,
                } if allowed else {}
            ),
        )

    async def authorize_approved_plugin_lifecycle(
        self,
        *,
        context: "ChatExecutionContext",
        scope: "PluginLifecycleApprovalScope",
        approval: Dict[str, Any],
        observed_state: str,
        manifest_checksum: str,
        revision: int,
        disposition: str,
    ) -> PolicyDecision:
        """Evaluate one host-retrieved, action-bound plugin lifecycle grant.

        This method does not execute a plugin and is not reachable through a
        generic PolicyEvaluationRequest. Its approval must be read by
        ApprovalService from the authenticated tenant/user scope; arbitrary
        UI/chat permission claims and supplied receipt dictionaries are never
        an independent grant. PluginService owns the execution admission.
        """
        from ai_karen_engine.core.runtime.plugin_lifecycle_approval import (
            PluginLifecycleApprovalScope,
        )

        now = datetime.now(timezone.utc)
        decision_id = f"policy-plugin-lifecycle-{time.time_ns()}"
        action = (
            "plugin.lifecycle." + scope.action
            if isinstance(scope, PluginLifecycleApprovalScope)
            else "plugin.lifecycle.invalid"
        )
        allowed = False
        reason = PolicyReasonCode.INSUFFICIENT_PERMISSION
        try:
            reason = self._plugin_lifecycle_preflight_reason(
                context=context,
                scope=scope,
                observed_state=observed_state,
                manifest_checksum=manifest_checksum,
                revision=revision,
                disposition=disposition,
            )
            if reason is not PolicyReasonCode.ALLOWED:
                raise PermissionError("Plugin lifecycle preconditions no longer authorize execution")
            if (
                not isinstance(approval, dict)
                or approval.get("status") != "approved"
                or approval.get("tenant_id") != scope.tenant_id
                or approval.get("user_id") != scope.user_id
                or approval.get("conversation_id") != scope.conversation_id
                or approval.get("decided_by") != scope.user_id
                or approval.get("intent") != action
                or approval.get("risk_level") not in {"high", "critical"}
                or not str(approval.get("policy_decision_id") or "").strip()
                or approval.get("request_payload", {}).get(
                    "plugin_lifecycle_scope"
                ) != scope.to_record()
            ):
                raise PermissionError("Plugin lifecycle approval scope is unavailable")
            expiry = approval.get("expires_at")
            if (
                not isinstance(expiry, datetime)
                or expiry.tzinfo is None
                or expiry <= now
            ):
                raise PermissionError("Plugin lifecycle approval expired")
            allowed = True
            reason = PolicyReasonCode.ALLOWED
        except (PermissionError, AttributeError, TypeError, ValueError):
            pass

        constraints: Dict[str, Any] = {}
        if allowed:
            constraints = {
                "authorized_user_id": scope.user_id,
                "authorized_tenant_id": scope.tenant_id,
                "authorized_session_id": scope.session_id,
                "correlation_id": context.correlation_id,
                "plugin_lifecycle_approval_id": approval.get("approval_id"),
                "plugin_lifecycle_installation_id": scope.installation_id,
                "plugin_lifecycle_expected_revision": scope.expected_revision,
                "plugin_lifecycle_manifest_checksum": scope.manifest_checksum,
                "plugin_lifecycle_original_policy_decision_id": approval.get(
                    "policy_decision_id"
                ),
            }
        return PolicyDecision(
            decision_id=decision_id,
            policy_version="v2-lifecycle-bound",
            allowed=allowed,
            reason_codes=[reason],
            allowed_capabilities=[action] if allowed else [],
            denied_capabilities=[] if allowed else [action],
            requires_human_gate=True,
            risk_level="high",
            evaluated_at=time.time(),
            runtime_constraints=constraints,
        )

    async def evaluate(self, request: PolicyEvaluationRequest) -> PolicyDecision:
        """Evaluate once, then retain exact original decision object provenance.

        The identity record belongs to RuntimePolicy, not to ChatRuntime,
        a provider, an SDK or a copyable policy ID. An unapproved decision
        cannot issue model execution permission.
        """
        decision = await self._evaluate_policy_request(request)
        if decision.allowed:
            self._record_issued_model_decision(decision)
        return decision

    @staticmethod
    def _snapshot_issued_model_claims(decision: PolicyDecision) -> tuple[Any, ...]:
        """Freeze the evaluator-issued grants, separate from mutable decisions."""
        return (
            decision.allowed,
            decision.decision_id,
            decision.policy_version,
            deepcopy(decision.runtime_constraints),
            tuple(decision.allowed_capabilities),
            tuple(decision.denied_capabilities),
            deepcopy(decision.provider_constraints),
        )

    def _record_issued_model_decision(self, decision: PolicyDecision) -> None:
        """Private policy-issuer bookkeeping, not an alternative grant path."""
        if not decision.allowed:
            raise PermissionError("runtime_model_policy_issuance_invalid")
        with self._issued_model_lock:
            existing = self._issued_model_decisions.get(decision.decision_id)
            if existing is not None and existing is not decision:
                raise PermissionError("runtime_model_policy_issuance_conflict")
            if existing is decision:
                if not self._matches_issued_model_claims(decision):
                    raise PermissionError("runtime_model_policy_issuance_invalid")
                return
            claim = self._snapshot_issued_model_claims(decision)
            self._issued_model_decisions[decision.decision_id] = decision
            self._issued_model_claims[decision.decision_id] = claim
            finalize(
                decision,
                self._issued_model_claims.pop,
                decision.decision_id,
                None,
            )

    def _matches_issued_model_claims(self, decision: PolicyDecision) -> bool:
        return (
            self._issued_model_decisions.get(decision.decision_id) is decision
            and self._issued_model_claims.get(decision.decision_id)
            == self._snapshot_issued_model_claims(decision)
        )

    def bind_chat_model_policy(
        self,
        *,
        context: "ChatExecutionContext",
        decision: PolicyDecision,
    ) -> None:
        """Prove this authenticated request owns a real issuer-returned decision."""
        from ai_karen_engine.core.runtime.chat_runtime_contract import (
            ChatExecutionContext,
        )

        if not isinstance(context, ChatExecutionContext):
            raise PermissionError("runtime_model_policy_issuance_invalid")
        context.require_authenticated_user()
        constraints = decision.runtime_constraints
        with self._issued_model_lock:
            if (
                not decision.allowed
                or not self._matches_issued_model_claims(decision)
                or constraints.get("authorized_user_id") != context.user_id
                or constraints.get("authorized_tenant_id") != context.tenant_id
                or constraints.get("authorized_session_id") != context.session_id
                or constraints.get("correlation_id") != context.correlation_id
            ):
                raise PermissionError("runtime_model_policy_issuance_invalid")
            original_context = decision.__dict__.get("_issued_model_context")
            bound_decision = context.__dict__.get("_runtime_policy_issuance")
            if original_context is None and bound_decision is None:
                decision.__dict__["_issued_model_context"] = context
                context.__dict__["_runtime_policy_issuance"] = (self, decision)
            elif (
                original_context is not context
                or bound_decision is None
                or bound_decision[0] is not self
                or bound_decision[1] is not decision
            ):
                raise PermissionError("runtime_model_policy_issuance_invalid")

    @staticmethod
    def _respects_issued_provider_scope(
        plan: AuthorizedExecutionPlan, decision: PolicyDecision,
    ) -> bool:
        """Prevent a submitted plan from widening the issuer's provider policy."""
        issued = decision.provider_constraints
        if issued is None:
            return True
        proposed = plan.provider_constraints
        if not isinstance(proposed, dict):
            return False
        eligible = proposed.get("eligible_providers")
        forbidden = proposed.get("forbidden_providers")
        if (
            not isinstance(eligible, (list, tuple, set))
            or not isinstance(forbidden, (list, tuple, set))
            or not all(isinstance(item, str) and item for item in eligible)
            or not all(isinstance(item, str) and item for item in forbidden)
        ):
            return False
        issuer_eligible = set(issued.eligible_providers)
        narrowed_eligible = set(eligible)
        if issuer_eligible and (
            not narrowed_eligible or not narrowed_eligible.issubset(issuer_eligible)
        ):
            return False
        if not set(issued.forbidden_providers).issubset(set(forbidden)):
            return False
        if issued.local_only and proposed.get("local_only") is not True:
            return False
        if not issued.external_allowed and proposed.get("external_allowed") is not False:
            return False
        return True

    def verifies_chat_model_policy(
        self,
        *,
        context: "ChatExecutionContext",
        plan: AuthorizedExecutionPlan,
    ) -> bool:
        """Check actual issuer provenance, original context and budget bounds."""
        binding = context.__dict__.get("_runtime_policy_issuance")
        if not isinstance(binding, tuple) or len(binding) != 2:
            return False
        issuer, decision = binding
        if issuer is not self or not isinstance(decision, PolicyDecision):
            return False
        with self._issued_model_lock:
            if (
                not decision.allowed
                or not self._matches_issued_model_claims(decision)
                or decision.__dict__.get("_issued_model_context") is not context
                or not self._respects_issued_provider_scope(plan, decision)
                or plan.policy_decision_id != decision.decision_id
                or not plan.matches_execution_scope(
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                )
            ):
                return False
            constraints = decision.runtime_constraints
            if (
                constraints.get("authorized_user_id") != context.user_id
                or constraints.get("authorized_tenant_id") != context.tenant_id
                or constraints.get("authorized_session_id") != context.session_id
                or constraints.get("correlation_id") != context.correlation_id
            ):
                return False
            # Source/revision scope must match the issuer's original decision.
            issued_attachments = constraints.get("attachment_references", [])
            selected_scope = plan.resource_scope.get(
                "attachment_references", []
            ) if isinstance(plan.resource_scope, dict) else None
            if (
                selected_scope != issued_attachments
                or (issued_attachments and "data:read" not in plan.allowed_capabilities)
                or plan.resource_scope.get("document_operation_digest")
                != constraints.get("document_operation_digest")
            ):
                return False
            if constraints.get("document_operation_digest") is not None and (
                set(plan.resource_scope) != {"attachment_references", "document_operation_digest"}
                or not {"content-intelligence", "data:read"}.issubset(plan.allowed_capabilities)
                or set(plan.allowed_plugins) != {"content-intelligence"}
            ):
                return False
            # A standalone coordinator must not self-issue tool/plugin/agent
            # grants by modifying a serialized plan before first binding.
            # These are the *actual*, issuer-returned allowlists. Empty means
            # deny all members of that category, never unrestricted access.
            for name in ("allowed_tools", "allowed_plugins", "allowed_agents"):
                requested = getattr(plan, name, None)
                issued = constraints.get(name, [])
                if (
                    not isinstance(requested, (list, tuple, set))
                    or not isinstance(issued, (list, tuple, set))
                    or not all(isinstance(item, str) for item in requested)
                    or not all(isinstance(item, str) for item in issued)
                    or not set(requested).issubset(set(issued))
                ):
                    return False
            if (
                not isinstance(plan.allowed_capabilities, (list, tuple, set))
                or not all(
                    isinstance(item, str)
                    for item in plan.allowed_capabilities
                )
                or not set(plan.allowed_capabilities).issubset(
                    set(decision.allowed_capabilities)
                )
            ):
                return False
            quota = constraints.get("max_model_calls")
            tool_quota = constraints.get("max_tool_calls")
            # External requests may be charged without a model call. A
            # serialized standalone plan cannot mint a larger independent
            # external budget than the original issuer-derived plan grants.
            external_limit = decision.to_authorized_plan().budget.max_external_requests
            external_requests = plan.budget.max_external_requests
            return (
                type(quota) is int
                and quota >= 0
                and type(plan.budget.max_model_calls) is int
                and 0 <= plan.budget.max_model_calls <= quota
                and type(tool_quota) is int
                and tool_quota >= 0
                and type(plan.budget.max_tool_calls) is int
                and 0 <= plan.budget.max_tool_calls <= tool_quota
                and type(external_requests) is int
                and 0 <= external_requests <= external_limit
            )

    async def authorize_generated_text_write(
        self, *, context: "ChatExecutionContext",
        plan: AuthorizedExecutionPlan, meter: Any,
    ) -> None:
        """Authorize the exact direct-chat execution at its write boundary.

        This is an admission check, not a storage receipt or new execution
        grant. Reuse the issuer, original plan, meter and durable session
        witness. No copied or specialist-derived plan may authorize creation.
        """
        from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

        def authorized() -> bool:
            return (
                isinstance(meter, ExecutionBudgetMeter)
                and context.original_runtime_model_plan(meter) is plan
                and self.verifies_chat_model_policy(context=context, plan=plan)
                and set(plan.allowed_capabilities) == {GENERATED_TEXT_ARTIFACT_CAPABILITY}
                and plan.topology is ExecutionTopology.DIRECT
                and not plan.approval_requirements
                and not plan.allowed_tools
                and not plan.allowed_plugins
                and not plan.allowed_agents
                and not plan.reasoning_modes
            )

        if not authorized():
            raise PermissionError("generated_artifact_authority_denied")
        remaining_ms = await meter.remaining_duration_ms()
        if remaining_ms <= 0:
            raise PermissionError("generated_artifact_deadline")
        async with asyncio.timeout(remaining_ms / 1000):
            await context.revalidate_runtime_artifact_write_session()
        if not authorized() or not await meter.check_duration():
            raise PermissionError("generated_artifact_authority_denied")

    async def _evaluate_policy_request(
        self, request: PolicyEvaluationRequest,
    ) -> PolicyDecision:
        """Evaluate capabilities and reasoning modes as distinct policy domains."""
        decision_id = f"policy-{request.tenant_id}-{request.user_id}-{time.time_ns()}"
        policy_version = "v2"
        evaluated_at = time.time()

        if not request.user_id or not request.tenant_id:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.MISSING_IDENTITY],
                denied_capabilities=["all"],
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                evaluated_at=evaluated_at,
            )

        # An ordinary PolicyEvaluationRequest is not a trusted plugin
        # lifecycle approval. Roles, permissions and capability identifiers in
        # this input may originate from ingress. Until the separate, server-
        # bound revision-fenced lifecycle grant is implemented, fail closed.
        # Do not infer authority from admin roles, plugin name or chat prose.
        lifecycle_requested = (
            isinstance(request.action, str)
            and request.action.startswith("plugin.lifecycle.")
        ) or any(
            isinstance(capability, str)
            and capability.startswith("plugin.lifecycle.")
            for capability in request.requested_capabilities
        )
        if lifecycle_requested:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=[
                    cap
                    for cap in request.requested_capabilities
                    if isinstance(cap, str) and cap.startswith("plugin.lifecycle.")
                ] or [str(request.action)],
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                requires_human_gate=True,
                risk_level="high",
                evaluated_at=evaluated_at,
            )

        # WS-04A9E: An ordinary policy evaluation is not evidence of an
        # author's explicit, source-scoped consent. RuntimePolicy must deny
        # both mutations even when roles/permissions/capabilities from the
        # request claim authorization. Only a future host-owned authenticated
        # approval flow may bind a separate non-forgeable issuance decision.
        document_consent_prefix = "writing_style.document_consent."
        document_consent_requested = (
            isinstance(request.action, str)
            and request.action.startswith(document_consent_prefix)
        ) or any(
            isinstance(capability, str)
            and capability.startswith(document_consent_prefix)
            for capability in request.requested_capabilities
        )
        if document_consent_requested:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=[
                    capability
                    for capability in request.requested_capabilities
                    if isinstance(capability, str)
                    and capability.startswith(document_consent_prefix)
                ] or [str(request.action)],
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                requires_human_gate=True,
                risk_level="high",
                evaluated_at=evaluated_at,
            )

        # The host-only Identity Vault resolver requires an exact personal
        # credential execution grant. A general PolicyEvaluationRequest is
        # intentionally NOT that trusted grant source: its capability list,
        # permissions and provider choices can originate at ingress. A later
        # runtime-owned admission step must verify the credential, model and
        # authenticated principal before minting the exact execution grant.
        if "model.personal_key.execute" in request.requested_capabilities:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=["model.personal_key.execute"],
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                risk_level="high",
                evaluated_at=evaluated_at,
            )

        # Transport side effects must never be granted simply because the
        # caller requested a capability or named an installed plugin.
        # Only trusted ingress-authenticated permission context may authorize
        # these high-impact channel actions. Transport adapters cannot supply
        # that context and RuntimePolicy remains the single decision owner.
        requested_channel_actions = {
            capability for capability in request.requested_capabilities
            if isinstance(capability, str) and capability.startswith("channel.")
        }
        missing_channel_permissions = requested_channel_actions.difference(
            request.permissions
        )
        if missing_channel_permissions:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=sorted(missing_channel_permissions),
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                risk_level="high",
                evaluated_at=evaluated_at,
            )

        # Card Studio draft actions are governed by the existing RBAC manager.
        # The requested capability is never itself a grant. This evaluator
        # receives a server-verified principal only from the runtime service.
        requested_card_actions = sorted({
            capability for capability in request.requested_capabilities
            if isinstance(capability, str) and capability.startswith("card_studio.")
        })
        if requested_card_actions:
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            required_permissions = {
                "card_studio.read": Permission.CARD_STUDIO_READ,
                "card_studio.write": Permission.CARD_STUDIO_WRITE,
            }
            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            manager = get_rbac_manager()
            denied = [
                action for action in requested_card_actions
                if action not in required_permissions
                or not manager.has_permission(principal, required_permissions[action])
            ]
            if denied:
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=denied,
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        # Generated artifacts are a dedicated direct-chat operation. Asking
        # for a capability or possessing read access must not confer write
        # authority. Actual principal/session verification at dispatch remains
        # mandatory even after this issuer decision.
        artifact_requested = (
            request.action == GENERATED_TEXT_ARTIFACT_CAPABILITY
            or GENERATED_TEXT_ARTIFACT_CAPABILITY in request.requested_capabilities
        )
        if artifact_requested:
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            manager = get_rbac_manager()
            topology = request.execution_topology
            if (
                request.action != GENERATED_TEXT_ARTIFACT_CAPABILITY
                or set(request.requested_capabilities) != {GENERATED_TEXT_ARTIFACT_CAPABILITY}
                or request.attachment_references
                or not request.session_id
                or not request.correlation_id
                or request.runtime_level is not RuntimeLevel.FULL
                or type(request.max_model_calls) is not int
                or request.max_model_calls < 1
                or request.requested_reasoning_modes
                or request.tool_id or request.plugin_id or request.extension_id
                or any(topology.get(key) for key in (
                    "tool_requirements", "plugin_candidates", "requested_agents",
                    "workflow_id", "agent_delegation", "requires_human_gate",
                    "requires_resumability", "requires_parallel_execution",
                    "graph_required",
                ))
                or not manager.has_permission(principal, Permission.DATA_READ)
                or not manager.has_permission(principal, Permission.ARTIFACT_CREATE_OWN)
            ):
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=[GENERATED_TEXT_ARTIFACT_CAPABILITY],
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        # Freeze the exact selected sources in the issuer's authorization.
        # Client-provided reference IDs never confer read rights by themselves.
        if request.attachment_references:
            from ai_karen_engine.services.database.repositories.conversation_repository import (
                validate_draft_attachment_references,
            )

            try:
                authorized_attachments = validate_draft_attachment_references(
                    request.attachment_references
                )
            except ValueError:
                authorized_attachments = []
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            if (
                not authorized_attachments
                or "data:read" not in request.requested_capabilities
                or not get_rbac_manager().has_permission(principal, Permission.DATA_READ)
            ):
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=["data:read"],
                    evaluated_at=evaluated_at,
                )
        else:
            authorized_attachments = []

        # A scoped document operation is a distinct, explicit read-only grant.
        # Do not infer it from attachments, plugin hints or a generic chat action.
        document_digest = None
        document_requested = (
            request.document_operation is not None
            or request.action == "content-intelligence"
            or bool(authorized_attachments) and (
                "content-intelligence" in request.requested_capabilities
                or "content-intelligence" in (request.execution_topology.get("plugin_candidates") or [])
                or request.plugin_id == "content-intelligence"
                or request.extension_id == "content-intelligence"
            )
        )
        if document_requested:
            from ai_karen_engine.extensions.content_intelligence_sources import (
                runtime_content_operation_digest,
            )

            try:
                topology = request.execution_topology
                if (
                    not authorized_attachments
                    or request.action != "content-intelligence"
                    or set(request.requested_capabilities) != {"content-intelligence", "data:read"}
                    or topology.get("plugin_candidates") != ["content-intelligence"]
                    or request.resource_scope is not None
                    or request.tool_id or request.plugin_id or request.extension_id
                    or not request.session_id or not request.correlation_id
                    or request.runtime_level is not RuntimeLevel.FULL
                    or type(request.max_model_calls) is not int or request.max_model_calls != 0
                    or request.requested_reasoning_modes
                    or any(topology.get(key) for key in (
                        "tool_requirements", "requested_agents", "workflow_id",
                        "agent_delegation", "requires_human_gate", "graph_required",
                        "requires_resumability", "requires_parallel_execution",
                    ))
                ):
                    raise PermissionError("document_operation_not_authorized")
                document_digest = runtime_content_operation_digest(
                    authorized_attachments, request.document_operation,
                )
            except (PermissionError, ValueError, TypeError):
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.RESOURCE_SCOPE_DENIED],
                    denied_capabilities=["content-intelligence"],
                    evaluated_at=evaluated_at,
                )

        # Explorer mutations are owner-only and must not inherit broad data
        # write/delete authority. Unknown future actions default to denial.
        explorer_actions = {
            capability for capability in request.requested_capabilities
            if isinstance(capability, str) and capability.startswith("file_explorer.")
        }
        if explorer_actions:
            from ai_karen_engine.auth.rbac_middleware import (
                FILE_EXPLORER_MUTATION_PERMISSIONS, Permission,
            )

            scope = request.resource_scope
            allowed = (
                len(explorer_actions) == 1
                and request.plugin_id == "file-explorer"
                and request.action == "plugin_execution"
                and isinstance(scope, dict)
                and scope.get("operation") in explorer_actions
                and Permission.DATA_READ.value in request.permissions
                and all(
                    action in FILE_EXPLORER_MUTATION_PERMISSIONS
                    and FILE_EXPLORER_MUTATION_PERMISSIONS[action].value in request.permissions
                    and FILE_EXPLORER_MUTATION_PERMISSIONS[action].value in request.requested_capabilities
                    for action in explorer_actions
                )
            )
            if not allowed:
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=sorted(explorer_actions),
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        # Planner reads expose tenant-private commitments. Requested capability
        # alone never grants access, even for a read-only presentation.
        if "planner.read" in request.requested_capabilities:
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            planner_read_allowed = get_rbac_manager().has_permission(
                principal, Permission.PLANNER_READ,
            )
        else:
            planner_read_allowed = True
        if not planner_read_allowed:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=["planner.read"],
                denied_reasoning_modes=list(request.requested_reasoning_modes),
                evaluated_at=evaluated_at,
            )

        # Personal planner mutations require their own explicit write
        # entitlement. A CORTEX capability request is not an RBAC grant.
        # Service-level authorization and the runtime action attestation
        # remain independent, mandatory checks at execution time.
        requested_planner_mutations = sorted(
            capability
            for capability in request.requested_capabilities
            if capability in {"planner.create", "planner.update"}
        )
        if requested_planner_mutations:
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            if not get_rbac_manager().has_permission(
                principal, Permission.PLANNER_WRITE,
            ):
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=requested_planner_mutations,
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        # An authenticated conversation cannot grant itself recurring-task
        # write authority merely by requesting the capability. The canonical
        # scheduler RBAC entitlement applies equally to chat and HTTP callers.
        if "automation.create" in request.requested_capabilities:
            from ai_karen_engine.auth.models import UserData
            from ai_karen_engine.auth.rbac_middleware import Permission, get_rbac_manager

            principal = UserData(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                roles=list(request.roles),
                permissions=list(request.permissions),
            )
            if not get_rbac_manager().has_permission(
                principal, Permission.SCHEDULER_WRITE,
            ):
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                    denied_capabilities=["automation.create"],
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        forbidden = set(request.forbidden_capabilities)
        for cap in request.requested_capabilities:
            if cap in forbidden:
                return PolicyDecision(
                    decision_id=decision_id,
                    policy_version=policy_version,
                    allowed=False,
                    reason_codes=[PolicyReasonCode.CAPABILITY_CONFLICT],
                    denied_capabilities=list(forbidden),
                    denied_reasoning_modes=list(request.requested_reasoning_modes),
                    evaluated_at=evaluated_at,
                )

        topology_tools = request.execution_topology.get("tool_requirements", []) or []
        if not isinstance(topology_tools, list):
            topology_tools = []
        topology_plugins = request.execution_topology.get("plugin_candidates", []) or []
        if not isinstance(topology_plugins, list):
            topology_plugins = []
        topology_agents = request.execution_topology.get("requested_agents", []) or []
        if not isinstance(topology_agents, list):
            topology_agents = []

        risk_score = float(request.risk_signals.get("score", 0.0) or 0.0)
        risk_categories = request.risk_signals.get("categories", []) or []
        if "credential_access" in risk_categories or "production_impact" in risk_categories:
            risk_score = max(risk_score, 0.7)
        if "destructive_action" in risk_categories:
            risk_score = max(risk_score, 0.5)

        risk_level = "low"
        if risk_score >= 0.8:
            risk_level = "critical"
        elif risk_score >= 0.5:
            risk_level = "high"
        elif risk_score >= 0.2:
            risk_level = "medium"

        reasoning_policy: ReasoningModePolicyResult = authorize_reasoning_modes(
            request.requested_reasoning_modes,
            runtime_level=request.runtime_level,
            risk_level=risk_level,
            max_model_calls=request.max_model_calls,
        )
        reasoning_denial_reasons = {
            mode: list(reasons)
            for mode, reasons in reasoning_policy.denial_reasons.items()
        }

        if risk_score >= 0.8 and "admin" not in request.permissions:
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.INSUFFICIENT_PERMISSION],
                denied_capabilities=["admin", "write", "delete"],
                allowed_reasoning_modes=[],
                denied_reasoning_modes=list(reasoning_policy.requested_modes),
                reasoning_denial_reasons=reasoning_denial_reasons,
                requires_human_gate=True,
                risk_level=risk_level,
                evaluated_at=evaluated_at,
            )

        if (
            (request.tool_id or topology_tools)
            and "admin" not in request.permissions
            and risk_score >= 0.5
        ):
            return PolicyDecision(
                decision_id=decision_id,
                policy_version=policy_version,
                allowed=False,
                reason_codes=[PolicyReasonCode.TOOL_RISK_DENIED],
                denied_capabilities=list(forbidden | {"admin", "write", "delete"}),
                allowed_reasoning_modes=[],
                denied_reasoning_modes=list(reasoning_policy.requested_modes),
                reasoning_denial_reasons=reasoning_denial_reasons,
                risk_level=risk_level,
                evaluated_at=evaluated_at,
            )

        allowed_plugins: List[str] = []
        plugin_candidates = [request.plugin_id, request.extension_id, *topology_plugins]
        for candidate in plugin_candidates:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in allowed_plugins:
                allowed_plugins.append(normalized)

        allowed_tools: List[str] = []
        tool_candidates = [request.tool_id, *topology_tools]
        for candidate in tool_candidates:
            normalized = str(candidate or "").strip()
            if normalized and normalized not in allowed_tools:
                allowed_tools.append(normalized)

        # Candidate IDs are advisory, never permission grants. A caller can
        # request delegation, but only separately verified runtime authority
        # may populate AuthorizedExecutionPlan.allowed_agents.
        allowed_agents: List[str] = []

        runtime_constraints = self._build_runtime_constraints(request.runtime_level)
        runtime_constraints.update(
            {
                "reasoning_modes": list(reasoning_policy.allowed_modes),
                "reasoning_required": bool(reasoning_policy.allowed_modes),
                "max_model_calls": max(0, int(request.max_model_calls)),
                # Chat already uses a count-derived allowance; standalone
                # policy requests retain the canonical ExecutionBudget default.
                "max_tool_calls": (
                    chat_tool_call_limit(topology_tools)
                    if "tool_requirements" in request.execution_topology
                    else ExecutionBudget().max_tool_calls
                ),
                "max_reasoning_steps": max(
                    0, int(request.execution_topology.get("max_steps", 10) or 10)
                ),
                "workflow_id": request.execution_topology.get("workflow_id"),
                "agent_delegation": bool(
                    request.execution_topology.get("agent_delegation", False)
                ),
                "allowed_plugins": allowed_plugins,
                "allowed_tools": allowed_tools,
                "allowed_agents": allowed_agents,
                "attachment_references": [
                    dict(item) for item in authorized_attachments
                ],
                "authorized_user_id": request.user_id,
                "authorized_tenant_id": request.tenant_id,
                "authorized_session_id": request.session_id,
                "correlation_id": request.correlation_id,
            }
        )

        if document_digest is not None:
            runtime_constraints["document_operation_digest"] = document_digest
            runtime_constraints["max_tool_calls"] = 1

        reason_codes = [PolicyReasonCode.POLICY_CHECK_PASSED]
        if reasoning_policy.denied_modes:
            reason_codes.append(PolicyReasonCode.REASONING_MODE_RESTRICTED)

        return PolicyDecision(
            decision_id=decision_id,
            policy_version=policy_version,
            allowed=True,
            reason_codes=reason_codes,
            allowed_capabilities=list(request.requested_capabilities),
            denied_capabilities=list(forbidden),
            allowed_reasoning_modes=list(reasoning_policy.allowed_modes),
            denied_reasoning_modes=list(reasoning_policy.denied_modes),
            reasoning_denial_reasons=reasoning_denial_reasons,
            runtime_constraints=runtime_constraints,
            resource_scope=request.resource_scope,
            provider_constraints=request.provider_constraints,
            risk_level=risk_level,
            evaluated_at=evaluated_at,
        )

    async def check_routing_policy(
        self, state: Dict[str, Any], provider_selection: Dict[str, Any]
    ) -> PolicyCheckResult:
        if not self.config.enable_routing_restrictions:
            return PolicyCheckResult(True, "Routing restrictions disabled")

        current_level = self._get_runtime_level(state)
        provider = provider_selection.get("provider")
        model = provider_selection.get("model")
        provider_constraints = self._resolve_provider_constraints(state)

        if current_level == RuntimeLevel.EMERGENCY:
            allowed_providers = provider_constraints.eligible_providers or ["local"]
            if provider not in allowed_providers:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not allowed in {current_level.value} mode",
                    "critical",
                )
        elif current_level == RuntimeLevel.SAFE:
            trusted_providers = provider_constraints.eligible_providers or ["local"]
            if provider not in trusted_providers:
                return PolicyCheckResult(
                    False,
                    f"Provider '{provider}' not trusted in {current_level.value} mode",
                    "high",
                )
        elif current_level == RuntimeLevel.REDUCED:
            complex_models = provider_constraints.resource_constraints.get(
                "reduced_complex_models", []
            )
            if model and model in complex_models:
                return PolicyCheckResult(
                    False,
                    f"Complex models not allowed in {current_level.value} mode",
                    "medium",
                )

        return PolicyCheckResult(True, "Routing policy check passed")

    async def check_execution_policy(
        self, state: Dict[str, Any], execution_plan: Dict[str, Any]
    ) -> PolicyCheckResult:
        if not self.config.enable_execution_constraints:
            return PolicyCheckResult(True, "Execution constraints disabled")

        current_level = self._get_runtime_level(state)
        requested_capabilities = execution_plan.get("requested_capabilities", [])
        forbidden_capabilities = execution_plan.get("forbidden_capabilities", [])

        forbidden = set(forbidden_capabilities)
        for cap in requested_capabilities:
            if cap in forbidden:
                return PolicyCheckResult(
                    False,
                    f"Required capability '{cap}' is forbidden",
                    "high",
                )

        restricted_capabilities = self._resolve_restricted_capabilities(
            current_level, state
        )
        for cap in requested_capabilities:
            if cap in restricted_capabilities:
                return PolicyCheckResult(
                    False,
                    f"Capability '{cap}' not available in {current_level.value} mode",
                    "high",
                )

        tools_required = execution_plan.get("tool_requirements", []) or execution_plan.get(
            "tools_required", []
        )
        if tools_required:
            tool_check = await self._check_tool_availability(
                tools_required, current_level, state
            )
            if not tool_check.allowed:
                return tool_check

        return PolicyCheckResult(True, "Execution policy check passed")

    async def check_response_policy(
        self, state: Dict[str, Any], response_content: str
    ) -> PolicyCheckResult:
        if not self.config.enable_safety_overrides:
            return PolicyCheckResult(True, "Safety overrides disabled")

        current_level = self._get_runtime_level(state)
        if current_level == RuntimeLevel.EMERGENCY and len(response_content) > 500:
            return PolicyCheckResult(
                False, "Response too long for emergency mode", "critical"
            )
        return PolicyCheckResult(True, "Response policy check passed")

    async def enforce_runtime_level_transition(
        self, current_level: RuntimeLevel, target_level: RuntimeLevel
    ) -> PolicyCheckResult:
        if target_level not in self.level_transitions.get(current_level, []):
            return PolicyCheckResult(
                False,
                f"Cannot transition from {current_level.value} to {target_level.value}",
                "critical",
            )
        return PolicyCheckResult(True, "Runtime level transition allowed")

    def _get_runtime_level(self, state: Dict[str, Any]) -> RuntimeLevel:
        level_str = state.get("runtime_level", self.config.default_level.value)
        try:
            return RuntimeLevel(level_str)
        except ValueError:
            logger.warning("Invalid runtime level '%s', using default", level_str)
            return self.config.default_level

    async def _check_tool_availability(
        self,
        tools: List[str],
        runtime_level: RuntimeLevel,
        state: Dict[str, Any],
    ) -> PolicyCheckResult:
        tool_restrictions = {
            RuntimeLevel.FULL: [],
            RuntimeLevel.REDUCED: ["file_access", "system_command"],
            RuntimeLevel.SAFE: ["file_access", "system_command", "code_execution"],
            RuntimeLevel.EMERGENCY: [
                "file_access",
                "system_command",
                "code_execution",
                "network_access",
            ],
        }
        state_restrictions = state.get("runtime_constraints", {}).get(
            "allowed_tool_types", []
        )
        if state_restrictions and "all" not in state_restrictions:
            combined_restrictions = set(tool_restrictions.get(runtime_level, [])) | {
                tool
                for tool in [
                    "file_access",
                    "system_command",
                    "code_execution",
                    "network_access",
                    "web_search",
                ]
                if tool not in state_restrictions
            }
        else:
            combined_restrictions = set(tool_restrictions.get(runtime_level, []))

        for tool in tools:
            if tool in combined_restrictions:
                return PolicyCheckResult(
                    False,
                    f"Tool '{tool}' not available in {runtime_level.value} mode",
                    "high",
                )
        return PolicyCheckResult(True, "Tool availability check passed")

    def _resolve_restricted_capabilities(
        self, runtime_level: RuntimeLevel, state: Dict[str, Any]
    ) -> List[str]:
        capability_restrictions = {
            RuntimeLevel.FULL: [],
            RuntimeLevel.REDUCED: ["admin", "delete", "write"],
            RuntimeLevel.SAFE: ["admin", "delete", "write", "network_access"],
            RuntimeLevel.EMERGENCY: [
                "admin",
                "delete",
                "write",
                "network_access",
                "code_execution",
            ],
        }
        state_restrictions = state.get("runtime_constraints", {}).get(
            "allowed_capabilities", []
        )
        if state_restrictions:
            return [
                cap
                for cap in capability_restrictions.get(runtime_level, [])
                if cap not in state_restrictions
            ]
        return capability_restrictions.get(runtime_level, [])

    def _resolve_provider_constraints(self, state: Dict[str, Any]) -> ProviderConstraints:
        raw = state.get("provider_constraints", {})
        if isinstance(raw, ProviderConstraints):
            return raw
        if not isinstance(raw, dict):
            return ProviderConstraints()

        eligible = (
            raw.get("emergency_allowed_providers")
            or raw.get("safe_trusted_providers")
            or raw.get("eligible_providers")
            or []
        )
        forbidden = raw.get("forbidden_providers", [])
        local_only = raw.get("local_only", False)
        external_allowed = raw.get("external_allowed", True)
        cap_restrictions = raw.get("capability_restrictions") or raw.get(
            "allowed_capabilities"
        ) or []
        res_constraints = raw.get("resource_constraints", {})

        return ProviderConstraints(
            eligible_providers=list(eligible),
            forbidden_providers=list(forbidden),
            local_only=bool(local_only),
            external_allowed=bool(external_allowed),
            capability_restrictions=list(cap_restrictions),
            resource_constraints=(
                dict(res_constraints) if isinstance(res_constraints, dict) else {}
            ),
        )

    def _build_runtime_constraints(self, runtime_level: RuntimeLevel) -> Dict[str, Any]:
        constraints = {
            RuntimeLevel.FULL: {
                "streaming_enabled": True,
                "max_response_length": 100000,
                "enable_tool_execution": True,
                "allowed_tool_types": ["all"],
            },
            RuntimeLevel.REDUCED: {
                "streaming_enabled": True,
                "max_response_length": 5000,
                "enable_tool_execution": True,
                "allowed_tool_types": [
                    "basic_search",
                    "information_retrieval",
                    "text_analysis",
                ],
            },
            RuntimeLevel.SAFE: {
                "streaming_enabled": False,
                "max_response_length": 2000,
                "enable_tool_execution": True,
                "allowed_tool_types": ["basic_search", "information_retrieval"],
            },
            RuntimeLevel.EMERGENCY: {
                "streaming_enabled": False,
                "max_response_length": 500,
                "enable_tool_execution": False,
                "allowed_tool_types": [],
            },
        }
        return constraints.get(runtime_level, constraints[RuntimeLevel.FULL])

    def apply_runtime_constraints(self, state: Dict[str, Any]) -> Dict[str, Any]:
        current_level = self._get_runtime_level(state)
        state["runtime_constraints"] = self._build_runtime_constraints(current_level)
        state["runtime_constraints"]["level"] = current_level.value
        state["runtime_constraints"]["applied_at"] = state.get("timestamp")
        state["runtime_constraints"]["effective_immediately"] = True
        return state
