# 15 | Research review, standards and implementation sources

[← Index](README.md) · [Previous](14-decisions.md)

**Research reviewed:** 2026-11-16. Preference is peer-reviewed sources, official documentation and authoritative standards. Preprints are labeled; findings are not treated as proof on Karen's workload.

## A. Memory architecture and agent learning

1. **Han et al. (2026-11-09), _Learning to remember: advances in memory mechanisms for large language models_.** [Springer](https://link.springer.com/article/10.1007/s44336-026-00044-1). Survey differentiates nonparametric storage, parametric/model memory and memory for agent evolution. **KCM implication:** preserve distinct loops and treat evaluation, maintenance and forgetting as first-class.
2. **ACM (2025-11), _Continual Learning of Large Language Models: A Comprehensive Survey_.** [DOI](https://doi.org/10.1145/3735633). Reviews catastrophic forgetting and challenges of sequential adaptation. **KCM:** no untested continuous fine-tuning.
3. **Le & Venkatesh (EMNLP 2026), _Continual Fine-Tuning of Large Language Models via Program Memory_.** [ACL](https://aclanthology.org/2026.findings-emnlp.1048/). Experimental ProCL method for mitigating forgetting via structured LoRA memory. **KCM:** research option, not required v1 architecture.

## B. Selection, coverage, data quality

4. **Pandia, Misra & Ettinger (2026-11-05 preprint), _Rethinking Data Selection: The Importance of Coverage over Difficulty in LLM Fine-Tuning_.** [arXiv](https://arxiv.org/abs/2611.07323). Shows why difficulty-only scoring may lose to coverage/random selection. **KCM:** coverage-first baselines alongside quality ranking.
5. **Wu et al. (EMNLP 2026), _From Instance Selection to Fixed-Pool Data Recipe Search for Supervised Fine-Tuning_.** [ACL](https://aclanthology.org/2026.emnlp-main.1877/). Filtering/mixing/dedup recipes matter beyond sample scores. **KCM:** version the entire selection recipe and dataset.
6. **Zhang et al. (ACL 2026), _Skill-Aware Data Selection and Fine-Tuning for Data-Efficient Reasoning Distillation_.** [ACL](https://aclanthology.org/2026.acl-short.49/). 1,000 skill-selected of 100K generated examples outperformed random baselines on evaluated mathematical reasoning tasks for 4B/8B students. **KCM:** target verified skill gaps, not indiscriminate volume; do not extrapolate performance to sub-billion Persona generation.
7. **Zhang & Gross (AACL 2026), _PPL-Factory: Task-Aware and Budget-Aware Data Selection from Language Modeling to Reasoning_.** [ACL](https://aclanthology.org/2026.findings-aacl.202/). Tested model-aware perplexity-based selection. **KCM:** model-aware scoring as optional experiment only.
8. **Zou et al. (ICML 2026), _Utility-Diversity Aware Online Batch Selection for LLM Supervised Fine-tuning_.** [PMLR](https://proceedings.mlr.press/v306/zou26j.html). Emphasizes utility/diversity trade-offs. **KCM:** prevent top-N quality sampling from collapsing coverage.
9. **_Training datasets tailored for domain-specific large language models_ (2026 survey).** [Springer](https://link.springer.com/article/10.1007/s44443-026-01150-2). Separates sample quality, distribution quality, model-aware value and actual outcome value. **KCM:** four-tier evaluation framework.
10. **ACL 2026 tutorial, _The Data Frontier for Large Language Models_.** [Tutorial site](https://acl26datatutorial.github.io/acl-data-frontier-tutorial/). Covers selection, synthesis and data-centric model optimization. **KCM:** prioritize audited dataset quality, not merely scale.
11. **_Instruction Tuning for Large Language Models: A Survey_ (ACM 2026).** [DOI](https://doi.org/10.1145/3777411). Summarizes instruction/output supervised learning. **KCM:** train on vetted targets, not raw context logs.

## C. Training implementations and model lifecycle

12. **Hugging Face TRL, SFTTrainer official docs (accessed 2026-11-16).** [Docs](https://huggingface.co/docs/trl/sft_trainer). Conversational datasets, completion-only/assistant-only loss, packing, PEFT LoRA. **KCM:** pinned and tested implementation reference; inspect exact installed API version.
13. **PyTorch serialization security docs.** [Docs](https://docs.pytorch.org/docs/stable/notes/serialization). `weights_only` mitigates some pickle risks but is not a complete secure execution boundary. **KCM:** safe checkpoint loading, verified sources and worker isolation.
14. **MLflow Evaluation Dataset Concepts.** [Docs](https://mlflow.org/docs/latest/genai/concepts/evaluation-datasets/). Reusable ground-truth/expectations and experiment lineage. **KCM:** conceptual reference, not an automatic new dependency.
15. **MLflow Model Registry.** [Docs](https://mlflow.org/docs/latest/registry/). Versions, lineage, metadata, rollbacks. **KCM:** compare capabilities against Karen's existing model lifecycle before considering another registry.

## D. Security, privacy, deletion

16. **OWASP GenAI LLM Top 10 (2026 edition).** [Official OWASP](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/). Data/model poisoning, prompt injection, agency, privacy, supply chain. **KCM:** threat model for memory-to-training poisoning.
17. **OWASP 2026 launch announcement.** [Official OWASP](https://genai.owasp.org/2026/09/01/owasp-genai-security-project-unveils-2026-top-10-for-llm-applications-new-agent-control-standard-and-sponsors-as-community-tops-30000-members/). Confirms 2026 guidance release; assess newest recommendations in implementation.
18. **NIST AI RMF 600-1 Generative AI Profile (2024).** [NIST](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence). Established risk management and evaluation principles; older but still a relevant baseline.
19. **_Towards Reliable Forgetting: A Survey on Machine Unlearning Verification_ (ACM 2026).** [DOI](https://doi.org/10.1145/3807451). Verification of unlearning remains difficult. **KCM:** lineage, model fencing and no unsupported deletion claims.
20. **_From Forgetting to Future: A Survey of Machine Unlearning Approaches_ (Wiley 2026).** [DOI](https://doi.org/10.1002/widm.70082). Reviews current unlearning gaps. **KCM:** clean-data retraining or explicit quarantining preferred over naive promises.
21. **OWASP Q3 2026 exploit roundup.** [Official OWASP](https://genai.owasp.org/2026/10/08/genai-and-agentic-ai-exploit-roundup-q3-2026/). Discusses persistent memory/context poisoning scenarios. **KCM:** quarantine and source isolation; no direct promotion from retrieved instructions.

## E. Primary Karen architecture evidence

22. [`core/memory/NEURO_MEMORY_ARCHITECTURE.md`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/NEURO_MEMORY_ARCHITECTURE.md): canonical memory ownership and documented current backend.
23. [`core/memory/types/base.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/types/base.py): existing training privacy tags and eligibility states.
24. [`core/memory/guards.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/memory/guards.py): trust provenance, sensitivity and deletion propagation.
25. [`core/cognitive/state.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/core/cognitive/state.py): belief, adaptive, policy, meta snapshots.
26. [`echocore/contracts.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/echocore/contracts.py): training queue policy and current quality-score conflation.
27. [`echocore/production_fine_tuner.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/echocore/production_fine_tuner.py): current SFT and mock fallback paths.
28. [`learning/training_data_manager.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/learning/training_data_manager.py): dataset management and scope audit finding.
29. [`config/learning.py`](https://github.com/agustealo/AI-Karen/blob/main/src/ai_karen_engine/config/learning.py): central learning configuration.
30. [`docs/ADR-001-karen-cognitive-runtime-architecture.md`](https://github.com/agustealo/AI-Karen/blob/main/docs/ADR-001-karen-cognitive-runtime-architecture.md): canonical cognitive/governance/execution boundaries (proposal).
31. [`docs/MODEL_LIFECYCLE_ARCHITECTURE.md`](https://github.com/agustealo/AI-Karen/blob/main/docs/MODEL_LIFECYCLE_ARCHITECTURE.md): model acquisition/activation and security contracts.

## Evidence grade and caveats

- **Strongest for implementation rules:** current repository source, official tool docs and published standards. Source review does not imply runtime correctness.
- **Peer-reviewed examples:** ACL/EMNLP/ICML 2026 papers. Results are on particular datasets/models; KCM must reproduce/benchmark locally.
- **Preprints:** arXiv 2026 coverage study; informative but not independently replicated here.
- **Surveys:** synthesis of a field, not proof of one optimal architecture.
- **Proposed thresholds/score weights:** KCM engineering hypotheses and evaluation targets; no source claims they are universally optimal.

### Update cadence

Recheck official tooling APIs and security guidance before coding. Revisit benchmark assumptions and citations each quarter or after major base-model changes; do not silently reinterpret past experimental results as new deployment permission.
