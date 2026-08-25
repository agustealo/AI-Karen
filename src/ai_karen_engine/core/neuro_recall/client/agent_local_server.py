"""
AgentFly — Kari-aligned Hierarchical Agent (SR/ICE Integrated)

Design:
- META-PLANNER (prompt-first): decomposes query into minimal tasks
- EXECUTOR: executes tasks with MCP tools and SR context
- SR: SoftReasoningEngine (dual-embedding recall + novelty/TTL heuristics)
- ICE: PremiumICEWrapper (policy-driven synthesis, cost/latency-aware)
- Local-first: LLMUtils + registry; external providers only if enabled

Observability:
- Prometheus counters/histograms (graceful if not installed)
- Optional OpenTelemetry spans (if your stack enables it)

Security/RBAC:
- External tool/LLM usage gated by ENV flags
- Audit hook piped from ICE policy

Author: Kari CORTEX v3.2
"""

from __future__ import annotations

import os
import re
import uuid
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

if os.getenv("KARI_NEURO_RECALL_LABS_ENABLED", "false").lower() not in {"1", "true", "yes"}:
    raise RuntimeError(
        "NeuroRecall local server agent is labs-only. Set KARI_NEURO_RECALL_LABS_ENABLED=true to run."
    )

# ----- Logging (colored if available) -----
try:
    import colorlog
    LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
    colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logger = logging.getLogger("agentfly")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("agentfly")

# ----- Prometheus (graceful if missing) -----
try:
    from prometheus_client import Counter, Histogram  # type: ignore
    METRICS = True
    M_LAT = Histogram("agentfly_cycle_latency_ms", "Cycle latency (ms)", buckets=(50,100,200,400,800,1600,3200))
    M_TASK = Counter("agentfly_tasks_total", "Tasks executed", labelnames=("kind",))
    M_TOOL = Counter("agentfly_tool_calls_total", "Tool calls", labelnames=("name", "status"))
except Exception:  # pragma: no cover
    METRICS = False
    class _Noop:
        def labels(self, *_, **__): return self
        def observe(self, *_): pass
        def inc(self, *_): pass
    M_LAT = M_TASK = M_TOOL = _Noop()

# ----- MCP client (tools) -----
from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]

# ----- Kari: SR / ICE / LLM -----
from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    SoftReasoningEngine, RecallConfig, WritebackConfig
)
from ai_karen_engine.core.reasoning.synthesis.ice_wrapper import (
    PremiumICEWrapper, ICEWritebackPolicy
)
from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils

# ----- Local/Direct model backends (optional) -----
from openai import AsyncOpenAI  # For local OpenAI-compatible servers only


# -------------------------------
# Prompt Templates (Prompt-First)
# -------------------------------

META_SYSTEM_PROMPT = (
    "You are the META-PLANNER in a hierarchical AI system. A user will ask a "
    "high-level question. First: break the problem into a minimal sequence of executable tasks. "
    "Reply ONLY in JSON with the schema:\n"
    '{ "plan": [ {"id": INT, "description": STRING} ... ] }\n\n'
    "After each task is executed by the EXECUTOR you will receive its result.\n"
    "Carefully consider dates/timestamps of sources and events when planning and finalizing.\n"
    "If the final answer is complete, output it with the template:\n"
    "FINAL ANSWER: <answer>\n\n"
    "YOUR FINAL ANSWER must strictly follow the question requirements, minimal words/numbers, "
    "no extra analysis. If incomplete, output a new JSON plan for remaining work.\n"
    "Never call tools yourself — that's the EXECUTOR's job.\n"
    "⚠️ Reply with pure JSON only, unless it is the FINAL ANSWER line."
)

EXEC_SYSTEM_PROMPT = (
    "You are the EXECUTOR. You receive one task at a time from the planner. "
    "Use available tools via function calling if needed. Think step by step but reply with the "
    "minimal content needed for the planner. Do NOT output FINAL ANSWER."
)

# -------------------------------
# RBAC / ENV Toggles
# -------------------------------
ENABLE_EXTERNAL_WORKFLOWS = os.getenv("ENABLE_EXTERNAL_WORKFLOWS", "false").lower() in ("1","true","yes")
DIRECT_BASE_URL = os.getenv("DIRECT_BASE_URL", "http://localhost:11434/v1")  # example ollama/openai-compatible
DIRECT_API_KEY = os.getenv("DIRECT_API_KEY", "EMPTY")

