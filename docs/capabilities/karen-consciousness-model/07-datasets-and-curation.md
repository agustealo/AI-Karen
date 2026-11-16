# 07 | Dataset curation and preparation

[← Index](README.md) · [Previous](06-contracts-and-lineage.md) · [Next →](08-training-and-models.md)

## 1. Separate learning objectives

Don't build one blended "Karen memories" corpus. Define independent, measurable objectives and rubrics:

| Dataset class | Input | Supervision | Should it train? |
|---|---|---|---|
| Persona expression | Authorized context, style directive | Human- or policy-reviewed answer | Sometimes, if prompt-only baseline is insufficient |
| Procedural execution | Task, constraints, tool schema | Verifiably correct step/action sequence | When proper tool checks and outcomes exist |
| Error repair | Task, failing attempt, diagnostic | Corrected and retested solution | Yes for defined skill under evaluation |
| Intent/classification | User utterance, task signature | Adjudicated label | Train classifier through existing intelligence owner |
| Capability calibration | Task descriptor, context | Verified success/failure and uncertainty labels | Usually **KCM projection**, not generator weights |
| Personal preference | User-supplied preference | Current authorized preference record | **Retrieval-only default** |
| Current/volatile fact | Time-bounded assertion | Source evidence | **Retrieval-only default** |

## 2. Exemplars: correct vs incorrect

- **Positive SFT:** request + complete authorized context + independently approved best-response target.
- **Corrected failure:** preserve rejected attempt and validated correction as *separate fields*. SFT trains on chosen target, not on the original failure.
- **Preference optimization:** create a chosen/rejected pair only when adjudicated and ethically/licensingly permitted. Avoid optimizing entirely on stylistic preference if factual correctness degrades.
- **Skill competency:** use real execution receipts; do not infer that a fluent code answer runs correctly.
- **Synthetic candidate:** mark source `synthetic` and teacher model/seed/revision; require independent validators and sampling audits. Never let teacher and student evaluations leak the same answers.

## 3. Data minimization and normalization

- Prefer derived task-level examples stripped of user identities, tokens, direct URLs to private systems and unnecessary content.
- Preserve immutable **references** to raw source, not unbounded copying into multiple stores.
- Remove accidental duplicates, templated filler, boilerplate and conflicting labels.
- Convert examples into model-native chat/completion format only *after* policy/label verification; keep a canonical pre-tokenization record.
- Preserve language, difficulty, task families, explicit objectives, evidence and consent metadata as separate non-training fields.

## 4. Split protection

A random row split is not sufficient for conversational/agent learning. Define a `leakage_group_id` to group by original task, session, transcript, canonical question, document, tool trace, synthetic parent, template family and near-duplicate cluster. All group members must belong to exactly one split.

For temporal tasks, hold out later periods to expose knowledge staleness. Maintain a frozen, curated golden evaluation set that is **never added back to training**, including via synthetic generation or examples derived from evaluation prompts.

Recommended experiment starting splits: 80/10/10 **by group**, not by row, when data is sufficient. Exact ratios are experiment configuration, not architectural guarantees; rare safety tasks need a separate locked benchmark.

## 5. Dataset recipes

Evaluate at least four budget-matched recipes:

1. Stratified random from authorized examples.
2. Quality-ranked candidates, with source caps.
3. Coverage-first clustering/stratification.
4. Skill-gap-aware selection prioritizing verified task weaknesses.

Measure sample count, useful tokens, label verification rate, exact/semantic duplicate reduction, source diversity, tenant distribution **within allowed scope**, task coverage, evaluator disagreement, pre/post task success and general benchmark retention.

Do not tune recipes on the final test set. Use dev splits to choose them; once frozen, evaluate once on held-out tests and document the result.

## 6. Sampling and weighting

Weights influence example sampling, not policy. Cap per-source contribution and restrict near duplicate families. Give hard negative/corrective examples coverage so the model sees boundary conditions. Avoid oversampling common short greetings until they dominate learning and degrade other skills.

Model-aware selection (perplexity, loss improvement, influence) is experimental and should be evaluated against simpler baselines first. [PPL-Factory (AACL 2026)](https://aclanthology.org/2026.findings-aacl.202/) and [AutoSelection (EMNLP 2026)](https://aclanthology.org/2026.emnlp-main.1877/) motivate testing context-aware recipes, but neither proves that one ranking heuristic is optimal across KCM objectives.

## 7. Dataset build acceptance

- Every selected example is authorized, verified, non-revoked and linked to an immutable source.
- No leakage groups cross training/dev/test.
- No source-dedup conflict remains unresolved.
- No secret, sensitive prohibited data, prompt injection or unauthorized licensed content passes admission.
- Source, tokenizer/template, evaluator and recipe versions are reproducible.
- At least one random/stratified baseline exists for comparison.
- Frozen manifest digest matches bytes exactly, and train/test row counts are honest.
- Dataset deletion/revocation propagates via existing governance, with training-start and activation fences.
