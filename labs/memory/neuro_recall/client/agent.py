from __future__ import annotations

import asyncio
import argparse
import os
import uuid
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv

if os.getenv("KARI_NEURO_RECALL_LABS_ENABLED", "false").lower() not in {"1", "true", "yes"}:
    raise RuntimeError(
        "NeuroRecall agent is labs-only. Set KARI_NEURO_RECALL_LABS_ENABLED=true to run."
    )

# ---- Logging (colored if available) ----
try:
    import colorlog
    LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
    colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logger = logging.getLogger("neuro_recall.agent")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("neuro_recall.agent")

# ---- MCP (Model Context Protocol) tools ----
from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]

# ---- Kari SR / ICE / LLM (local-first) ----
from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    SoftReasoningEngine, RecallConfig, WritebackConfig
)
from ai_karen_engine.core.reasoning.synthesis.ice_wrapper import (
    PremiumICEWrapper, ICEWritebackPolicy
)
from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils

# ---- Optional OpenAI-compatible local server (RBAC-gated) ----
from openai import AsyncOpenAI  # used only if ENABLE_EXTERNAL_WORKFLOWS=true

# ---------------------------------------------------------------------------
#   Prompts (Prompt-First)
# ---------------------------------------------------------------------------
META_SYSTEM_PROMPT = (
    "You are the META-PLANNER in a hierarchical AI system. A user will ask a "
    "high-level question. First: break the problem into a minimal sequence of executable tasks. "
    "Reply ONLY in JSON with the schema:\n"
    '{ "plan": [ {"id": INT, "description": STRING} … ] }\n\n'
    "After each task is executed by the EXECUTOR you will receive its result.\n"
    "Carefully consider dates/timestamps of sources and events when planning and finalizing.\n"
    "If the final answer is complete, output it with the template:\n"
    "FINAL ANSWER: <answer>\n\n"
    "YOUR FINAL ANSWER should be a number OR as few words as possible OR a comma-separated list; "
    "no extra analysis; no units unless requested. If incomplete, emit a new JSON plan. "
    "Never call tools yourself — that's the EXECUTOR's job.\n"
    "⚠️ Reply with pure JSON only (unless the single FINAL ANSWER line)."
)

EXEC_SYSTEM_PROMPT = (
    "You are the EXECUTOR sub-agent. You receive one task at a time from the planner. "
    "Use available tools via function-calling if needed. Think step by step but respond with the "
    "minimal content needed for the planner. Do NOT output FINAL ANSWER."
)

# ---------------------------------------------------------------------------
#   RBAC / ENV toggles (local-first by default)
# ---------------------------------------------------------------------------
ENABLE_EXTERNAL_WORKFLOWS = os.getenv("ENABLE_EXTERNAL_WORKFLOWS", "false").lower() in ("1", "true", "yes")
DIRECT_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
DIRECT_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")

# Executor/model aliases (descriptive; not coupled to vendors)
DEFAULT_META_MODEL = os.getenv("AGENT_META_MODEL", "kari-meta")
DEFAULT_EXEC_MODEL = os.getenv("AGENT_EXEC_MODEL", "kari-exec")

# Conversation memory cap
MAX_TURNS_MEMORY = int(os.getenv("AGENT_MAX_TURNS", "50"))
# Context cap hint (approx; we avoid strict tokenizer to keep no-Internet constraint)
MAX_CTX_TOKENS_EXEC = int(os.getenv("AGENT_EXEC_MAX_TOK", "8192"))
# Cycles
MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "3"))

# ---------------------------------------------------------------------------
#   Utility helpers
# ---------------------------------------------------------------------------
def _trim_messages(messages: List[Dict[str, Any]], max_items: int = MAX_TURNS_MEMORY) -> List[Dict[str, Any]]:
    """Trim history by count (local, deterministic). Always keep the first system message if present."""
    if len(messages) <= max_items:
        return messages
    sys = messages[0:1]
    rest = messages[1:]
    rest = rest[-(max_items - 1):]
    return sys + rest