MAX_TURNS_MEMORY = 50
MAX_CTX_TOKENS_EXEC = int(os.getenv("AGENT_EXEC_MAX_TOK", "8192"))
MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "3"))

DEFAULT_META_MODEL = os.getenv("AGENT_META_MODEL", "local-meta")
DEFAULT_EXEC_MODEL = os.getenv("AGENT_EXEC_MODEL", "local-exec")


# -------------------------------
# Utility: message trimming (token-approx by words for local-first)
# -------------------------------
def _trim_messages(messages: List[Dict[str, Any]], max_items: int = MAX_TURNS_MEMORY) -> List[Dict[str, Any]]:
    """Keep most recent messages within memory cap, always preserving first system msg."""
    if len(messages) <= max_items:
        return messages
    sys = messages[0:1]
    rest = messages[1:]
    rest = rest[-(max_items-1):]
    return sys + rest


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"{[\s\S]*}", text)
    return m.group(0) if m else text


# -------------------------------
# Backends: Local-first LLM facade
# -------------------------------

class KariLLMBackend:
    """Local-first facade. Uses LLMUtils/registry; optionally routes to a local OpenAI-compatible server
    when ENABLE_EXTERNAL_WORKFLOWS is true and model name matches a policy.
    """

    def __init__(self, model_alias: str, role: str):
        self.role = role
        self.model_alias = model_alias
        # Try Kari registry first
        self.kari_llm: Optional[LLMUtils] = get_registry().get_active() or LLMUtils()  # type: ignore[assignment,attr-defined]
        self.direct_client: Optional[AsyncOpenAI] = None

        if ENABLE_EXTERNAL_WORKFLOWS:
            # Only spin direct client if explicitly allowed
            self.direct_client = AsyncOpenAI(base_url=DIRECT_BASE_URL, api_key=DIRECT_API_KEY)

    async def chat(self, messages: List[Dict[str, Any]], *, max_tokens: int = 1024,
                   tools: Optional[List[Dict[str, Any]]] = None,
                   tool_choice: Optional[str] = "auto") -> Dict[str, Any]:
        """Minimal wrapper supporting non-stream chat and optional tool schema."""
        # If tools are provided and external workflows enabled, try local OpenAI-compatible
        if tools and self.direct_client:
            payload = {
                "model": self.model_alias,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": tool_choice or "auto",
            }
            resp = await self.direct_client.chat.completions.create(**payload)
            msg = resp.choices[0].message
            raw_calls = getattr(msg, "tool_calls", None)
            tool_calls = None
            if raw_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    } for tc in raw_calls
                ]
            return {"content": msg.content, "tool_calls": tool_calls}

        # Otherwise, use Kari's LLMUtils in prompt-first single-shot mode (no tools)
        # Synthesize a simple prompt from last user + assistant messages
        text = "\n".join(
            [f"{m['role'].upper()}: {m.get('content','')}" for m in messages[-8:]]
        )
        out = self.kari_llm.generate_text(text, max_tokens=max_tokens)
        return {"content": out, "tool_calls": None}


# -------------------------------
# MCP Tool Hub
# -------------------------------

class ToolHub:
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = None

    async def connect(self, scripts: List[str]) -> None:
        from contextlib import AsyncExitStack
        self.exit_stack = AsyncExitStack()
        for script in scripts:
            path = Path(script)
            cmd = "python" if path.suffix == ".py" else "node"
            params = StdioServerParameters(command=cmd, args=[str(path)])
            stdio, write = await self.exit_stack.enter_async_context(stdio_client(params))
            session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
            await session.initialize()
            tools = await session.list_tools()
            for tool in tools.tools:
                name = tool.name
                if name in self.sessions:
                    raise RuntimeError(f"Duplicate tool '{name}' from {script}")
                self.sessions[name] = session
        logger.info("Connected MCP tools: %s", list(self.sessions.keys()))

    async def tools_schema(self) -> List[Dict[str, Any]]:
        result, cached = [], {}
        for session in self.sessions.values():
            tools_resp = cached.get(id(session)) or await session.list_tools()
            cached[id(session)] = tools_resp
            for tool in tools_resp.tools:
                result.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })
        return result

    def resolve(self, requested: str) -> str:
        if requested in self.sessions:
            return requested
        # simple contains fallback
        for name in self.sessions.keys():
            if requested in name or name in requested:
                return name
        raise KeyError(f"No tool named like '{requested}'. Available: {list(self.sessions.keys())}")

    async def call(self, tool_name: str, args: Dict[str, Any]) -> str:
        session = self.sessions[self.resolve(tool_name)]
        result = await session.call_tool(tool_name, args)
        return str(result.content)

    async def close(self) -> None:
        if self.exit_stack:
            await self.exit_stack.aclose()


