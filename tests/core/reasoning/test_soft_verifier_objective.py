from __future__ import annotations

from ai_karen_engine.core.reasoning.soft_reasoning.objective import (
    CandidateJudgment,
    VerifierGuidedObjective,
    VerifierObjectiveConfig,
)


class FakeJudge:
    def __init__(self, judgment: CandidateJudgment) -> None:
        self.judgment = judgment
        self.calls = 0
        self.last_evidence: tuple[str, ...] = ()

    def judge(self, objective: str, response: str, *, evidence):
        self.calls += 1
        self.last_evidence = tuple(evidence)
        return self.judgment


def test_objective_uses_structured_judge_scores_without_text_heuristics() -> None:
    judge = FakeJudge(
        CandidateJudgment(
            correctness=0.9,
            coherence=0.8,
            completeness=0.7,
            relevance=1.0,
            evidence_support=0.8,
            contradiction_penalty=0.0,
            confidence=0.9,
            feedback="supported",
        )
    )
    objective = VerifierGuidedObjective(judge)

    result = objective.score(
        "determine the supported conclusion",
        "candidate response",
        evidence=("evidence-a", "evidence-b"),
    )

    assert judge.calls == 1
    assert judge.last_evidence == ("evidence-a", "evidence-b")
    assert result.passed is True
    assert result.confidence == 0.9
    assert result.feedback == "supported"
    assert result.components["correctness"] == 0.9
    assert result.score > 0.75


def test_contradiction_penalty_reduces_bayesian_reward() -> None:
    base = dict(
        correctness=0.9,
        coherence=0.9,
        completeness=0.9,
        relevance=0.9,
        evidence_support=0.9,
        confidence=0.9,
    )
    clean = VerifierGuidedObjective(FakeJudge(CandidateJudgment(**base)))
    contradicted = VerifierGuidedObjective(
        FakeJudge(CandidateJudgment(**base, contradiction_penalty=1.0))
    )

    clean_score = clean.score("objective", "answer", evidence=()).score
    contradicted_score = contradicted.score("objective", "answer", evidence=()).score

    assert clean_score == 0.9
    assert contradicted_score == 0.65
    assert contradicted_score < clean_score


def test_low_judge_confidence_fails_acceptance_even_with_high_quality_score() -> None:
    judge = FakeJudge(
        CandidateJudgment(
            correctness=1.0,
            coherence=1.0,
            completeness=1.0,
            relevance=1.0,
            evidence_support=1.0,
            confidence=0.2,
        )
    )
    objective = VerifierGuidedObjective(judge)

    result = objective.score("objective", "answer", evidence=())

    assert result.score == 1.0
    assert result.passed is False


def test_empty_candidate_fails_closed_without_invoking_judge() -> None:
    judge = FakeJudge(
        CandidateJudgment(
            correctness=1.0,
            coherence=1.0,
            completeness=1.0,
            relevance=1.0,
            evidence_support=1.0,
            confidence=1.0,
        )
    )
    objective = VerifierGuidedObjective(judge)

    result = objective.score("objective", "   ", evidence=())

    assert judge.calls == 0
    assert result.score == 0.0
    assert result.passed is False
    assert result.feedback == "empty_candidate_response"


def test_thresholds_are_configurable_but_bounded() -> None:
    judge = FakeJudge(
        CandidateJudgment(
            correctness=0.6,
            coherence=0.6,
            completeness=0.6,
            relevance=0.6,
            evidence_support=0.6,
            confidence=0.8,
        )
    )
    objective = VerifierGuidedObjective(
        judge,
        VerifierObjectiveConfig(acceptance_threshold=0.55),
    )

    assert objective.score("objective", "answer", evidence=()).passed is True
