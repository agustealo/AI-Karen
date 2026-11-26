"""Legacy provider exception imports preserve one sanitized error identity."""

from ai_karen_engine.core.model_runtime.provider_contracts import ProviderProcessingError
from ai_karen_engine.core.model_runtime.routing.llm_router_service import (
    ProviderProcessingError as RouterError,
)
from ai_karen_engine.core.runtime.provider_runtime import (
    ProviderProcessingError as RuntimeErrorAlias,
)


def test_provider_processing_error_accepts_error_list():
    secret = "sk-private-provider-credential"
    cause = RuntimeError(f"Authorization: Bearer {secret}")
    err = RouterError("ollama", [cause])
    assert RouterError is RuntimeErrorAlias is ProviderProcessingError
    assert "ollama failed after" in str(err)
    assert "RuntimeError" in str(err)
    assert secret not in str(err)
    assert secret not in repr(err)
    assert err.last_error is cause
    assert err.errors == [cause]
