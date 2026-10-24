"""Direct time reads must consume governed runtime context, not infer user geography."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = (ROOT / "src/ai_karen_engine/core/runtime/direct_capability_executor.py").read_text()
RUNTIME = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text()


def test_runtime_resolves_scoped_timezone_for_time_intent():
    assert 'attribute="timezone"' in RUNTIME
    assert 'if decision.intent == "time.current" else None' in RUNTIME
    assert '"timezone": resolved_timezone' in RUNTIME


def test_time_executor_passes_resolved_context_to_plugin():
    assert 'timezone_name = self._metadata_timezone(resolved_context or {})' in EXECUTOR
    assert '                    resolved_context,\n                ),' in EXECUTOR
