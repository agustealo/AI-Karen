"""
Canonical extension errors.

All extension kernel errors inherit from ExtensionError.
"""

from __future__ import annotations


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
]
