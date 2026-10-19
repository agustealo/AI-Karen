"""Optional real Deep Agents package compatibility smoke.

Install `pip install -r requirements/deepagents.txt` before running this test.
It uses a deterministic in-process LangChain model, not any network provider.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pinned_deepagents_constructs_and_runs_in_memory_graph():
    deepagents = pytest.importorskip("deepagents")
    from deepagents.backends import StateBackend
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    class ToolCapableTestModel(FakeListChatModel):
        def bind_tools(self, tools, **kwargs):
            del tools, kwargs
            return self

    model = ToolCapableTestModel(responses=["Research task complete."])
    graph = deepagents.create_deep_agent(
        model=model,
        tools=[],
        system_prompt="Only answer from the provided question.",
        subagents=[{
            "name": "general-purpose",
            "description": "A bounded in-memory helper",
            "model": model,
            "tools": [],
        }],
        backend=StateBackend(),
        middleware=[TodoListMiddleware()],
        skills=[],
        memory=[],
        checkpointer=None,
    )
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": "Summarize the task."}]},
        config={"recursion_limit": 12},
    )
    assert result["messages"][-1].content == "Research task complete."
