# Cognitive Contract Ledger

Audit date: 2026-08-24
Scope: `core/memory/`, `core/neuro_recall/`, `core/personalization/`, `core/reasoning/`, `core/context/`, `core/adaptive/`, `core/cortex/`

## Public Contract Inventory

| Concept                  | Canonical owner        | Definition location | Consumers                              | Duplicate?             | Action       |
| ------------------------ | ---------------------- | ------------------- | -------------------------------------- | ---------------------- | ------------ |
| ReasoningDepth           | reasoning/meta         | reasoning/meta/contracts.py:51 | meta, cortex, KIRE                      | yes (cortex/contracts.py:24) | converge     |
| ClaimStatus              | memory                 | memory/contracts.py:27 | memory, belief, cortex                  | yes (reasoning/belief/contracts.py:32) | canonicalize |
| EvidenceType             | reasoning/belief       | reasoning/belief/contracts.py:68 | belief, goals                           | yes (personalization/goals/contracts.py:173) | converge     |
| GoalState                | personalization/goals  | personalization/goals/contracts.py:57 | cortex, goals                           | yes (personalization/contracts.py UserGoalStatus) | converge     |
| VerificationDepth        | cortex/behavior        | cortex/behavior/contracts.py:65 | behavior, KIRE                          | yes (reasoning/meta/contracts.py ReasoningDepth used) | canonicalize |
| Confidence               | belief                 | reasoning/belief/contracts.py: ConfidenceMetrics | meta, cortex, adaptive                  | overloaded (30+ float fields) | split        |
| Salience                 | adaptive/salience      | adaptive/salience/contracts.py:9 | context, memory, goals, cortex          | no                     | keep         |
| GoalSnapshot             | personalization/goals  | personalization/goals/contracts.py:373 | cortex, adaptive                        | no (exists as GoalSnapshot) | keep         |
| MemoryStatus             | memory/types           | memory/types/base.py:94 | memory, cortex                          | no                     | keep         |
| PreferenceState          | personalization        | personalization/contracts.py:45 | personalization, adaptive               | no                     | keep         |
| BehaviorType             | cortex/behavior        | cortex/behavior/contracts.py:9 | cortex, adaptive                        | no                     | keep         |
| SuggestionFeedbackType   | adaptive               | adaptive/contracts.py:61 | adaptive, suggestions                   | yes (adaptive/suggestions/contracts.py:14) | converge     |
| LearningScope            | adaptive/learning      | adaptive/learning/experience/contracts.py:32 | adaptive learning                       | no                     | keep         |
| OutcomeStatus            | adaptive/learning      | adaptive/learning/experience/contracts.py:44 | adaptive learning                       | no                     | keep         |
| RelationshipType         | personalization        | personalization/contracts.py:137 | personalization, cortex                 | no                     | keep         |
| EvidenceStrength         | reasoning/belief       | reasoning/belief/contracts.py:90 | belief, meta                            | no                     | keep         |
| MetaStatus               | reasoning/meta         | reasoning/meta/contracts.py:21 | meta, CORTEX                            | no                     | keep         |
| UserGoalStatus           | personalization        | personalization/contracts.py:86 | personalization, goals                  | yes (personalization/goals/contracts.py GoalState) | converge     |

## Duplicate Enum Classification

| Enum name                | Locations | Classification       | Canonical owner        | Action                          |
| ------------------------- | --------- | --------------------- | ---------------------- | ------------------------------- |
| ReasoningDepth            | reasoning/meta, cortex | IDENTICAL_DUPLICATE | reasoning contracts | Re-export from reasoning during COG-CLOSE-1 |
| ClaimStatus               | memory, reasoning/belief | SEMANTICALLY_DIFFERENT | memory | Canonicalize in memory; belief imports |
| EvidenceType              | reasoning/belief, personalization/goals | IDENTICAL_DUPLICATE | reasoning/belief | Re-export from belief during COG-CLOSE-1 |
| GoalState / UserGoalStatus | personalization/goals, personalization | SEMANTICALLY_DIFFERENT | personalization/goals | Converge during COG-CLOSE-1; GoalState is richer |
| SuggestionFeedbackType    | adaptive, adaptive/suggestions | IDENTICAL_DUPLICATE | adaptive | Remove duplicate from suggestions during COG-CLOSE-1 |
| DriftState / DriftStatus  | personalization, adaptive/drift | SEMANTICALLY_DIFFERENT | adaptive/drift | Keep separate; rename personalization DriftState to PreferenceDriftState |
| ContradictionSeverity     | reasoning, cortex/behavior | IDENTICAL_DUPLICATE (both have LOW/MEDIUM/HIGH/CRITICAL) | reasoning | Re-export from reasoning during COG-CLOSE-1 |

## Concept Boundaries

| Concept                  | Current boundary problem | Recommended fix |
| ------------------------- | ----------------------- | --------------- |
| reasoning depth           | Defined in meta, duplicated in cortex | Single source in reasoning contracts; cortex imports |
| confidence                | 30+ float fields named `confidence` across domains | Split into typed confidence dataclasses per domain |
| verification requirement  | Independent logic in meta and behavior | Meta recommends; behavior decides; single VerificationRequirement contract |
| salience                  | Clean boundary; adaptive owns it | Keep |
| goal snapshot             | GoalSnapshot exists in goals | Export through personalization contracts to cortex |
