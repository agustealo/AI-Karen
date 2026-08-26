from __future__ import annotations

# ==============================
#  AgentFly — Kari SR+ICE Runner
#  Local-first evaluator that:
#   • Plans/executes via hierarchical agents
#   • Grounds each task with SoftReasoningEngine (SR) recall
#   • Injects ICE synthesis hints (PremiumICEWrapper)
#   • Uses MCP tool servers (RBAC’d)
#   • Judges answers (local-first; externals opt-in)
#   • Writes dataset + SR memories for continual learning
# ==============================

import asyncio
import json
import logging
import os
import re
import sys
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

if os.getenv("KARI_NEURO_RECALL_LABS_ENABLED", "false").lower() not in {"1", "true", "yes"}:
    raise RuntimeError(
        "NeuroRecall CBR runner is labs-only. Set KARI_NEURO_RECALL_LABS_ENABLED=true to run."
    )

# ---- Logging (colored if available) ----
try:
    import colorlog
    LOG_FORMAT = '%(log_color)s%(levelname)-8s%(reset)s %(message)s'
    colorlog.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logger = logging.getLogger("neuro_recall.runner")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("neuro_recall.runner")

# ---- MCP (Model Context Protocol) tools ----
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]

# ---- Local-first Kari engines (SR + ICE + LLM) ----
from ai_karen_engine.core.reasoning.soft_reasoning.engine import (
    SoftReasoningEngine,
    RecallConfig,
    WritebackConfig,
)
from ai_karen_engine.core.reasoning.synthesis.ice_wrapper import (
    PremiumICEWrapper,
    ICEWritebackPolicy,
)
from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry
from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils

# ---- Optional OpenAI-compatible client for gated externals (Ollama/vLLM/etc) ----
from openai import AsyncOpenAI

# ==============================
#  Configuration (env + sane defaults)
# ==============================
DATASET_PATH = os.getenv("DEEPRESEARCHER_JSONL", "../data/deepresearcher.jsonl")
RESULT_OUT = os.getenv("RESULT_OUT", "../result/result_round_0.jsonl")
MEMORY_JSONL_PATH = os.getenv("MEMORY_JSONL_PATH", "../memory/dummy_memo.jsonl")

# Hierarchy models (aliases; not vendor-locked)
META_MODEL = os.getenv("META_MODEL", "kari-meta")
EXEC_MODEL = os.getenv("EXEC_MODEL", "kari-exec")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "kari-judge")  # local-first; can be remapped

# External workflows toggle (function tools, remote LLMs)
ENABLE_EXTERNAL_WORKFLOWS = os.getenv("ENABLE_EXTERNAL_WORKFLOWS", "false").lower() in ("1", "true", "yes")

# OpenAI-compatible endpoint (local vLLM/Ollama/OpenRouter/etc)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "EMPTY")

# Limits
MAX_TURNS_MEMORY = int(os.getenv("AGENT_MAX_TURNS", "50"))
MAX_CTX_TOKENS_EXEC = int(os.getenv("AGENT_EXEC_MAX_TOK", "8192"))  # heuristic trim by message count
MAX_CYCLES = int(os.getenv("AGENT_MAX_CYCLES", "3"))

# MCP tool servers
SERVER_PATHS = [
    "../server/code_agent.py",
    "../server/ai_crawl.py",
    "../server/documents_tool.py",
    "../server/image_tool.py",
    "../server/math_tool.py",
    "../server/serp_search.py",
    "../server/video_tool.py",
]

# ==============================
#  Prompts (prompt-first)
# ==============================
META_SYSTEM_PROMPT = (
    "You are the META-PLANNER in a hierarchical AI system. A user will ask a "
    "high-level question. First: break the problem into a minimal sequence of executable tasks. "
    'Reply ONLY in JSON with the schema: { "plan": [ {"id": INT, "description": STRING} … ] }\n\n'
    "After each task is executed by the EXECUTOR you will receive its result. "
    "Carefully consider dates/timestamps of sources and events. "
    "If the final answer is complete, output it with the template:\n"
    "FINAL ANSWER: <answer>\n\n"
    "YOUR FINAL ANSWER should be a number OR as few words as possible OR a comma separated list; "
    "no extra analysis; no units unless requested. If incomplete, emit a new JSON plan. "
    "Never call tools yourself — that's the EXECUTOR's job. "
    "⚠️ Reply with pure JSON only (unless the single FINAL ANSWER line)."
)

