# NeuroRecall Labs Harness

This directory contains the former `core/neuro_recall` research harness. It is intentionally outside `ai_karen_engine.core` so it cannot present itself as a competing production memory authority.

Production recall lives at `src/ai_karen_engine/core/memory/retrieval/neuro_recall.py`.

Labs scope:
- memory experiments and benchmark runs
- procedural-learning candidate discovery
- case-based reasoning evaluation
- judged writeback candidate generation
- benchmark data and research-only agent clients

The harness remains gated by `KARI_NEURO_RECALL_LABS_ENABLED=true` and must not directly persist production memory. Durable writes must pass through the canonical memory governance path and NeuroVault boundary.