def _strip_fences(text: str) -> str:
    """Remove markdown fences and return inner JSON if present."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"{[\s\S]*}", text)
    return m.group(0) if m else text

# ---------------------------------------------------------------------------
#   Local-first LLM backend
# ---------------------------------------------------------------------------
class KariLLMBackend:
    """
    Local-first facade. Uses Kari's LLMUtils/registry by default.
    If ENABLE_EXTERNAL_WORKFLOWS=true, can route to a local OpenAI-compatible server
    (e.g., Ollama/vLLM) with tool-calling support.
    """
    def __init__(self, model_alias: str, role: str):
        self.model_alias = model_alias
        self.role = role
        self.kari_llm: LLMUtils = get_registry().get_active() or LLMUtils()  # type: ignore[assignment,attr-defined]
        self.direct_client: Optional[AsyncOpenAI] = None
        if ENABLE_EXTERNAL_WORKFLOWS:
            self.direct_client = AsyncOpenAI(base_url=DIRECT_BASE_URL, api_key=DIRECT_API_KEY)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
    ) -> Dict[str, Any]:
        # If tools are requested and we’re allowed to use an OpenAI-compatible server:
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
                    }
                    for tc in raw_calls
                ]
            return {"content": msg.content, "tool_calls": tool_calls}

        # Local single-shot synthesis via LLMUtils (no function tools)
        # We flatten recent conversation into a prompt string (prompt-first, no secrets)
        text = "\n".join(f"{m['role'].upper()}: {m.get('content','')}" for m in messages[-8:])
        out = self.kari_llm.generate_text(text, max_tokens=max_tokens)
        return {"content": out, "tool_calls": None}

# ---------------------------------------------------------------------------
#   MCP Tool Hub
# ---------------------------------------------------------------------------
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
                if tool.name in self.sessions:
                    raise RuntimeError(f"Duplicate tool name '{tool.name}' from {script}")
                self.sessions[tool.name] = session
        logger.info("Connected tools: %s", list(self.sessions.keys()))

    async def schema(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cached = {}
        for session in self.sessions.values():
            tools_resp = cached.get(id(session)) or await session.list_tools()
            cached[id(session)] = tools_resp
            for tool in tools_resp.tools:
                out.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })
        return out

    def resolve(self, requested: str) -> str:
        if requested in self.sessions:
            return requested
        for name in self.sessions.keys():
            if requested in name or name in requested:
                return name
        raise KeyError(f"No matching tool for '{requested}'. Available: {list(self.sessions.keys())}")

    async def call(self, tool_name: str, args: Dict[str, Any]) -> str:
        resolved = self.resolve(tool_name)
        session = self.sessions[resolved]
        result = await session.call_tool(resolved, args)
        return str(result.content)

    async def close(self) -> None:
        if self.exit_stack:
            await self.exit_stack.aclose()

# ---------------------------------------------------------------------------
#   Hierarchical Client (Kari-aligned SR/ICE weaving)
# ---------------------------------------------------------------------------
class HierarchicalClient:
    """
    – Meta-planner (prompt-first JSON planning)
    – Executor with SR context weaving + ICE synthesis hint
    – MCP tools (RBAC’d)
    – Local-first LLMs; optional OpenAI-compatible when enabled
    """
    MAX_CYCLES = MAX_CYCLES

    def __init__(self, meta_model: str, exec_model: str):
        # LLM backends
        self.meta_llm = KariLLMBackend(meta_model, role="planner")
        self.exec_llm = KariLLMBackend(exec_model, role="executor")

        # Tools
        self.tools = ToolHub()

        # SR: retrieval + novelty/TTL
        self.sr = SoftReasoningEngine(
            recall=RecallConfig(
                fast_top_k=24, final_top_k=5, recency_alpha=0.65, min_score=0.0, use_dual_embedding=True
            ),
            writeback=WritebackConfig(
                novelty_gate=0.18, default_ttl_seconds=3600.0, long_ttl_seconds=86400.0, max_len_chars=5000
            ),
        )

        # ICE: policy-driven synthesis/cost/latency-aware
        self.ice = PremiumICEWrapper(
            policy=ICEWritebackPolicy(
                base_entropy_threshold=0.30,
                include_confidence=True,
                include_alternatives=False,
            )
        )

        # Conversation memory shared between planner/executor
        self.shared_history: List[Dict[str, Any]] = []

    # ---------- Tool management ----------
    async def connect_to_servers(self, scripts: List[str]):
        await self.tools.connect(scripts)

    async def _tools_schema(self) -> List[Dict[str, Any]]:
        return await self.tools.schema()

    # ---------- Planning / Execution ----------
    async def _plan_once(self, planner_msgs: List[Dict[str, Any]]) -> str:
        msgs = _trim_messages(planner_msgs)
        reply = await self.meta_llm.chat(msgs, max_tokens=1024)
        return reply.get("content") or ""

    async def _exec_task(self, task_id: int, description: str, tools_schema: List[Dict[str, Any]]) -> str:
        # SR context before anything else
        sr_matches = self.sr.query(description, top_k=5)
        sr_context = "\n".join(f"- {m.get('payload',{}).get('text','')}" for m in sr_matches if m.get("payload"))

        # ICE synthesis hint to focus the action
        trace = self.ice.process(f"Task {task_id}: {description}", metadata={"role": "executor"})
        ice_hint = trace.synthesis

        exec_msgs = [
            {"role": "system", "content": EXEC_SYSTEM_PROMPT},
            {"role": "assistant", "content": f"SR Context:\n{sr_context}\n"},
            {"role": "assistant", "content": f"ICE Hint:\n{ice_hint}\n"},
            {"role": "user", "content": f"Task {task_id}: {description}"},
        ]
        exec_msgs = _trim_messages(self.shared_history + exec_msgs)

        # Try with tools if allowed/available; else pure LLM local
        reply = await self.exec_llm.chat(exec_msgs, tools=tools_schema if ENABLE_EXTERNAL_WORKFLOWS else None, max_tokens=1024)

        # Handle tool calls loop (if any)
        if reply.get("tool_calls"):
            for call in reply["tool_calls"]:
                t_name = call["function"]["name"]
                t_args = json.loads(call["function"].get("arguments") or "{}")
                try:
                    result_text = await self.tools.call(t_name, t_args)
                    exec_msgs.extend([
                        {"role": "assistant", "content": None, "tool_calls": [call]},
                        {"role": "tool", "tool_call_id": call.get("id", str(uuid.uuid4())), "name": t_name, "content": result_text},
                    ])
                except Exception as e:
                    exec_msgs.extend([
                        {"role": "assistant", "content": None, "tool_calls": [call]},
                        {"role": "tool", "tool_call_id": call.get("id", str(uuid.uuid4())), "name": t_name, "content": f"[tool error] {e}"},
                    ])

            # Final assistant turn post-tools
            reply = await self.exec_llm.chat(exec_msgs, tools=None, max_tokens=512)

        result_text = (reply.get("content") or "").strip()
        self.shared_history.append({"role": "assistant", "content": f"Task {task_id} result: {result_text}"})
        return result_text

    async def process_query(self, query: str, file: str, task_id: str = "interactive") -> str:
        tools_schema = await self._tools_schema()
        self.shared_history = []
        self.shared_history.append({"role": "user", "content": f"{query}\ntask_id: {task_id}\nfile_path: {file}\n"})
        planner_msgs = [{"role": "system", "content": META_SYSTEM_PROMPT}] + self.shared_history

        final = ""
        plan_text = ""
        for _ in range(self.MAX_CYCLES):
            plan_text = await self._plan_once(planner_msgs)
            self.shared_history.append({"role": "assistant", "content": plan_text})

            if plan_text.startswith("FINAL ANSWER:"):
                final = plan_text[len("FINAL ANSWER:"):].strip()
                break

            # parse plan JSON
            try:
                tasks = json.loads(_strip_fences(plan_text))["plan"]
            except Exception as e:
                final = f"[planner error] {e}: {plan_text}"
                break

            # execute tasks
            for task in tasks:
                desc = str(task.get("description", ""))
                tid = int(task.get("id", 0))
                await self._exec_task(tid, desc, tools_schema)

            # loop back with enriched shared_history
            planner_msgs = [{"role": "system", "content": META_SYSTEM_PROMPT}] + self.shared_history

        return final or plan_text.strip()

    async def cleanup(self):
        await self.tools.close()

# ---------------------------------------------------------------------------
#   CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="AgentFly — Kari SR/ICE aligned (local-first)")
    parser.add_argument("-q", "--question", type=str, help="Your question")
    parser.add_argument("-f", "--file", type=str, default="", help="Optional file path")
    parser.add_argument("-m", "--meta_model", type=str, default=DEFAULT_META_MODEL, help="Meta-planner model alias")
    parser.add_argument("-e", "--exec_model", type=str, default=DEFAULT_EXEC_MODEL, help="Executor model alias")
    parser.add_argument("-s", "--servers", type=str, nargs="*", default=[
        "../server/code_agent.py",
        "../server/craw_page.py",
        "../server/documents_tool.py",
        "../server/excel_tool.py",
        "../server/image_tool.py",
        "../server/math_tool.py",
        "../server/search_tool.py",
        "../server/video_tool.py",
    ], help="Paths of MCP tool server scripts")
    return parser.parse_args()

async def run_single_query(client: HierarchicalClient, question: str, file_path: str):
    answer = await client.process_query(question, file_path, str(uuid.uuid4()))
    print("\nFINAL ANSWER:", answer)

async def main_async(args):
    load_dotenv()
    client = HierarchicalClient(args.meta_model, args.exec_model)
    await client.connect_to_servers(args.servers)
    try:
        if args.question:
            await run_single_query(client, args.question, args.file)
        else:
            print("Enter 'exit' to quit.")
            while True:
                q = input("\nQuestion: ").strip()
                if q.lower() in {"exit", "quit", "q"}:
                    break
                f = input("File path (optional): ").strip()
                await run_single_query(client, q, f)
    finally:
        await client.cleanup()

if __name__ == "__main__":
    arg_ns = parse_args()
    asyncio.run(main_async(arg_ns))
