import pytest
from ai_karen_engine.core.expression import ExpressionGateway, ExpressionTask
from ai_karen_engine.core.expression.errors import EngineUnavailableError
from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings

@pytest.mark.asyncio
async def test_gateway_disabled_engine_result():
    settings = ExpressionSettings(active_engine="builtin")
    settings.engines["builtin"] = EngineConfig(enabled=False, type="builtin_provider_engine")
    g = ExpressionGateway(settings)
    with pytest.raises(EngineUnavailableError):
        await g.generate(ExpressionTask(
            task_id='1', kind='chat', messages=[], response_mode='text',
            required_capabilities=[], forbidden_capabilities=[],
        ))
