from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ai_karen_engine"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: expected one occurrence of {old!r}, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Correct collateral rename caught during import-level review.
replace_once(
    SRC / "core/langgraph_orchestrator/context/file_upload_service.py",
    "FileFileContextUpdateRequest",
    "FileContextUpdateRequest",
)

# Keep configuration coercion inside PromptRuntime rather than LangGraph.
prompt_service = SRC / "core/runtime/prompt/prompt_service.py"
replace_once(prompt_service, "        token_budget: int = 4096,\n", "        token_budget: Any = 4096,\n")
replace_once(
    prompt_service,
    "            token_budget=max(1, int(token_budget or 4096)),\n",
    "            token_budget=self._normalize_token_budget(token_budget),\n",
)
anchor = '''    @staticmethod\n    def _instruction_lines(value: Any) -> List[str]:\n'''
helper = '''    @staticmethod\n    def _normalize_token_budget(value: Any, default: int = 4096) -> int:\n        try:\n            parsed = int(value)\n        except (TypeError, ValueError):\n            return default\n        return max(1, parsed)\n\n'''
text = prompt_service.read_text(encoding="utf-8")
if text.count(anchor) != 1:
    raise RuntimeError("prompt service token-budget helper anchor changed")
prompt_service.write_text(text.replace(anchor, helper + anchor, 1), encoding="utf-8")

response_synth = SRC / "core/langgraph_orchestrator/nodes/response_synth.py"
old = '''                    token_budget=int(\n                        request_preferences.get("token_budget")\n                        or request_preferences.get("max_input_tokens")\n                        or 4096\n                    ),\n'''
new = '''                    token_budget=(\n                        request_preferences.get("token_budget")\n                        or request_preferences.get("max_input_tokens")\n                        or 4096\n                    ),\n'''
replace_once(response_synth, old, new)

# Correct stale constructor documentation after file/conversation separation.
replace_once(
    SRC / "core/langgraph_orchestrator/context/file_upload_service.py",
    "            context_manager: Context Manager instance\n",
    "            file_context_store: File-context metadata store\n",
)

print("forensic context converge-1 corrections applied")