# -------------------------------
# AgentFly (Kari-aligned)
# -------------------------------

class AgentFly:
    """Hierarchical agent with SR context weaving and ICE synthesis."""
    def __init__(
        self,
        meta_model: str = DEFAULT_META_MODEL,
        exec_model: str = DEFAULT_EXEC_MODEL,
        sr: Optional[SoftReasoningEngine] = None,
        ice: Optional[PremiumICEWrapper] = None,
    ):
        # LLMs
        self.meta_llm = KariLLMBackend(meta_model, role="planner")
        self.exec_llm = KariLLMBackend(exec_model, role="executor")

        # Tools
        self.tools = ToolHub()

        # SR (retrieval + novelty)
        self.sr = sr or SoftReasoningEngine(
            recall=RecallConfig(fast_top_k=24, final_top_k=5, recency_alpha=0.65, min_score=0.0, use_dual_embedding=True),
            writeback=WritebackConfig(novelty_gate=0.18, default_ttl_seconds=3600.0, long_ttl_seconds=86400.0, max_len_chars=5000),
        )

        # ICE (policy synthesis + writeback gate is handled by ICE up the stack if needed)
        self.ice = ice or PremiumICEWrapper(
            policy=ICEWritebackPolicy(
                base_entropy_threshold=0.30,
                include_confidence=True,
                include_alternatives=False,
                actor_role="agentfly",
            )
        )

        self.shared_history: List[Dict[str, Any]] = []  # planner/executor dialog memory (bounded)

    async def connect_tools(self, scripts: List[str]) -> None:
        await self.tools.connect(scripts)

    async def _plan(self, question: str, file: str, task_id: str) -> str:
        msgs = [{"role": "system", "content": META_SYSTEM_PROMPT}] + self.shared_history + [
            {"role": "user", "content": f"{question}\ntask_id: {task_id}\nfile_path: {file}\n"}
        ]
        msgs = _trim_messages(msgs)
        out = await self.meta_llm.chat(msgs, max_tokens=1024)
        return out["content"] or ""

    async def _exec_one(self, task_id: int, description: str, tools_schema: List[Dict[str, Any]]) -> str:
        """Execute a single task, weaving SR context before tool use."""
        # SR context recall (pre-tool)
        sr_matches = self.sr.query(description, top_k=5)
        context = "\n".join(f"- {m.get('payload',{}).get('text','')}" for m in sr_matches if m.get("payload"))

        # ICE synthesis for a crisp execution hint (policy-driven)
        trace = self.ice.process(f"Task {task_id}: {description}", metadata={"role": "executor"})
        exec_hint = trace.synthesis

        # Build executor messages (context → hint → instruction)
        exec_msgs = [
            {"role": "system", "content": EXEC_SYSTEM_PROMPT},
            {"role": "assistant", "content": f"SR Context:\n{context}\n"},
            {"role": "assistant", "content": f"ICE Hint:\n{exec_hint}\n"},
            {"role": "user", "content": f"Task {task_id}: {description}"},
        ]
        exec_msgs = _trim_messages(self.shared_history + exec_msgs)

        # Try tools (if available via external workflow), else plain LLM
        reply = await self.exec_llm.chat(exec_msgs, tools=tools_schema, max_tokens=1024)
        if reply.get("tool_calls"):
            # execute tool calls in a simple loop
            for call in reply["tool_calls"]:
                name = call["function"]["name"]
                args = json.loads(call["function"].get("arguments") or "{}")
                try:
                    result_text = await self.tools.call(name, args)
                    M_TOOL.labels(name=name, status="ok").inc() if METRICS else None
                    # feed back to the conversation
                    exec_msgs.extend([
                        {"role": "assistant", "content": None, "tool_calls": [call]},
                        {"role": "tool", "tool_call_id": call.get("id", str(uuid.uuid4())), "name": name, "content": result_text},
                    ])
                except Exception as e:
                    M_TOOL.labels(name=name, status="error").inc() if METRICS else None
                    exec_msgs.extend([
                        {"role": "assistant", "content": None, "tool_calls": [call]},
                        {"role": "tool", "tool_call_id": call.get("id", str(uuid.uuid4())), "name": name, "content": f"[tool error] {e}"},
                    ])

            # final assistant turn (no more tool calls)
            reply = await self.exec_llm.chat(exec_msgs, tools=None, max_tokens=512)

        result_text = (reply.get("content") or "").strip()
        self.shared_history.append({"role": "assistant", "content": f"Task {task_id} result: {result_text}"})
        M_TASK.labels(kind="exec").inc() if METRICS else None
        return result_text

    async def ask(self, question: str, file: str = "", task_id: Optional[str] = None) -> str:
        """Top-level entrypoint."""
        tools_schema = await self.tools.tools_schema()
        self.shared_history = []
        task_id = task_id or str(uuid.uuid4())

        # Initial user turn
        self.shared_history.append({"role": "user", "content": f"{question}\ntask_id: {task_id}\nfile_path: {file}\n"})

        final_answer = ""
        for cycle in range(MAX_CYCLES):
            t0 = time.time()

            plan = await self._plan(question, file, task_id)
            self.shared_history.append({"role": "assistant", "content": plan})

            if plan.startswith("FINAL ANSWER:"):
                final_answer = plan[len("FINAL ANSWER:"):].strip()
                break

            # Parse plan JSON
            try:
                tasks = json.loads(_strip_fences(plan))["plan"]
            except Exception as e:
                final_answer = f"[planner error] {e}: {plan}"
                break

            # Execute tasks
            for t in tasks:
                desc = str(t.get("description",""))
                tid = int(t.get("id", 0))
                await self._exec_one(tid, desc, tools_schema)

            if METRICS:
                M_LAT.observe((time.time() - t0) * 1000.0)

        return final_answer or plan.strip()

    async def close(self) -> None:
        await self.tools.close()