EXEC_SYSTEM_PROMPT = (
    "You are the EXECUTOR sub-agent. You receive one task at a time from the planner. "
    "Use available tools via function calling if needed. Think step by step but respond with "
    "the minimal content needed for the planner. Do NOT output FINAL ANSWER."
)

JUDGE_PROMPT_TPL = '''You will be given a question and its ground truth answer list where each item can be a ground truth answer. Provided a pred_answer, you need to judge if the pred_answer correctly answers the question based on the ground truth answer list.
You should first give your rationale for the judgement, and then give your judgement result (i.e., correct or incorrect).

Criteria:
1) pred_answer may differ in wording but must be semantically equivalent to at least one ground truth.
2) Use only what's necessary; be strict but fair.

question: {question}
ground truth answers: {gt_answer}
pred_answer: {pred_answer}

Output JSON:
{{
  "rationale": "...",
  "judgement": "correct" | "incorrect"
}}
'''

# ==============================
#  Utilities
# ==============================
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"{[\s\S]*}", text)
    return m.group(0) if m else text

def _ensure_list(x: Any) -> List[str]:
    if x is None:
        return []
    if isinstance(x, list):
        return [str(i) for i in x]
    if isinstance(x, (str, int, float, bool)):
        return [str(x)]
    try:
        return [json.dumps(x, ensure_ascii=False)]
    except Exception:
        return [str(x)]

def _trim_by_count(messages: List[Dict[str, Any]], max_items: int = MAX_TURNS_MEMORY) -> List[Dict[str, Any]]:
    if len(messages) <= max_items:
        return messages
    sys_first = messages[:1]
    tail = messages[1:][-max_items + 1:]
    return sys_first + tail

def log_block(title: str, content: Any):
    try:
        if not isinstance(content, str):
            content = json.dumps(content, indent=2, ensure_ascii=False)
    except Exception:
        content = str(content)
    bar = "=" * len(title)
    print(f"\n{bar}\n{title}\n{bar}\n{content}\n")

# ==============================
#  Local-first LLM facade
# ==============================
class KariLLMBackend:
    """
    Uses Kari's LLMUtils/registry by default (local-first).
    If ENABLE_EXTERNAL_WORKFLOWS is true, can send OpenAI-compatible calls (for tools).
    """
    def __init__(self, model_alias: str, role: str):
        self.model_alias = model_alias
        self.role = role
        self.kari_llm: LLMUtils = get_registry().get_active() or LLMUtils()  # type: ignore[assignment,attr-defined]
        self.direct: Optional[AsyncOpenAI] = None
        if ENABLE_EXTERNAL_WORKFLOWS:
            self.direct = AsyncOpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = "auto",
    ) -> Dict[str, Any]:
        # If tools requested and externals allowed, use OpenAI-compatible tool calling
        if tools and self.direct:
            payload = {
                "model": self.model_alias,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": tool_choice or "auto",
            }
            resp = await self.direct.chat.completions.create(**payload)
            msg = resp.choices[0].message
            raw_calls = getattr(msg, "tool_calls", None)
            tool_calls = None
            if raw_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in raw_calls
                ]
            return {"content": msg.content, "tool_calls": tool_calls}

        # Local single-shot synthesis (no function tools)
        text = "\n".join(f"{m['role'].upper()}: {m.get('content','')}" for m in messages[-8:])
        out = self.kari_llm.generate_text(text, max_tokens=max_tokens)
        return {"content": out, "tool_calls": None}

