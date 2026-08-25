"""
Self-Refine: Iterative Refinement with Self-Feedback

Implements the Self-Refine approach from the paper:
"Self-Refine: Iterative Refinement with Self-Feedback" (arXiv:2303.17651)

Key concepts:
- Iterative refinement mimicking human revision process
- Self-feedback generation without external supervision
- Multi-criteria evaluation and targeted improvement
- Convergence detection to prevent over-refinement
- Integration with verifier for quality assessment
"""

from __future__ import annotations

import logging
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger(__name__)


class RefinementStage(Enum):
    """Stages of the self-refinement process"""
    INITIAL_GENERATION = "initial_generation"
    FEEDBACK_GENERATION = "feedback_generation"
    REFINEMENT = "refinement"
    VERIFICATION = "verification"
    CONVERGENCE_CHECK = "convergence_check"


@dataclass
class FeedbackPoint:
    """Individual piece of feedback"""
    criterion: str                    # What aspect (e.g., "coherence", "accuracy")
    issue: str                        # What's wrong
    suggestion: str                   # How to improve
    severity: float                   # 0-1, how critical this is
    location: Optional[str] = None    # Which part of the output (optional)


@dataclass
class RefinementIteration:
    """Record of a single refinement iteration"""
    iteration: int
    stage: RefinementStage
    output: str
    feedback: List[FeedbackPoint]
    quality_score: float
    improvement: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class RefinementConfig:
    """Configuration for self-refinement process"""
    max_iterations: int = 5
    min_quality_score: float = 0.8
    convergence_threshold: float = 0.05  # Stop if improvement < this
    enable_self_feedback: bool = True
    enable_verifier_feedback: bool = True
    feedback_temperature: float = 0.7    # Higher = more creative feedback
    refinement_temperature: float = 0.5  # Lower = more focused refinement
    early_stopping: bool = True
    min_iterations: int = 1              # Always do at least 1 refinement


@dataclass
class RefinementResult:
    """Result from self-refinement process"""
    final_output: str
    initial_output: str
    iterations: List[RefinementIteration]
    converged: bool
    total_iterations: int
    initial_quality: float
    final_quality: float
    improvement: float
    total_time: float