# -------------------------------
# CLI Entrypoint
# -------------------------------

async def _main():
    load_dotenv()
    import argparse
    parser = argparse.ArgumentParser(description="AgentFly — Kari SR/ICE aligned")
    parser.add_argument("-q", "--question", type=str, help="Your question")
    parser.add_argument("-f", "--file", type=str, default="", help="Optional file path")
    parser.add_argument("-m", "--meta_model", type=str, default=DEFAULT_META_MODEL, help="Meta-planner model alias")
    parser.add_argument("-e", "--exec_model", type=str, default=DEFAULT_EXEC_MODEL, help="Executor model alias")
    parser.add_argument("-s", "--servers", type=str, nargs="*", default=[
        "../server/code_agent.py",
        "../server/documents_tool.py",
        "../server/image_tool.py",
        "../server/math_tool.py",
        "../server/ai_crawl.py",
        "../server/serp_search.py",
    ], help="Paths of tool server scripts")
    args = parser.parse_args()

    agent = AgentFly(meta_model=args.meta_model, exec_model=args.exec_model)
    await agent.connect_tools(args.servers)

    try:
        if args.question:
            ans = await agent.ask(args.question, file=args.file)
            print("\nFINAL ANSWER:", ans)
        else:
            print("Interactive mode. Type 'exit' to quit.")
            while True:
                q = input("\nQuestion: ").strip()
                if q.lower() in {"exit","quit","q"}:
                    break
                f = input("File path (optional): ").strip()
                ans = await agent.ask(q, file=f)
                print("\nFINAL ANSWER:", ans)
    finally:
        await agent.close()

if __name__ == "__main__":
    asyncio.run(_main())