# ==============================
#  MCP Tool Hub
# ==============================
class ToolHub:
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack: Optional[AsyncExitStack] = None

    async def connect(self, scripts: List[str]) -> None:
        self.exit_stack = AsyncExitStack()
        await self.exit_stack.__aenter__()
        for script in scripts:
            path = Path(script)
            if path.suffix not in {".py", ".js"}:
                raise ValueError(f"Server script must be .py or .js → {script}")
            cmd = "python" if path.suffix == ".py" else "node"
            params = StdioServerParameters(command=cmd, args=[str(path)])
            stdio, write = await stdio_client(params)
            session = ClientSession(stdio, write)
            await session.__aenter__()
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                if tool.name in self.sessions:
                    raise RuntimeError(f"Duplicate tool name '{tool.name}'.")
                self.sessions[tool.name] = session
        logger.info("Connected tools: %s", list(self.sessions.keys()))

    async def schema(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cached = {}
        for session in self.sessions.values():
            tools_resp = cached.get(id(session)) or await session.list_tools()
            cached[id(session)] = tools_resp
            for tool in tools_resp.tools:
                out.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        },
                    }
                )
        return out

    async def call(self, tool_name: str, args: Dict[str, Any]) -> str:
        # naive resolver: exact name required
        if tool_name not in self.sessions:
            # soft fuzzy
            for k in self.sessions.keys():
                if tool_name in k or k in tool_name:
                    tool_name = k
                    break
        if tool_name not in self.sessions:
            raise KeyError(f"No matching tool for '{tool_name}'. Available: {list(self.sessions.keys())}")
        session = self.sessions[tool_name]
        result = await session.call_tool(tool_name, args)
        return str(result.content)

    async def close(self) -> None:
        if self.exit_stack:
            # close sessions
            for sess in list(self.sessions.values()):
                try:
                    await sess.__aexit__(None, None, None)
                except Exception:
                    pass
            await self.exit_stack.__aexit__(None, None, None)

# ==============================
#  Traces / Records
# ==============================
@dataclass
class MetaCycle:
    cycle: int
    input: List[str]
    output: str

@dataclass
class ExecStep:
    task_id: int
    input: str
    output: str

@dataclass
class ToolCallRecord:
    tool: str
    arguments: Dict[str, Any]
    result: str

@dataclass
class QueryRecord:
    task_id: str
    query: str
    model_output: str
    plan_json: str
    meta_trace: List[MetaCycle]
    executor_trace: List[ExecStep]
    tool_history: List[ToolCallRecord]

