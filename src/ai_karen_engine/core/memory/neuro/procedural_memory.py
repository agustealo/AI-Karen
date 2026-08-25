from __future__ import annotations

from .contracts import ProcedureArtifact


class ProceduralMemoryStore:
    def __init__(self) -> None:
        self._store: dict[str, list[ProcedureArtifact]] = {}

    def put(self, tenant_id: str, artifact: ProcedureArtifact) -> None:
        self._store.setdefault(tenant_id, []).append(artifact)

    def count(self, tenant_id: str) -> int:
        return len(self._store.get(tenant_id, []))

    def recall(self, tenant_id: str, trigger_text: str, limit: int = 3) -> list[ProcedureArtifact]:
        triggers = trigger_text.lower()
        items = self._store.get(tenant_id, [])
        return [a for a in items if any(p.lower() in triggers for p in a.trigger_patterns)][:limit]


def default_routing_procedures() -> list[ProcedureArtifact]:
    """Seed routing preferences so plugin/tool routing is policy-based, not hardcoded."""
    return [
        ProcedureArtifact(
            id="proc-weather-search",
            name="weather_via_web_search",
            trigger_patterns=["weather", "forecast", "temperature"],
            tool_sequence=["plugin:intelligent-search(mode=weather)", "llm:summarize"],
            confidence=0.9,
        ),
        ProcedureArtifact(
            id="proc-time-tool",
            name="time_via_utility_tool",
            trigger_patterns=["current time", "time in", "timezone"],
            tool_sequence=["tool:time", "llm:format_with_timezone"],
            confidence=0.95,
        ),
        ProcedureArtifact(
            id="proc-latest-search",
            name="latest_info_via_web_search",
            trigger_patterns=["latest", "current", "search the internet", "look online"],
            tool_sequence=["plugin:intelligent-search(mode=general)", "llm:summarize"],
            confidence=0.9,
        ),
        ProcedureArtifact(
            id="proc-joke-llm",
            name="joke_via_llm_only",
            trigger_patterns=["tell me a joke", "joke", "funny"],
            tool_sequence=["llm:direct_generation"],
            confidence=0.95,
        ),
    ]
