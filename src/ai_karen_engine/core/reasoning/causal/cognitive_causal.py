"""
Cognitive Causal Reasoning - Human-Like Causal Understanding

Enhances causal reasoning with human-like cognitive capabilities:
- Metacognitive awareness of causal inference quality
- Uncertainty and confidence tracking
- Self-refinement of causal explanations
- Adaptive causal reasoning strategies
- Integration with cognitive orchestrator

Builds on Pearl's causal hierarchy with human-like cognition.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

from ai_karen_engine.core.reasoning.causal.engine import CausalIdentificationError

logger = logging.getLogger(__name__)


class CausalReasoningMode(Enum):
    """Modes for causal reasoning"""
    EXPLORATORY = "exploratory"       # Discover causal structure
    CONFIRMATORY = "confirmatory"     # Test specific hypotheses
    EXPLANATORY = "explanatory"       # Explain observed outcomes
    PREDICTIVE = "predictive"         # Predict intervention effects
    COUNTERFACTUAL = "counterfactual" # What-if reasoning


class EvidenceQuality(Enum):
    """Quality of causal evidence"""
    STRONG = "strong"                 # Experimental/RCT data
    MODERATE = "moderate"             # Observational with controls
    WEAK = "weak"                     # Correlational only
    SPECULATIVE = "speculative"       # Theoretical/hypothetical


@dataclass
class CausalHypothesis:
    """A causal hypothesis with confidence"""
    cause: str
    effect: str
    strength_estimate: float          # 0-1: estimated strength
    confidence: float                 # 0-1: confidence in hypothesis
    evidence_quality: EvidenceQuality
    supporting_evidence: List[str]
    alternative_explanations: List[str]
    confounders_identified: List[str]
    mechanism_proposed: Optional[str] = None


@dataclass
class CausalReasoningState:
    """Current state of causal reasoning"""
    mode: CausalReasoningMode
    confidence: float                 # Overall confidence in analysis
    certainty: float                  # Certainty about conclusions
    evidence_quality: EvidenceQuality
    identified_gaps: List[str]        # Missing information
    assumptions: List[str]            # Assumptions made
    alternative_models: int           # Number of plausible alternatives
    timestamp: float = field(default_factory=time.time)


@dataclass
class EnhancedCausalExplanation:
    """Enhanced causal explanation with confidence and alternatives"""
    outcome: str
    primary_explanation: str
    actual_causes: List[Tuple[str, float, float]]  # (Variable, contribution, confidence)
    necessary_causes: List[Tuple[str, float]]  # (Cause, confidence)
    sufficient_causes: List[Tuple[str, float]]  # (Cause, confidence)
    contributing_factors: List[Tuple[str, float, float]]  # (Factor, contribution, confidence)
    alternative_explanations: List[Tuple[str, float]]  # (Explanation, plausibility)
    confidence: float                  # Overall confidence
    evidence_quality: EvidenceQuality
    reasoning_trace: List[str]
    identified_gaps: List[str]
    assumptions: List[str]


@dataclass
class CounterfactualComparison:
    """Comparison between factual and counterfactual scenarios"""
    factual_outcome: Dict[str, Any]
    counterfactual_outcome: Dict[str, Any]
    differences: Dict[str, Tuple[Any, Any]]  # Variable -> (factual, counterfactual)
    causal_attribution: Dict[str, float]  # Variable -> causal contribution
    confidence: float
    plausibility: float               # How plausible is this counterfactual?


class CognitiveCausalReasoner:
    """
    Enhanced causal reasoner with human-like cognitive capabilities.

    Integrates:
    - Metacognitive monitoring of causal reasoning quality
    - Uncertainty quantification and confidence tracking
    - Self-refinement of causal explanations
    - Adaptive reasoning strategies
    - Multiple hypothesis consideration
    """

    def __init__(
        self,
        *,
        causal_engine: Optional[Any] = None,
        enable_metacognition: bool = True,
        enable_refinement: bool = True,
    ):
        self.causal_engine = causal_engine
        self.enable_metacognition = enable_metacognition
        self.enable_refinement = enable_refinement

        self._reasoning_history: List[CausalReasoningState] = []
        self._hypothesis_cache: Dict[Tuple[str, str], CausalHypothesis] = {}

        # Auto-initialize causal engine if not provided
        if self.causal_engine is None:
            try:
                from ai_karen_engine.core.reasoning.causal import CausalReasoningEngine
                self.causal_engine = CausalReasoningEngine()
            except ImportError:
                logger.warning("Could not initialize CausalReasoningEngine")

    def explain_outcome(
        self,
        outcome_variable: str,
        outcome_value: Any,
        context: Dict[str, Any],
        *,
        evidence_quality: Optional[EvidenceQuality] = None,
        consider_alternatives: bool = True,
    ) -> EnhancedCausalExplanation:
        """
        Generate enhanced causal explanation with confidence and alternatives.

        Args:
            outcome_variable: Variable to explain
            outcome_value: Observed value
            context: Context and observations
            evidence_quality: Quality of available evidence
            consider_alternatives: Whether to generate alternative explanations

        Returns:
            Enhanced causal explanation with confidence metrics
        """
        logger.info(f"Generating causal explanation for {outcome_variable} = {outcome_value}")

        reasoning_trace = []
        evidence_quality = evidence_quality or self._assess_evidence_quality(context)

        # Phase 1: Generate initial explanation
        reasoning_trace.append("Phase 1: Initial causal analysis")

        if self.causal_engine:
            try:
                basic_explanation = self.causal_engine.explain_outcome(
                    outcome_variable,
                    outcome_value,
                    context
                )
                reasoning_trace.append(f"Identified {len(basic_explanation.actual_causes)} potential causes")
            except CausalIdentificationError:
                # A separate causal identification contract is required.
                # Do not fabricate a confidence-weighted explanation here.
                raise
            except Exception as e:
                logger.error(f"Causal engine failed: {e}")
                basic_explanation = None
        else:
            basic_explanation = None

        # Phase 2: Assess confidence in each cause
        reasoning_trace.append("Phase 2: Confidence assessment")

        actual_causes_enhanced = []
        if basic_explanation:
            for cause, contribution in basic_explanation.actual_causes:
                confidence = self._assess_cause_confidence(
                    cause, outcome_variable, contribution, context, evidence_quality
                )
                actual_causes_enhanced.append((cause, contribution, confidence))
                reasoning_trace.append(f"  {cause}: contribution={contribution:.2f}, confidence={confidence:.2f}")

        # Sort by contribution * confidence (most reliable first)
        actual_causes_enhanced.sort(key=lambda x: x[1] * x[2], reverse=True)

        # Phase 3: Identify necessary and sufficient causes with confidence
        reasoning_trace.append("Phase 3: Necessity and sufficiency analysis")

        necessary_causes = []
        sufficient_causes = []

        if basic_explanation:
            for cause in basic_explanation.necessary_causes:
                conf = self._assess_necessity_confidence(cause, outcome_variable, context)
                necessary_causes.append((cause, conf))
                reasoning_trace.append(f"  Necessary: {cause} (confidence={conf:.2f})")

            for cause in basic_explanation.sufficient_causes:
                conf = self._assess_sufficiency_confidence(cause, outcome_variable, context)
                sufficient_causes.append((cause, conf))
                reasoning_trace.append(f"  Sufficient: {cause} (confidence={conf:.2f})")

        # Phase 4: Contributing factors
        contributing_factors = []
        if basic_explanation:
            for factor, contribution in basic_explanation.contributing_factors:
                conf = self._assess_cause_confidence(
                    factor, outcome_variable, contribution, context, evidence_quality
                )
                contributing_factors.append((factor, contribution, conf))

        # Phase 5: Alternative explanations
        reasoning_trace.append("Phase 4: Alternative explanations")

        alternative_explanations = []
        if consider_alternatives:
            alts = self._generate_alternative_explanations(
                outcome_variable, outcome_value, context, actual_causes_enhanced
            )
            alternative_explanations = alts
            reasoning_trace.append(f"  Generated {len(alts)} alternative explanations")

        # Phase 6: Overall confidence and gaps
        reasoning_trace.append("Phase 5: Overall assessment")

        overall_confidence = self._compute_overall_confidence(
            actual_causes_enhanced, evidence_quality, len(alternative_explanations)
        )

        identified_gaps = self._identify_causal_gaps(
            outcome_variable, context, actual_causes_enhanced
        )

        assumptions = self._identify_assumptions(context, evidence_quality)

        # Generate primary explanation text
        if actual_causes_enhanced:
            primary_cause, primary_contrib, primary_conf = actual_causes_enhanced[0]
            primary_explanation = (
                f"{outcome_variable} = {outcome_value} is primarily caused by {primary_cause} "
                f"(contribution: {primary_contrib:.2f}, confidence: {primary_conf:.2f})"
            )
        else:
            primary_explanation = f"Unable to determine clear cause for {outcome_variable} = {outcome_value}"

        reasoning_trace.append(f"Overall confidence: {overall_confidence:.2f}")
        reasoning_trace.append(f"Evidence quality: {evidence_quality.value}")

        return EnhancedCausalExplanation(
            outcome=f"{outcome_variable} = {outcome_value}",
            primary_explanation=primary_explanation,
            actual_causes=actual_causes_enhanced,
            necessary_causes=necessary_causes,
            sufficient_causes=sufficient_causes,
            contributing_factors=contributing_factors,
            alternative_explanations=alternative_explanations,
            confidence=overall_confidence,
            evidence_quality=evidence_quality,
            reasoning_trace=reasoning_trace,
            identified_gaps=identified_gaps,
            assumptions=assumptions,
        )

    def compare_counterfactuals(
        self,
        factual: Dict[str, Any],
        interventions: List[Tuple[str, Any]],
        *,
        variables_of_interest: Optional[List[str]] = None,
    ) -> CounterfactualComparison:
        """
        Compare factual and counterfactual scenarios.

        Args:
            factual: Factual observations
            interventions: Counterfactual interventions [(variable, value), ...]
            variables_of_interest: Variables to compare (if None, all variables)

        Returns:
            Detailed comparison with causal attribution
        """
        logger.info("Comparing counterfactual interventions, count=%d", len(interventions))
        if not interventions or not self.causal_engine:
            raise CausalIdentificationError("counterfactual_unidentifiable")

        # Predict counterfactual outcomes
        counterfactual_outcome = {}
        if self.causal_engine:
            for var, val in interventions:
                try:
                    outcomes = self.causal_engine.do_intervention(var, val, context=factual)
                    counterfactual_outcome.update(outcomes)
                except CausalIdentificationError:
                    # Do not convert missing counterfactual predictions into
                    # zero effects, differences or synthetic plausibility.
                    raise
                except Exception as e:
                    logger.warning(f"Intervention prediction failed for {var}: {e}")

        # Identify differences
        variables = variables_of_interest or list(factual.keys())
        differences = {}
        causal_attribution = {}

        for var in variables:
            factual_val = factual.get(var)
            counterfactual_val = counterfactual_outcome.get(var)

            if factual_val != counterfactual_val:
                differences[var] = (factual_val, counterfactual_val)

                # Attribute causality
                attribution = self._attribute_causality(
                    var, factual_val, counterfactual_val, interventions
                )
                causal_attribution[var] = attribution

        # Assess confidence and plausibility
        confidence = self._assess_counterfactual_confidence(
            interventions, factual, counterfactual_outcome
        )

        plausibility = self._assess_counterfactual_plausibility(
            interventions, factual
        )

        return CounterfactualComparison(
            factual_outcome=factual,
            counterfactual_outcome=counterfactual_outcome,
            differences=differences,
            causal_attribution=causal_attribution,
            confidence=confidence,
            plausibility=plausibility,
        )

    def refine_causal_hypothesis(
        self,
        hypothesis: CausalHypothesis,
        new_evidence: Dict[str, Any],
    ) -> CausalHypothesis:
        """
        Refine a causal hypothesis with new evidence.

        Args:
            hypothesis: Current hypothesis
            new_evidence: New observations/evidence

        Returns:
            Refined hypothesis with updated confidence
        """
        # Update confidence based on new evidence
        new_confidence = self._update_confidence(
            hypothesis.cause,
            hypothesis.effect,
            hypothesis.confidence,
            new_evidence,
        )

        # Check for new confounders
        new_confounders = self._identify_confounders(
            hypothesis.cause,
            hypothesis.effect,
            new_evidence,
        )

        # Update evidence quality
        combined_evidence = hypothesis.supporting_evidence + [str(new_evidence)]
        new_quality = self._assess_evidence_quality(new_evidence)

        # Adjust strength estimate
        new_strength = hypothesis.strength_estimate
        if new_confidence < hypothesis.confidence:
            new_strength *= 0.9  # Reduce if confidence dropped

        return CausalHypothesis(
            cause=hypothesis.cause,
            effect=hypothesis.effect,
            strength_estimate=new_strength,
            confidence=new_confidence,
            evidence_quality=new_quality,
            supporting_evidence=combined_evidence,
            alternative_explanations=hypothesis.alternative_explanations,
            confounders_identified=hypothesis.confounders_identified + new_confounders,
            mechanism_proposed=hypothesis.mechanism_proposed,
        )

    # Internal methods

    def _assess_evidence_quality(self, context: Dict[str, Any]) -> EvidenceQuality:
        """Assess quality of available evidence"""
        # Check for experimental indicators
        if any(k.startswith("experiment_") or k.startswith("rct_") for k in context.keys()):
            return EvidenceQuality.STRONG

        # Check for controlled observations
        if "controls" in context or "covariates" in context:
            return EvidenceQuality.MODERATE

        # Check data size
        data_size = context.get("n_observations", 0)
        if data_size < 10:
            return EvidenceQuality.SPECULATIVE
        elif data_size < 100:
            return EvidenceQuality.WEAK
        else:
            return EvidenceQuality.MODERATE

    def _assess_cause_confidence(
        self,
        cause: str,
        effect: str,
        contribution: float,
        context: Dict[str, Any],
        evidence_quality: EvidenceQuality,
    ) -> float:
        """Assess confidence in a causal relationship"""
        confidence = 0.5  # Base confidence

        # Evidence quality boost
        quality_boost = {
            EvidenceQuality.STRONG: 0.3,
            EvidenceQuality.MODERATE: 0.2,
            EvidenceQuality.WEAK: 0.1,
            EvidenceQuality.SPECULATIVE: 0.0,
        }
        confidence += quality_boost[evidence_quality]

        # Contribution strength boost
        confidence += min(0.2, contribution * 0.3)

        # Penalize if many alternatives
        if cause in context:
            confidence += 0.1  # Present in observations

        return max(0.0, min(1.0, confidence))

    def _assess_necessity_confidence(
        self,
        cause: str,
        effect: str,
        context: Dict[str, Any]
    ) -> float:
        """Assess confidence that cause is necessary for effect"""
        # Simplified: moderate confidence by default
        return 0.6

    def _assess_sufficiency_confidence(
        self,
        cause: str,
        effect: str,
        context: Dict[str, Any]
    ) -> float:
        """Assess confidence that cause is sufficient for effect"""
        # Simplified: lower confidence (sufficiency is harder to establish)
        return 0.5

    def _generate_alternative_explanations(
        self,
        outcome: str,
        value: Any,
        context: Dict[str, Any],
        primary_causes: List[Tuple[str, float, float]]
    ) -> List[Tuple[str, float]]:
        """Generate alternative causal explanations"""
        alternatives = []

        # Common alternative patterns
        if primary_causes:
            # Alternative: combination of multiple factors
            if len(primary_causes) >= 2:
                factors = [c[0] for c in primary_causes[:2]]
                alt = f"Combination of {' and '.join(factors)}"
                plausibility = 0.7
                alternatives.append((alt, plausibility))

            # Alternative: unmeasured confounder
            alternatives.append(("Unmeasured confounding factor", 0.5))

            # Alternative: reverse causation
            top_cause = primary_causes[0][0]
            alternatives.append((f"Reverse causation: {outcome} causes {top_cause}", 0.3))

        # Alternative: random chance
        alternatives.append(("Random variation / chance", 0.4))

        return alternatives

    def _compute_overall_confidence(
        self,
        causes: List[Tuple[str, float, float]],
        evidence_quality: EvidenceQuality,
        num_alternatives: int,
    ) -> float:
        """Compute overall confidence in causal explanation"""
        if not causes:
            return 0.1

        # Average confidence of top causes
        top_confidences = [c[2] for c in causes[:3]]
        avg_confidence = sum(top_confidences) / len(top_confidences)

        # Adjust for evidence quality
        quality_factor = {
            EvidenceQuality.STRONG: 1.0,
            EvidenceQuality.MODERATE: 0.85,
            EvidenceQuality.WEAK: 0.7,
            EvidenceQuality.SPECULATIVE: 0.5,
        }
        adjusted = avg_confidence * quality_factor[evidence_quality]

        # Penalize for many alternatives
        if num_alternatives > 3:
            adjusted *= 0.9

        return max(0.0, min(1.0, adjusted))

    def _identify_causal_gaps(
        self,
        outcome: str,
        context: Dict[str, Any],
        causes: List[Tuple[str, float, float]]
    ) -> List[str]:
        """Identify gaps in causal understanding"""
        gaps = []

        # Low overall contribution
        if causes:
            total_contribution = sum(c[1] for c in causes)
            if total_contribution < 0.7:
                gaps.append(f"Identified causes explain only {total_contribution:.1%} of outcome")

        # Missing mechanism
        if causes and not any("mechanism" in str(context).lower() for _ in [1]):
            gaps.append("Causal mechanisms not well understood")

        # Temporal information
        if not any(k.endswith("_time") or k.endswith("_timestamp") for k in context.keys()):
            gaps.append("Temporal ordering not established")

        # Sample size
        n = context.get("n_observations", 0)
        if n < 30:
            gaps.append(f"Small sample size (n={n}) limits confidence")

        return gaps

    def _identify_assumptions(
        self,
        context: Dict[str, Any],
        evidence_quality: EvidenceQuality
    ) -> List[str]:
        """Identify assumptions made in causal reasoning"""
        assumptions = [
            "Causal structure is stable over time",
            "No unmeasured confounding (or adequately controlled)",
        ]

        if evidence_quality in [EvidenceQuality.WEAK, EvidenceQuality.SPECULATIVE]:
            assumptions.append("Observational associations reflect causal relationships")

        if "controls" not in context:
            assumptions.append("No significant confounding variables")

        return assumptions

    def _attribute_causality(
        self,
        variable: str,
        factual_value: Any,
        counterfactual_value: Any,
        interventions: List[Tuple[str, Any]]
    ) -> float:
        """Attribute causal responsibility for difference"""
        # Simplified: attribute based on intervention proximity
        # In real implementation, would use causal graph structure

        for intervention_var, _ in interventions:
            if intervention_var == variable:
                return 1.0  # Direct intervention

        # Indirect effect
        return 0.5

    def _assess_counterfactual_confidence(
        self,
        interventions: List[Tuple[str, Any]],
        factual: Dict[str, Any],
        counterfactual: Dict[str, Any],
    ) -> float:
        """Assess confidence in counterfactual prediction"""
        # Base confidence
        confidence = 0.6

        # More interventions → less confidence
        if len(interventions) > 2:
            confidence *= 0.8

        # Check if interventions are within observed range
        # (simplified heuristic)
        confidence *= 0.9

        return confidence

    def _assess_counterfactual_plausibility(
        self,
        interventions: List[Tuple[str, Any]],
        factual: Dict[str, Any]
    ) -> float:
        """Assess plausibility of counterfactual scenario"""
        # Simplified: closer to factual → more plausible
        plausibility = 0.7

        # Small interventions → more plausible
        if len(interventions) == 1:
            plausibility += 0.2

        return min(1.0, plausibility)

    def _identify_confounders(
        self,
        cause: str,
        effect: str,
        evidence: Dict[str, Any]
    ) -> List[str]:
        """Identify potential confounders from evidence"""
        confounders = []

        # Simplified: look for related variables
        for key in evidence.keys():
            if key != cause and key != effect:
                if "control" in key.lower() or "covariate" in key.lower():
                    confounders.append(key)

        return confounders

    def _update_confidence(
        self,
        cause: str,
        effect: str,
        current_confidence: float,
        new_evidence: Dict[str, Any],
    ) -> float:
        """Update confidence based on new evidence"""
        # Bayesian-like update (simplified)
        new_conf = current_confidence

        # Boost if consistent evidence
        if cause in new_evidence and effect in new_evidence:
            new_conf += 0.1

        # Reduce if contradictory
        if "contradiction" in str(new_evidence).lower():
            new_conf -= 0.2

        return max(0.0, min(1.0, new_conf))


def create_cognitive_causal_reasoner(**kwargs) -> CognitiveCausalReasoner:
    """Factory function to create CognitiveCausalReasoner"""
    return CognitiveCausalReasoner(**kwargs)
