from __future__ import annotations

"""
Client library exports.

Production-ready clients for:
- Database: Milvus, Elasticsearch
"""

from ai_karen_engine.clients.database import (
    elastic_client,
    milvus_client,
)

__all__ = [
    "elastic_client",
    "milvus_client",
]