class SelfRefiner:
    """
    Self-Refine engine for iterative improvement of LLM outputs.

    Implements human-like cognitive process:
    1. Generate initial output
    2. Self-critique and identify issues
    3. Refine based on feedback
    4. Verify improvements
    5. Repeat until convergence or quality threshold met
    """

    def __init__(
        self,
        *,
        llm: Optional[Any] = None,
        verifier: Optional[Any] = None,
        config: Optional[RefinementConfig] = None,
    ):
        self.llm = llm
        self.verifier = verifier
        self.config = config or RefinementConfig()

    def refine(
        self,
        query: str,
        initial_output: Optional[str] = None,
        *,
        context: Optional[List[str]] = None,
        criteria: Optional[List[str]] = None,
    ) -> RefinementResult:
        """
        Refine an output iteratively using self-feedback.

        Args:
            query: Original query/prompt
            initial_output: Initial output to refine (if None, generates one)
            context: Optional context information
            criteria: Specific criteria to focus on (e.g., ["accuracy", "completeness"])

        Returns:
            RefinementResult with refinement history and final output
        """
        start_time = time.time()
        iterations: List[RefinementIteration] = []

        # Generate initial output if not provided
        if initial_output is None:
            initial_output = self._generate_initial(query, context)

        current_output = initial_output
        current_quality = self._assess_quality(query, current_output, context)

        logger.info(f"Self-Refine starting: initial quality {current_quality:.3f}")

        # Iterative refinement loop
        converged = False
        for iteration in range(self.config.max_iterations):
            # Generate feedback
            feedback = self._generate_feedback(
                query=query,
                output=current_output,
                context=context,
                criteria=criteria,
            )

            # If no significant issues found, we can stop early
            if not feedback and iteration >= self.config.min_iterations:
                logger.info(f"No significant issues found at iteration {iteration}")
                converged = True
                break

            # Refine based on feedback
            refined_output = self._apply_refinement(
                query=query,
                output=current_output,
                feedback=feedback,
                context=context,
            )

            # Assess quality of refinement
            new_quality = self._assess_quality(query, refined_output, context)
            improvement = new_quality - current_quality

            # Record iteration
            iterations.append(RefinementIteration(
                iteration=iteration,
                stage=RefinementStage.REFINEMENT,
                output=refined_output,
                feedback=feedback,
                quality_score=new_quality,
                improvement=improvement,
            ))

            logger.debug(
                f"Iteration {iteration}: quality {new_quality:.3f} "
                f"(Δ{improvement:+.3f})"
            )

            # Check convergence
            if iteration >= self.config.min_iterations:
                # Quality threshold met
                if new_quality >= self.config.min_quality_score:
                    logger.info(f"Quality threshold reached: {new_quality:.3f}")
                    converged = True
                    current_output = refined_output
                    current_quality = new_quality
                    break

                # Diminishing returns
                if abs(improvement) < self.config.convergence_threshold:
                    logger.info(f"Converged: improvement {improvement:.3f} below threshold")
                    converged = True
                    current_output = refined_output
                    current_quality = new_quality
                    break

                # Quality degradation
                if improvement < -0.1 and self.config.early_stopping:
                    logger.warning(f"Quality decreased by {improvement:.3f}, stopping")
                    # Don't use the worse output
                    break

            # Continue with refined output
            current_output = refined_output
            current_quality = new_quality

        total_time = time.time() - start_time
        initial_quality = self._assess_quality(query, initial_output, context)

        return RefinementResult(
            final_output=current_output,
            initial_output=initial_output,
            iterations=iterations,
            converged=converged,
            total_iterations=len(iterations),
            initial_quality=initial_quality,
            final_quality=current_quality,
            improvement=current_quality - initial_quality,
            total_time=total_time,
        )

    def _generate_initial(self, query: str, context: Optional[List[str]]) -> str:
        """Generate initial output"""
        if self.llm is None:
            # Fallback placeholder
            return "Initial output placeholder"

        prompt = self._build_initial_prompt(query, context)

        try:
            from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
            if isinstance(self.llm, LLMUtils):
                return self.llm.generate_text(prompt, max_tokens=500)
            else:
                # Try generic generate method
                return str(self.llm.generate(prompt))
        except Exception as e:
            logger.error(f"Error generating initial output: {e}")
            return f"Error: {str(e)}"

    def _generate_feedback(
        self,
        query: str,
        output: str,
        context: Optional[List[str]],
        criteria: Optional[List[str]],
    ) -> List[FeedbackPoint]:
        """Generate self-feedback on current output"""
        feedback_points: List[FeedbackPoint] = []

        # Use verifier if available
        if self.verifier is not None and self.config.enable_verifier_feedback:
            try:
                verification = self.verifier.verify(
                    query=query,
                    response=output,
                    context=context,
                )

                # Convert verifier scores to feedback
                for criterion, score in verification.criterion_scores.items():
                    if score < 0.7:  # Below good threshold
                        feedback_points.append(FeedbackPoint(
                            criterion=criterion.value,
                            issue=f"Score {score:.2f} is below target",
                            suggestion=f"Improve {criterion.value} aspect",
                            severity=1.0 - score,
                        ))
            except Exception as e:
                logger.warning(f"Verifier feedback failed: {e}")

        # Generate self-feedback via LLM
        if self.llm is not None and self.config.enable_self_feedback:
            try:
                feedback_text = self._generate_self_feedback_text(
                    query, output, context, criteria
                )

                # Parse feedback text into structured points
                parsed = self._parse_feedback(feedback_text, criteria)
                feedback_points.extend(parsed)
            except Exception as e:
                logger.warning(f"Self-feedback generation failed: {e}")

        # Sort by severity (most critical first)
        feedback_points.sort(key=lambda f: f.severity, reverse=True)

        return feedback_points

    def _generate_self_feedback_text(
        self,
        query: str,
        output: str,
        context: Optional[List[str]],
        criteria: Optional[List[str]],
    ) -> str:
        """Generate self-feedback as text using LLM"""
        criteria_list = criteria or ["accuracy", "completeness", "coherence", "relevance"]
        criteria_str = ", ".join(criteria_list)

        prompt = f"""Review the following response and provide constructive feedback.

Query: {query}

Response to Review:
{output}

Please evaluate the response on these criteria: {criteria_str}

For each issue you identify, provide:
1. What the issue is
2. Why it's problematic
3. How to improve it

Be specific and actionable. Focus on the most important issues.

Feedback:"""

        try:
            from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
            if isinstance(self.llm, LLMUtils):
                return self.llm.generate_text(
                    prompt,
                    max_tokens=300,
                    temperature=self.config.feedback_temperature
                )
            return ""
        except Exception:
            return ""

    def _parse_feedback(
        self,
        feedback_text: str,
        criteria: Optional[List[str]]
    ) -> List[FeedbackPoint]:
        """Parse feedback text into structured FeedbackPoints"""
        points = []

        # Simple heuristic parsing
        lines = feedback_text.split('\n')
        current_issue = None
        current_suggestion = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect issue statements
            if any(marker in line.lower() for marker in ['issue:', 'problem:', 'lacks', 'missing']):
                if current_issue and current_suggestion:
                    points.append(FeedbackPoint(
                        criterion="general",
                        issue=current_issue,
                        suggestion=current_suggestion,
                        severity=0.6,
                    ))
                current_issue = line
                current_suggestion = None

            # Detect suggestions
            elif any(marker in line.lower() for marker in ['suggest:', 'should', 'improve', 'add', 'include']):
                current_suggestion = line

        # Add last point
        if current_issue and current_suggestion:
            points.append(FeedbackPoint(
                criterion="general",
                issue=current_issue,
                suggestion=current_suggestion,
                severity=0.6,
            ))

        return points

    def _apply_refinement(
        self,
        query: str,
        output: str,
        feedback: List[FeedbackPoint],
        context: Optional[List[str]],
    ) -> str:
        """Apply refinement based on feedback"""
        if not feedback:
            return output

        if self.llm is None:
            return output

        # Build refinement prompt
        feedback_summary = "\n".join([
            f"- {fp.criterion}: {fp.issue}. {fp.suggestion}"
            for fp in feedback[:5]  # Top 5 most critical
        ])

        prompt = f"""Improve the following response based on the feedback provided.

Original Query: {query}

Current Response:
{output}

Feedback to Address:
{feedback_summary}

Provide an improved response that addresses the feedback while maintaining the good aspects of the original.

Improved Response:"""

        try:
            from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
            if isinstance(self.llm, LLMUtils):
                refined = self.llm.generate_text(
                    prompt,
                    max_tokens=600,
                    temperature=self.config.refinement_temperature
                )
                return refined.strip()
            return output
        except Exception as e:
            logger.error(f"Refinement failed: {e}")
            return output

    def _assess_quality(
        self,
        query: str,
        output: str,
        context: Optional[List[str]]
    ) -> float:
        """Assess quality of output"""
        if self.verifier is not None:
            try:
                result = self.verifier.verify(
                    query=query,
                    response=output,
                    context=context,
                )
                return result.overall_score
            except Exception as e:
                logger.warning(f"Quality assessment failed: {e}")

        # Fallback heuristic
        return self._heuristic_quality(output)

    def _heuristic_quality(self, output: str) -> float:
        """Simple heuristic quality score"""
        score = 0.5

        # Length check
        words = len(output.split())
        if 20 <= words <= 300:
            score += 0.2
        elif words > 300:
            score += 0.1

        # Sentence structure
        sentences = output.count('.') + output.count('?') + output.count('!')
        if sentences >= 2:
            score += 0.2

        # Avoid hedge words
        hedge_words = ['maybe', 'perhaps', 'possibly', 'might']
        if not any(hw in output.lower() for hw in hedge_words):
            score += 0.1

        return min(1.0, score)

    def _build_initial_prompt(
        self,
        query: str,
        context: Optional[List[str]]
    ) -> str:
        """Build prompt for initial generation"""
        if context:
            context_str = "\n".join(f"- {c}" for c in context)
            return f"Context:\n{context_str}\n\nQuery: {query}\n\nResponse:"
        return f"Query: {query}\n\nResponse:"


def create_self_refiner(
    llm: Optional[Any] = None,
    verifier: Optional[Any] = None,
    **config_kwargs
) -> SelfRefiner:
    """
    Factory function to create a SelfRefiner instance.

    Args:
        llm: LLM instance for generation
        verifier: Verifier instance for quality assessment
        **config_kwargs: Configuration parameters

    Returns:
        Configured SelfRefiner instance
    """
    config = RefinementConfig(**config_kwargs) if config_kwargs else None

    # Auto-create verifier if not provided
    if verifier is None:
        try:
            from ai_karen_engine.core.reasoning.soft_reasoning.verifier import ReasoningVerifier
            verifier = ReasoningVerifier()
        except ImportError:
            logger.warning("Could not import ReasoningVerifier, proceeding without")

    # Auto-create LLM if not provided
    if llm is None:
        try:
            from ai_karen_engine.core.model_runtime.llm_adapter import LLMUtils
            llm = LLMUtils()
        except ImportError:
            logger.warning("Could not import LLMUtils, proceeding without")

    return SelfRefiner(llm=llm, verifier=verifier, config=config)
