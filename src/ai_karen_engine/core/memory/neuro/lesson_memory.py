from __future__ import annotations

from .contracts import LessonArtifact


class LessonMemoryStore:
    def __init__(self) -> None:
        self._store: dict[str, list[LessonArtifact]] = {}

    def put(self, tenant_id: str, artifact: LessonArtifact) -> None:
        self._store.setdefault(tenant_id, []).append(artifact)

    def count(self, tenant_id: str) -> int:
        return len(self._store.get(tenant_id, []))

    def recall(self, tenant_id: str, scope: str, limit: int = 5) -> list[LessonArtifact]:
        items = self._store.get(tenant_id, [])
        scope_l = scope.lower()
        return [a for a in items if scope_l in a.failure_signature.lower() or any(scope_l in x.lower() for x in a.applies_to)][:limit]
