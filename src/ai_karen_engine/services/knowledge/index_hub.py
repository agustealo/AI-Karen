"""Knowledge index hub (lightweight canonical implementation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Department(str, Enum):
    ENGINEERING = "engineering"
    OPERATIONS = "operations"
    BUSINESS = "business"


class Team(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DEVOPS = "devops"
    QA = "qa"
    INFRASTRUCTURE = "infrastructure"
    SECURITY = "security"
    MONITORING = "monitoring"
    PRODUCT = "product"
    MARKETING = "marketing"
    SALES = "sales"


@dataclass
class KnowledgeQuery:
    text: str
    department: Optional[Department] = None
    team: Optional[Team] = None
    source_types: Optional[List[str]] = None
    max_results: int = 10
    min_confidence: float = 0.5
    require_citations: bool = True


@dataclass
class Citation:
    source_id: str
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    table_name: Optional[str] = None
    column_name: Optional[str] = None
    confidence_score: float = 0.5
    context_snippet: Optional[str] = None


@dataclass
class KnowledgeResult:
    content: str
    citations: List[Citation] = field(default_factory=list)
    confidence_score: float = 0.5
    source_metadata: Dict[str, Any] = field(default_factory=dict)
    conceptual_relationships: List[str] = field(default_factory=list)


class KnowledgeBackendUnavailableError(RuntimeError):
    """The legacy index hub has no configured, authorized retrieval backend."""


class IndexHub:
    """Retired compatibility surface, not a usable document search authority.

    The canonical runtime must supply authorized document evidence through its
    owned retrieval contracts. Never silently report zero matches or healthy
    indexing when this compatibility hub has no backing implementation.
    """

    async def search(self, query: KnowledgeQuery) -> List[KnowledgeResult]:
        raise KnowledgeBackendUnavailableError(
            "Legacy knowledge index unavailable; search was not performed"
        )

    async def get_department_statistics(self) -> Dict[str, Any]:
        raise KnowledgeBackendUnavailableError(
            "Legacy knowledge index unavailable; statistics were not read"
        )

    async def health_check(self) -> Dict[str, Any]:
        return {
            "status": "unavailable",
            "indexed_sources": None,
            "reason": "legacy_index_not_configured",
        }


__all__ = [
    "IndexHub",
    "Department",
    "Team",
    "KnowledgeQuery",
    "Citation",
    "KnowledgeResult",
    "KnowledgeBackendUnavailableError",
]
