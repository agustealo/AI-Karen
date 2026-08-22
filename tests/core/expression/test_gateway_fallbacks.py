import pytest
import asyncio
from unittest.mock import MagicMock, patch
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.contracts import ExpressionTask, ExpressionResult
from ai_karen_engine.core.expression.settings import ExpressionSettings, EngineConfig

@pytest.mark.asyncio
async def test_gateway_fallback_loop():
    # Setup settings with two enabled engines
    settings = ExpressionSettings(
        active_engine="builtin",
        engine_fallback_order=["builtin", "openai_compatible_local"]
    )
    settings.engines["builtin"] = EngineConfig(enabled=True, type="builtin_provider_engine", fallback_eligible=True)
    settings.engines["openai_compatible_local"] = EngineConfig(enabled=True, type="openai_compatible")
    
    gateway = ExpressionGateway(settings=settings)
    task = ExpressionTask(
        task_id="test_fallback",
        kind="chat",
        messages=[{"role": "user", "content": "hello"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[]
    )
    
    # Mock engines
    mock_builtin = MagicMock()
    mock_builtin.generate = MagicMock(side_effect=Exception("Builtin failed"))
    
    mock_openai = MagicMock()
    mock_openai.generate = MagicMock(return_value=asyncio.Future())
    mock_openai.generate.return_value.set_result(ExpressionResult(
        task_id="test_fallback",
        text="Success from OpenAI",
        provider="ollama",
        model="llama3",
        engine_id="openai_compatible_local",
        engine_mode="openai_compatible",
        runtime_engine="openai_compatible",
        response_source="openai_compatible_engine",
        attempts=[],
        skipped=[],
        latency_ms=10.0,
        degraded=False
    ))
    
    def get_engine_mock(engine_id, engine_type):
        if engine_id == "builtin":
            return mock_builtin
        if engine_id == "openai_compatible_local":
            return mock_openai
        return MagicMock()

    with patch("ai_karen_engine.core.expression.gateway.get_engine", side_effect=get_engine_mock):
        result = await gateway.generate(task)
        
        assert result.text == "Success from OpenAI"
        assert result.engine_id == "openai_compatible_local"
        assert result.metadata["fallback_level"] == 1
        assert any(s["engine_id"] == "builtin" and s["reason"] == "exception" for s in result.metadata["skipped_engines"])

@pytest.mark.asyncio
async def test_gateway_emergency_fallback():
    # Setup settings where all fail
    settings = ExpressionSettings(active_engine="builtin")
    settings.engines["builtin"] = EngineConfig(enabled=True, type="builtin_provider_engine")
    
    gateway = ExpressionGateway(settings=settings)
    task = ExpressionTask(
        task_id="test_emergency",
        kind="chat",
        messages=[{"role": "user", "content": "hello"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[]
    )
    
    with patch("ai_karen_engine.core.expression.gateway.get_engine") as mock_get_engine:
        mock_builtin = MagicMock()
        mock_builtin.generate = MagicMock(side_effect=Exception("Fatal fail"))
        
        mock_disabled = MagicMock()
        mock_disabled.generate = MagicMock(return_value=asyncio.Future())
        mock_disabled.generate.return_value.set_result(ExpressionResult(
            task_id="test_emergency",
            text="Expression engine is disabled.",
            provider="disabled",
            model=None,
            engine_id="disabled",
            engine_mode="disabled",
            runtime_engine=None,
            response_source="engine_disabled",
            attempts=[],
            skipped=[],
            latency_ms=0.0,
            degraded=True
        ))
        
        def side_effect(engine_id, engine_type):
            if engine_id == "builtin": return mock_builtin
            return mock_disabled
            
        mock_get_engine.side_effect = side_effect
        
        result = await gateway.generate(task)
        
        assert result.engine_id == "disabled"
        assert result.degraded is True
