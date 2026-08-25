"""
Evaluation Harness for AI Karen Memory System.

Provides tools for benchmarking memory retrieval, extraction quality, 
and profile stability. Inspired by LoCoMo and LongMemEval research.
"""

import json
import os
import time
from pathlib import Path
from typing import Any

from ai_karen_engine.core.logging import get_logger

from ..retrieval.retrieval_router import get_retrieval_router
from ..types import MemoryQuery

logger = get_logger(__name__)

class MemoryEvalHarness:
    """Harness for automated memory system evaluation."""
    
    def __init__(self):
        self.router = get_retrieval_router()

    async def evaluate_retrieval(self, dataset: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Evaluate retrieval accuracy against a known dataset.
        Dataset format: [{'query': '...', 'expected_id': '...'}]
        """
        results = {
            "total": len(dataset),
            "hits": 0,
            "misses": 0,
            "latency_avg_ms": 0.0
        }
        
        latencies = []
        for entry in dataset:
            start = time.time()
            query = MemoryQuery(text=entry['query'], top_k=5)
            retrieved = await self.router.recall(query)
            latencies.append((time.time() - start) * 1000)
            
            # Check if expected ID is in results
            retrieved_ids = [m.id for m in retrieved]
            if entry['expected_id'] in retrieved_ids:
                results['hits'] += 1
            else:
                results['misses'] += 1
                
        results['latency_avg_ms'] = sum(latencies) / len(latencies) if latencies else 0
        results['accuracy'] = results['hits'] / results['total'] if results['total'] > 0 else 0
        
        return results

    async def run_stability_test(self, user_id: str):
        """Evaluate if profile facts remain stable over multiple contradictory inputs."""
        # Implementation of profile stability benchmarking

# Global instance
eval_harness = MemoryEvalHarness()

def get_eval_harness() -> MemoryEvalHarness:
    return eval_harness


async def run_neuro_recall_benchmark(dataset_path: str) -> dict[str, Any]:
    """Labs-only benchmark runner for JSONL datasets (read/eval only)."""
    if os.getenv("KARI_NEURO_RECALL_LABS_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        raise RuntimeError("NeuroRecall benchmark runner is labs-only.")
    rows: list[dict[str, Any]] = []
    for line in Path(dataset_path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    normalized = [{"query": r.get("query", ""), "expected_id": str(r.get("expected_id", ""))} for r in rows]
    return await eval_harness.evaluate_retrieval(normalized)
