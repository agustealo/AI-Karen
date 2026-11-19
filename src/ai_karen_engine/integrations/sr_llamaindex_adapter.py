"""Retired direct LlamaIndex structural-retrieval integration.

Historical SRRetriever callers may still import this adapter. It cannot safely
retrieve enterprise or personal documents: the legacy contract has no trusted
actor/resource identity, and its metadata_filter did not constrain index queries.

Keep the compatibility type fail-closed until a canonical, authenticated document
retrieval owner supplies a versioned, ACL-checked adapter. Do not turn document
metadata into authorization or reinstate silent ingestion failures.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ai_karen_engine.core.reasoning.retrieval.adapters import SRRetriever


class LlamaIndexAuthorizationRequired(PermissionError):
    """Direct LlamaIndex access lacks canonical document authorization."""


class LlamaIndexSRAdapter(SRRetriever):
    """Compatibility adapter that refuses ungoverned document operations.

    An externally built index is not a trusted authorization boundary. In
    particular, a caller-controlled metadata_filter cannot prove access to the
    referenced source documents or that their consent/revision is current.
    """

    def __init__(self, index: Any) -> None:
        if index is None:
            raise ValueError("A configured LlamaIndex index is required")
        self.index = index

    def query(
        self,
        text: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Never execute direct index queries outside governed retrieval."""
        raise LlamaIndexAuthorizationRequired(
            "Direct LlamaIndex retrieval unavailable: canonical document "
            "authorization and source revision checks are required"
        )

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        """Never acknowledge insertion without a durable governed receipt."""
        raise LlamaIndexAuthorizationRequired(
            "Direct LlamaIndex ingestion unavailable: canonical document "
            "ownership and persistence receipts are required"
        )


__all__ = ["LlamaIndexSRAdapter", "LlamaIndexAuthorizationRequired"]
