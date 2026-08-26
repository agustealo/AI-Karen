"""
Canonical extension errors.

All extension kernel errors inherit from ExtensionError.
"""

from __future__ import annotations

from typing import List, Optional


class ExtensionError(Exception):
    """Base exception for extension kernel errors."""

    def __init__(self, message: str, error_code: str = "extension_error", plugin_id: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code
        self.plugin_id = plugin_id


class ExtensionNotFoundError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(f"Extension '{plugin_id}' not found", error_code="not_found", plugin_id=plugin_id)


class ExtensionNotRegisteredError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(f"Extension '{plugin_id}' is not registered", error_code="not_registered", plugin_id=plugin_id)


class ExtensionDisabledError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(f"Extension '{plugin_id}' is disabled", error_code="disabled", plugin_id=plugin_id)


class ExtensionManifestError(ExtensionError):
    pass


class ExtensionValidationError(ExtensionError):
    pass


class ExtensionPermissionError(ExtensionError):
    def __init__(self, plugin_id: str, missing: list[str]):
        super().__init__(f"Extension '{plugin_id}' missing permissions: {missing}", error_code="permission_denied", plugin_id=plugin_id)


class ExtensionTimeoutError(ExtensionError):
    def __init__(self, plugin_id: str, timeout_ms: int):
        super().__init__(f"Extension '{plugin_id}' timed out after {timeout_ms}ms", error_code="timeout", plugin_id=plugin_id)


class ExtensionExecutionEngineError(ExtensionError):
    pass


class ExtensionPolicyDeniedError(ExtensionError):
    def __init__(self, plugin_id: str, reason_codes: Optional[List[str]] = None):
        super().__init__(
            f"Extension '{plugin_id}' denied by policy",
            error_code="policy_denied",
            plugin_id=plugin_id,
        )
        self.reason_codes = reason_codes or []


class ExtensionTenantDeniedError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(
            f"Extension '{plugin_id}' denied for tenant",
            error_code="tenant_denied",
            plugin_id=plugin_id,
        )


class ExtensionIsolationPolicyViolationError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(
            f"Extension '{plugin_id}' violates isolation policy",
            error_code="isolation_policy_violation",
            plugin_id=plugin_id,
        )


class ExtensionPromptContractDeniedError(ExtensionError):
    def __init__(self, plugin_id: str, detail: str = ""):
        super().__init__(
            f"Extension '{plugin_id}' prompt contract denied: {detail}",
            error_code="prompt_contract_denied",
            plugin_id=plugin_id,
        )


class ExtensionTimeoutClampedError(ExtensionError):
    def __init__(self, plugin_id: str, requested: int, maximum: int):
        super().__init__(
            f"Extension '{plugin_id}' timeout clamped from {requested}ms to {maximum}ms",
            error_code="timeout_clamped",
            plugin_id=plugin_id,
        )


class ExtensionSchemaError(ExtensionError):
    def __init__(self, plugin_id: str, direction: str, detail: str):
        super().__init__(
            f"Extension '{plugin_id}' {direction} schema error: {detail}",
            error_code=f"invalid_{direction}",
            plugin_id=plugin_id,
        )


class ExtensionHumanGateRequiredError(ExtensionError):
    def __init__(self, plugin_id: str, decision_id: str):
        super().__init__(
            f"Extension '{plugin_id}' requires human gate approval (decision={decision_id})",
            error_code="human_gate_required",
            plugin_id=plugin_id,
        )


class ExtensionCredentialDeniedError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(
            f"Extension '{plugin_id}' credential access denied",
            error_code="credential_denied",
            plugin_id=plugin_id,
        )


class ExtensionNetworkDeniedError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(
            f"Extension '{plugin_id}' network access denied",
            error_code="network_denied",
            plugin_id=plugin_id,
        )


class ExtensionFilesystemDeniedError(ExtensionError):
    def __init__(self, plugin_id: str):
        super().__init__(
            f"Extension '{plugin_id}' filesystem access denied",
            error_code="filesystem_denied",
            plugin_id=plugin_id,
        )


__all__ = [
    "ExtensionError",
    "ExtensionNotFoundError",
    "ExtensionNotRegisteredError",
    "ExtensionDisabledError",
    "ExtensionManifestError",
    "ExtensionValidationError",
    "ExtensionPermissionError",
    "ExtensionTimeoutError",
    "ExtensionExecutionEngineError",
    "ExtensionPolicyDeniedError",
    "ExtensionTenantDeniedError",
    "ExtensionIsolationPolicyViolationError",
    "ExtensionPromptContractDeniedError",
    "ExtensionTimeoutClampedError",
    "ExtensionSchemaError",
    "ExtensionHumanGateRequiredError",
    "ExtensionCredentialDeniedError",
    "ExtensionNetworkDeniedError",
    "ExtensionFilesystemDeniedError",
]
