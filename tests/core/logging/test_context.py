import pytest
import asyncio
from ai_karen_engine.core.logging.context import (
    get_log_context,
    set_log_context,
    bind_log_context,
    RuntimeLogContext,
    clear_log_context,
)

@pytest.mark.asyncio
async def test_context_isolation():
    """Verify context does not bleed across async tasks."""
    
    async def task_a():
        set_log_context(RuntimeLogContext(correlation_id="A"))
        await asyncio.sleep(0.01)
        assert get_log_context().correlation_id == "A"

    async def task_b():
        set_log_context(RuntimeLogContext(correlation_id="B"))
        await asyncio.sleep(0.005)
        assert get_log_context().correlation_id == "B"

    await asyncio.gather(task_a(), task_b())

def test_bind_context():
    clear_log_context()
    bind_log_context(correlation_id="123", custom_field="abc")
    ctx = get_log_context()
    assert ctx.correlation_id == "123"
    assert ctx.extra["custom_field"] == "abc"

def test_to_dict():
    ctx = RuntimeLogContext(correlation_id="CID", user_id="U1")
    ctx.extra["foo"] = "bar"
    d = ctx.to_dict()
    assert d["correlation_id"] == "CID"
    assert d["user_id"] == "U1"
    assert d["foo"] == "bar"
    assert "request_id" not in d
