import pytest

from ai_karen_engine.core.expression.engines.builtin_provider_engine import BuiltinProviderEngine
from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.model_runtime.providers.transformers_runtime import TransformersRuntime
from ai_karen_engine.integrations.llm_utils import ProviderNotAvailable


class _DummyProvider:
    def __init__(self, text, model="auto"):
        self._text=text
        self.model=model
    def generate_text(self, prompt, **kwargs):
        return self._text


@pytest.mark.asyncio
async def test_builtin_engine_vllm_failure_falls_back_to_transformers_with_attempts(monkeypatch):
    def _get_provider(pid, model=None):
        if pid == "builtin_vllm":
            raise ProviderNotAvailable("down")
        return _DummyProvider("transformers live proof", model="gpt2")

    monkeypatch.setattr("ai_karen_engine.integrations.llm_registry.get_provider", _get_provider)
    engine = BuiltinProviderEngine()
    task = ExpressionTask(task_id="t1", kind="chat", messages=[{"content":"hi"}], response_mode="chat", required_capabilities=["chat"], forbidden_capabilities=[], request_id="r1", correlation_id="c1", preferred_provider="builtin_vllm", preferred_model="auto")
    result = await engine.generate(task)
    assert result.text == "transformers live proof"
    assert result.provider == "builtin_transformers"
    assert result.runtime_engine == "transformers"
    assert result.metadata["response_source"] == "fallback_provider_runtime"
    assert any(a["status"] == "failed" for a in result.metadata["provider_attempts"])


def test_transformers_runtime_raises_when_no_real_generation_available():
    runtime = TransformersRuntime()
    runtime._transformers_available = False
    runtime._pipeline = None
    with pytest.raises(ProviderNotAvailable):
        runtime.generate("hello")
