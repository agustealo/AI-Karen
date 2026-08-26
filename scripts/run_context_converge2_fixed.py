from __future__ import annotations

from pathlib import Path

path = Path(__file__).with_name("apply_context_converge2.py")
text = path.read_text(encoding="utf-8")
needle = '''text = replace_once(text, old_node, new_node, 'orchestrator memory node wiring')
if "ContextManager" in text or "_context_manager" in text or "context_manager=" in text:
    raise RuntimeError("orchestrator still contains ContextManager authority")
'''
replacement = '''text = replace_once(text, old_node, new_node, 'orchestrator memory node wiring')
text = replace_once(
    text,
    ''' + '"""' + '''        diagnostics_engine = DiagnosticsEngine(\n            decision_engine=self._decision_engine,\n            context_manager=await self._ensure_context_manager(),\n            llm_router=self._llm_router,\n            profile_manager=self._profile_manager,\n        )\n''' + '"""' + ''',
    ''' + '"""' + '''        diagnostics_engine = DiagnosticsEngine(\n            decision_engine=self._decision_engine,\n            llm_router=self._llm_router,\n            profile_manager=self._profile_manager,\n        )\n''' + '"""' + ''',
    'orchestrator diagnostics ContextManager wiring',
)
text = replace_once(
    text,
    ''' + '"""' + '''        if self._context_manager:\n            self._context_manager.clear_context_cache()\n''' + '"""' + ''',
    "",
    'orchestrator ContextManager shutdown hook',
)
_remaining = [
    f"{index}: {line}"
    for index, line in enumerate(text.splitlines(), start=1)
    if "ContextManager" in line or "_context_manager" in line or "context_manager=" in line
]
if _remaining:
    raise RuntimeError("orchestrator still contains ContextManager authority: " + " | ".join(_remaining))
'''
if text.count(needle) != 1:
    raise RuntimeError("converge-2 driver could not locate orchestrator guard")
text = text.replace(needle, replacement, 1)
code = compile(text, str(path), "exec")
exec(code, {"__name__": "__main__", "__file__": str(path)})
