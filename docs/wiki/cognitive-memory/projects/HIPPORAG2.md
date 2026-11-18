# HippoRAG 2 | associative retrieval and Personalized PageRank

**Upstream:** [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) · **Pinned:** `d5c8329422e0a0b834a15874545cb6a74b4f9b26` · **Version:** 2.0.0a5 in [manifest](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/pyproject.toml) · **License/Python:** MIT; >=3.10 · **Status:** source-inspected, unbenchmarked.

## Functional mechanisms to reverse-engineer
1. Open information extraction (entities and relational triples), passage/entity linking, graph candidate construction.
2. Seed selection through query-to-entity/fact affinity and subsequent **Personalized PageRank** over graph structure.
3. Retrieval fusion: map graph-activated entities back to source passages, protect against high-degree hubs and distractors.
4. Index identity tied to model/normalization/revision so old vectors are not silently mixed with new.
5. [Engine](https://github.com/OSU-NLP-Group/HippoRAG/blob/d5c8329422e0a0b834a15874545cb6a74b4f9b26/src/hipporag/HippoRAG.py) uses `igraph`, OpenIE and separate entity/fact/chunk embedding stores.

## KAREN overlap and possible value
- KAREN already has `SpreadingActivation`, a bounded graph neighborhood API, and NeuroRecall candidate fusion/ranking.
- Experiment with **one pure-Python sparse PPR** compute over authorized PostgreSQL-derived neighbors, measuring whether it improves R03/R04 beyond existing depth/decay activation. Never turn a scoring view into authoritative graph state.
- Avoid new embedding stores: obtain vectors/scores only through KAREN's governed retrieval/model infrastructure.

## Dependency/deployment consequences
The upstream base pins `torch==2.5.1`, `transformers==4.45.2`, `python_igraph==0.11.8`, `litellm==1.73.1`, and `openai>=3.3.1,<4`. KAREN pins `openai==2.32.0`: this is a **direct resolver conflict**. Full package installation is off the table for the current stack.

## Investigation steps
- [ ] Trace exact PPR seed formation and graph propagation in source; separately document OpenIE/model call costs.
- [ ] Reproduce a mathematically specified PPR baseline with built-in Python, bounded iterations, convergence, restart probability and strict scope filtering (research-only).
- [ ] Compare paired Recall@K and nDCG with KAREN's existing spreading activation and simple degree-limited traversal.
- [ ] Check adversarial hub effects, disconnected graphs, stale vector identities, consent deletion and restart.
- [ ] R03/R04/R08/R09/R12/R14 must pass before any algorithm-level promotion.

**Gate:** Score improvements without added heavyweight ML dependencies or extra vector stores.


## Pinned mechanism deep dive
See [KCR-02A](../KCR02A_GRAPH_RETRIEVAL.md) for exact weighted undirected PPR execution, entity/passage seed formation, and source-aware graph deduplication. A zero-dependency synthetic comparator is proposed, not a production integration.