# ==============================
#  Hierarchical Client (Kari-aligned)
# ==============================
class HierarchicalClient:
    MAX_CYCLES = MAX_CYCLES

    def __init__(self, meta_model: str, exec_model: str):
        # LLMs
        self.meta_llm = KariLLMBackend(meta_model, role="planner")
        self.exec_llm = KariLLMBackend(exec_model, role="executor")

        # Tools
        self.tools = ToolHub()

        # SR
        self.sr = SoftReasoningEngine(
            recall=RecallConfig(
                fast_top_k=24,
                final_top_k=5,
                recency_alpha=0.65,
                min_score=0.0,
                use_dual_embedding=True,
            ),
            writeback=WritebackConfig(
                novelty_gate=0.18,
                default_ttl_seconds=3600.0,
                long_ttl_seconds=86400.0,
                max_len_chars=5000,
            ),
        )

        # ICE
        self.ice = PremiumICEWrapper(
            policy=ICEWritebackPolicy(
                base_entropy_threshold=0.30,
                include_confidence=True,
                include_alternatives=False,
            )
        )

        # Shared conv
        self.shared_history: List[Dict[str, str]] = []

    async def connect_to_servers(self, scripts: List[str]):
        await self.tools.connect(scripts)

    async def _tools_schema(self) -> List[Dict[str, Any]]:
        return await self.tools.schema()

    def _add(self, role: str, content: str):
        self.shared_history.append({"role": role, "content": content})
        if len(self.shared_history) > MAX_TURNS_MEMORY:
            self.shared_history.pop(0)

    async def _plan_once(self, planner_msgs: List[Dict[str, Any]]) -> str:
        msgs = _trim_by_count(planner_msgs)
        reply = await self.meta_llm.chat(msgs, max_tokens=1024)
        return reply.get("content") or ""

    async def _exec_task(self, task_id: int, description: str, tools_schema: List[Dict[str, Any]]) -> str:
        # SR recall
        sr_matches = self.sr.query(description, top_k=5)
        sr_context = "\n".join(f"- {m.get('payload',{}).get('text','')}" for m in sr_matches if m.get("payload"))

        # ICE hint
        trace = self.ice.process(f"Task {task_id}: {description}", metadata={"role": "executor"})
        ice_hint = trace.synthesis

        exec_msgs = [
            {"role": "system", "content": EXEC_SYSTEM_PROMPT},
            {"role": "assistant", "content": f"SR Context:\n{sr_context}\n"},
            {"role": "assistant", "content": f"ICE Hint:\n{ice_hint}\n"},
            {"role": "user", "content": f"Task {task_id}: {description}"},
        ]
        exec_msgs = _trim_by_count(self.shared_history + exec_msgs, max_items=MAX_TURNS_MEMORY)

        # Try tool-enabled if external workflows allowed
        tools_for_call = tools_schema if ENABLE_EXTERNAL_WORKFLOWS else None
        reply = await self.exec_llm.chat(exec_msgs, tools=tools_for_call, max_tokens=1024)

        # Handle tool calls
        tool_history: List[ToolCallRecord] = []
        if reply.get("tool_calls"):
            for call in reply["tool_calls"]:
                t_name = call["function"]["name"]
                t_args = json.loads(call["function"].get("arguments") or "{}")
                try:
                    result_text = await self.tools.call(t_name, t_args)
                except Exception as e:
                    result_text = f"[tool error] {e}"
                tool_history.append(ToolCallRecord(tool=t_name, arguments=t_args, result=result_text))
                exec_msgs.extend(
                    [
                        {"role": "assistant", "content": None, "tool_calls": [call]},
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", str(uuid.uuid4())),
                            "name": t_name,
                            "content": result_text,
                        },
                    ]
                )
            # final assistant completion after tools
            reply = await self.exec_llm.chat(exec_msgs, tools=None, max_tokens=512)

        result_text = (reply.get("content") or "").strip()

        # Record and return
        self._add("assistant", f"Task {task_id} result: {result_text}")
        return result_text

    async def process_query(self, query: str, task_id: str) -> QueryRecord:
        self.shared_history = []
        tools_schema = await self._tools_schema()

        # SR pre-warm (recall similar questions; helpful few-shot)
        pre_matches = self.sr.query(query, top_k=5)
        exemplar = "\n".join(f"- {m.get('payload',{}).get('text','')}" for m in pre_matches if m.get("payload")) or ""
        exemplar_hint = f"(Similar prior items)\n{exemplar}\n" if exemplar else ""

        self._add("user", query)
        if exemplar_hint:
            self._add("assistant", exemplar_hint)

        planner_msgs = [{"role": "system", "content": META_SYSTEM_PROMPT}] + self.shared_history

        meta_trace: List[MetaCycle] = []
        executor_trace: List[ExecStep] = []
        tool_history: List[ToolCallRecord] = []
        final_answer: str = ""
        latest_plan_json: str = ""

        meta_content = ""
        for cycle in range(self.MAX_CYCLES):
            meta_reply = await self.meta_llm.chat(planner_msgs)
            meta_content = meta_reply["content"] or ""
            meta_trace.append(MetaCycle(cycle, [m["content"] for m in planner_msgs], meta_content))
            self._add("assistant", meta_content)

            if meta_content.startswith("FINAL ANSWER:"):
                final_answer = meta_content[len("FINAL ANSWER:"):].strip()
                break

            try:
                stripped = _strip_fences(meta_content)
                obj = json.loads(stripped)
                _ = obj["plan"]
                latest_plan_json = stripped
            except Exception as e:
                final_answer = f"[planner error] {e}: {meta_content}"
                break

            # Execute tasks (with SR grounding + ICE hint per task)
            tasks = json.loads(latest_plan_json)["plan"]
            for task in tasks:
                task_desc = f"Task {task['id']}: {task['description']}"
                out = await self._exec_task(task["id"], task["description"], tools_schema)
                executor_trace.append(ExecStep(task_id=task["id"], input=task_desc, output=out))

            planner_msgs = [{"role": "system", "content": META_SYSTEM_PROMPT}] + self.shared_history

        else:
            final_answer = meta_content.strip()

        # SR writeback (query + plan) for continual improvement
        try:
            wb_text = f"Q: {query}\nPlanJSON: {latest_plan_json or '[none]'}"
            self.sr.ingest(wb_text, {"source": "AgentFly", "kind": "plan_json"})
        except Exception as e:
            logger.warning("SR writeback failed: %s", e)

        # Clear volatile history
        self.shared_history.clear()

        return QueryRecord(
            task_id=task_id,
            query=query,
            model_output=final_answer,
            plan_json=latest_plan_json,
            meta_trace=meta_trace,
            executor_trace=executor_trace,
            tool_history=tool_history,
        )

    async def cleanup(self):
        await self.tools.close()

