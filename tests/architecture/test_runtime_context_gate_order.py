"""Runtime gating must happen before prior personal conversation is hydrated."""

from pathlib import Path


RUNTIME = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/core/runtime/chat_runtime.py"
)


def test_http_gate_precedes_authorized_conversation_hydration():
    source = RUNTIME.read_text(encoding="utf-8")
    method = source.split("    async def execute(self, request:", 1)[1].split(
        "    async def execute_stream(", 1
    )[0]
    assert method.index("gate = await self._resolve_gate(ctx)") < method.index(
        "await self._prepare_conversation_continuation(request)"
    )
    assert method.index("return ChatExecutionResult(") < method.index(
        "await self._prepare_conversation_continuation(request)"
    )


def test_stream_gate_precedes_authorized_conversation_hydration():
    source = RUNTIME.read_text(encoding="utf-8")
    method = source.split("    async def execute_stream(", 1)[1].split(
        "    async def _persist_transcript(", 1
    )[0]
    assert method.index("gate = await self._resolve_gate(ctx)") < method.index(
        "await self._prepare_conversation_continuation(request)"
    )
    assert method.index('metadata={"gate": getattr(gate, "mode", "gate")}', 1) < method.index(
        "await self._prepare_conversation_continuation(request)"
    )
