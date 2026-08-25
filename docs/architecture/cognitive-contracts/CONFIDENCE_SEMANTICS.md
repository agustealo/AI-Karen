# Confidence Semantics

"Confidence" is currently at risk of becoming a universal mystery number. This document inventories every confidence field and assigns its meaning.

## Inventory

| Source | Field name | Domain | Meaning |
| ------ | ---------- | ------ | ------- |
| memory/contracts.py | MemoryClaim.confidence | memory | Epistemic confidence in a stored claim (0-1) |
| memory/contracts.py | SelfModel.confidence | memory | Karen's confidence in her self-model accuracy |
| reasoning/belief/contracts.py | BeliefClaim.confidence | belief | Overall epistemic confidence in a belief |
| reasoning/belief/contracts.py | ConfidenceMetrics | belief | Multi-dimensional confidence breakdown |
| reasoning/belief/contracts.py | Evidence.confidence | belief | Confidence that evidence is authentic/accurate |
| reasoning/contracts.py | ReasoningEvidence.confidence | reasoning | Confidence in evidence relevance/strength |
| reasoning/contracts.py | ReasoningHypothesis.confidence | reasoning | Confidence in a generated hypothesis |
| reasoning/contracts.py | ReasoningAssessment.confidence | reasoning | Confidence in overall reasoning quality |
| reasoning/meta/contracts.py | MetaCognitiveState.confidence | meta | Aggregate meta-cognitive confidence |
| reasoning/meta/contracts.py | MetaAssessment.confidence | meta | Confidence in meta-assessment itself |
| reasoning/meta/contracts.py | StrategyAttempt.confidence | meta | Confidence that a strategy attempt was sound |
| reasoning/meta/contracts.py | MemoryReliabilityAssessment.recall_confidence | meta | Confidence that recalled memory is reliable |
| reasoning/meta/contracts.py | ReasoningDepthRecommendation.confidence | meta | Confidence in recommended reasoning depth |
| reasoning/meta/contracts.py | CalibrationObservation.predicted_confidence | meta | Previously predicted confidence |
| adaptive/contracts.py | ScoreComponents.confidence | adaptive | Confidence in utility score calculation |
| adaptive/contracts.py | AdaptiveRecommendation.confidence | adaptive | Confidence that recommendation is correct |
| adaptive/contracts.py | SuggestionCandidate.confidence | adaptive | Confidence that suggestion is helpful |
| adaptive/contracts.py | CapabilityPerformanceProfile.confidence_interval | adaptive | Statistical confidence interval |
| adaptive/salience/contracts.py | SalienceSignal.confidence | adaptive | Confidence in salience dimension signal |
| adaptive/salience/contracts.py | SalienceAssessment.confidence | adaptive | Confidence in overall salience assessment |
| cortex/contracts.py | IntentSignal.confidence | cortex | Confidence in intent classification |
| cortex/contracts.py | ReasoningResult.confidence | cortex | Confidence in reasoning result |
| cortex/behavior/contracts.py | BehaviorCandidate.confidence | cortex | Confidence that behavior candidate is optimal |
| cortex/behavior/contracts.py | BehaviorDecision.confidence | cortex | Confidence in final behavior decision |
| personalization/contracts.py | Provenance.confidence | personalization | Confidence in inferred model property |
| personalization/contracts.py | PreferenceRecord.confidence | personalization | Confidence that preference is accurate |
| personalization/contracts.py | BehaviorPattern.confidence | personalization | Confidence in repeated behavior pattern |
| personalization/contracts.py | UserGoal.confidence | personalization | Confidence that goal is still valid |
| adaptive/learning/experience/contracts.py | LearningSignal.outcome_confidence | learning | Confidence in observed outcome correctness |
| adaptive/learning/experience/contracts.py | ProfileUpdateCandidate.confidence | learning | Confidence that profile update is beneficial |

## Prohibited conversions

The following conversions are **not** allowed without explicit transformation and documentation:

| Source confidence | Cannot equal | Why |
| ----------------- | ------------ | ---- |
| recall confidence | belief truth probability | Recall confidence measures retrieval quality, not epistemic truth |
| salience confidence | behavior confidence | Salience confidence measures signal reliability; behavior confidence measures action optimality |
| model confidence | policy eligibility | Model confidence is predictive; policy eligibility is normative |
| evidence confidence | claim confidence | Evidence confidence measures source trust; claim confidence measures overall belief strength |
| hypothesis confidence | reasoning confidence | Hypothesis confidence is local; reasoning confidence is global across strategy |
| preference confidence | user goal confidence | Preference confidence measures taste stability; goal confidence measures intention validity |

## Recommended canonical confidence types

| Canonical type | Owner | Definition |
| -------------- | ----- | ---------- |
| `EpistemicConfidence` | reasoning/belief | Multi-dimensional belief confidence |
| `RetrievalConfidence` | memory | Recall quality and relevance confidence |
| `SalienceConfidence` | adaptive/salience | Signal reliability confidence |
| `BehaviorConfidence` | cortex/behavior | Action selection confidence |
| `MetaConfidence` | reasoning/meta | Confidence in cognitive self-assessment |
| `PreferenceConfidence` | personalization | User preference stability confidence |
| `LearningConfidence` | adaptive/learning | Experience outcome confidence |