# ==============================
#  Judge (local-first with optional external)
# ==============================
class Judge:
    def __init__(self, model_alias: str):
        self.alias = model_alias
        self.kari_llm: LLMUtils = get_registry().get_active() or LLMUtils()  # type: ignore[assignment,attr-defined]
        self.direct: Optional[AsyncOpenAI] = None
        if ENABLE_EXTERNAL_WORKFLOWS:
            self.direct = AsyncOpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)

    async def evaluate(self, question: str, ground_truth: Any, pred_answer: str) -> Dict[str, Any]:
        gt_list = _ensure_list(ground_truth)
        prompt = JUDGE_PROMPT_TPL.format(
            question=question,
            gt_answer=json.dumps(gt_list, ensure_ascii=False),
            pred_answer=pred_answer,
        )

        # If externals allowed, we can use tool-capable completion; otherwise local
        try:
            if self.direct:
                resp = await self.direct.chat.completions.create(
                    model=self.alias,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                )
                content = resp.choices[0].message.content or ""
            else:
                content = self.kari_llm.generate_text(prompt, max_tokens=300)

            content = _strip_fences(content)
            data = json.loads(content)
            judgement = str(data.get("judgement", "incorrect")).lower().strip()
            if judgement not in ("correct", "incorrect"):
                judgement = "incorrect"
            rationale = str(data.get("rationale", ""))
            return {"judgement": judgement, "rationale": rationale}
        except Exception as e:
            logger.warning("Judge failed: %s", e)
            return {"judgement": "incorrect", "rationale": f"judge failed: {e}"}

# ==============================
#  Dataset loader
# ==============================
def load_deepresearcher(path: str) -> tuple[List[str], Dict[str, Any]]:
    query_list: List[str] = []
    gt_map: Dict[str, Any] = {}
    if not os.path.exists(path):
        logger.warning("Dataset not found: %s", path)
        return query_list, gt_map
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            q = data["question"]
            query_list.append(q)
            gt_map[q] = data.get("ground_truth", None)
    return query_list, gt_map

# ==============================
#  Main
# ==============================
async def main():
    load_dotenv()

    query_list, ground_truth_map = load_deepresearcher(DATASET_PATH)
    if not query_list:
        print("⚠️  query_list is empty – add questions to process.")
        return

    # resume
    finished_task = set()
    if os.path.exists(RESULT_OUT):
        with open(RESULT_OUT, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                    finished_task.add(record.get("query") or record.get("question"))
                except Exception:
                    continue

    client = HierarchicalClient(META_MODEL, EXEC_MODEL)
    await client.connect_to_servers(SERVER_PATHS)
    judge = Judge(JUDGE_MODEL)

    try:
        for idx, q in enumerate(query_list):
            if q in finished_task:
                print(f"Task already finished, skipping: {q[:80]}...")
                continue

            try:
                rec = await client.process_query(q, str(uuid.uuid4()))
                pred_answer = rec.model_output
                gt = ground_truth_map.get(q)

                judge_res = await judge.evaluate(q, gt, pred_answer)
                reward = 1 if judge_res["judgement"] == "correct" else 0

                # Persist result row
                rec_dict = asdict(rec)
                rec_dict.update(
                    {
                        "question": q,
                        "plan": rec.plan_json,
                        "ground_truth": gt,
                        "pred_answer": pred_answer,
                        "judgement": judge_res["judgement"],
                        "rationale": judge_res["rationale"],
                        "reward": reward,
                    }
                )
                print("\nFINAL ANSWER:", rec.model_output)
                os.makedirs(os.path.dirname(RESULT_OUT), exist_ok=True)
                with open(RESULT_OUT, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec_dict, ensure_ascii=False) + "\n")

                # Append minimal memory JSONL for future few-shot (training-friendly)
                try:
                    os.makedirs(os.path.dirname(MEMORY_JSONL_PATH), exist_ok=True)
                    mem_entry = {"question": q, "plan": rec.plan_json or "", "reward": reward}
                    with open(MEMORY_JSONL_PATH, "a", encoding="utf-8") as mf:
                        mf.write(json.dumps(mem_entry, ensure_ascii=False) + "\n")
                except Exception as e:
                    logger.warning("Failed to write memory file: %s", e)

                # SR writeback (reward-aware importance bump)
                try:
                    wb_text = f"[judged:{judge_res['judgement']}|reward:{reward}] Q:{q} A:{pred_answer}"
                    self_meta = {"source": "Judge", "importance": 0.7 + 0.2 * reward}
                    client.sr.ingest(wb_text, self_meta)
                except Exception as e:
                    logger.warning("SR judge writeback failed: %s", e)

            except Exception as e:
                print(f"[ERROR]: {e}")
                continue
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
