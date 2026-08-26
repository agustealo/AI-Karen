"""Reproducible evaluation contract for Zhu et al. Soft Reasoning (ICML 2025).

This module intentionally contains protocol metadata only. Dataset acquisition
and model execution stay outside unit tests so CI never downloads benchmarks or
large models implicitly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PaperBenchmark:
    benchmark_id: str
    task_family: str
    answer_extractor: str


PAPER_BENCHMARKS = (
    PaperBenchmark("gsm8k", "math", "numeric_final_answer"),
    PaperBenchmark("gsm_hard", "math", "numeric_final_answer"),
    PaperBenchmark("svamp", "math", "numeric_final_answer"),
    PaperBenchmark("strategyqa", "boolean_reasoning", "yes_no_final_answer"),
)

PAPER_SHOT_COUNTS = (0, 1, 2, 4, 8)
PAPER_RUNS_PER_CONFIGURATION = 5
PAPER_CONVERGENCE_THRESHOLD = 0.01
PAPER_PROJECTION_DIMENSION = 50
PAPER_BATCH_SIZE = 5
PAPER_EI_CANDIDATE_POOL = 5000
PAPER_DEFAULT_VERIFIER = "multi_generate"

# Models explicitly reported in the paper's full comparison tables.
PAPER_MODEL_FAMILIES = (
    "LLaMA3-8B-Instruct",
    "Qwen2-7B-Instruct",
    "Mistral-7B-Instruct",
)


def protocol_matrix_size() -> int:
    return (
        len(PAPER_BENCHMARKS)
        * len(PAPER_SHOT_COUNTS)
        * len(PAPER_MODEL_FAMILIES)
        * PAPER_RUNS_PER_CONFIGURATION
    )


__all__ = [
    "PAPER_BATCH_SIZE",
    "PAPER_BENCHMARKS",
    "PAPER_CONVERGENCE_THRESHOLD",
    "PAPER_DEFAULT_VERIFIER",
    "PAPER_EI_CANDIDATE_POOL",
    "PAPER_MODEL_FAMILIES",
    "PAPER_PROJECTION_DIMENSION",
    "PAPER_RUNS_PER_CONFIGURATION",
    "PAPER_SHOT_COUNTS",
    "PaperBenchmark",
    "protocol_matrix_size",
]
