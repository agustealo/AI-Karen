from __future__ import annotations

from typing import Any

from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import EvaluationCase


class CanonicalEvaluationCorpus:
    DATASET_VERSION = "ml-eval-v1"

    @classmethod
    def all_cases(cls) -> list[EvaluationCase]:
        cases: list[EvaluationCase] = []
        cases.extend(cls.intent_cases())
        cases.extend(cls.domain_cases())
        cases.extend(cls.complexity_cases())
        cases.extend(cls.ambiguity_cases())
        cases.extend(cls.memory_relevance_cases())
        cases.extend(cls.capability_cases())
        cases.extend(cls.adversarial_cases())
        return cases

    @classmethod
    def get_cases(
        cls,
        task: PredictionTask | None = None,
        difficulty: str | None = None,
        tags: list[str] | None = None,
        case_ids: list[str] | None = None,
    ) -> list[EvaluationCase]:
        cases = cls.all_cases()
        if task is not None:
            cases = [c for c in cases if c.task == task]
        if difficulty is not None:
            cases = [c for c in cases if c.difficulty == difficulty]
        if tags:
            cases = [c for c in cases if any(t in c.tags for t in tags)]
        if case_ids:
            cases = [c for c in cases if c.case_id in case_ids]
        return cases

    @classmethod
    def intent_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="intent-001",
                task=PredictionTask.INTENT,
                input_text="What is machine learning?",
                expected_label="information_seeking",
                tags=["information_seeking", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-002",
                task=PredictionTask.INTENT,
                input_text="I need help writing a Python script to parse CSV files.",
                expected_label="task_completion",
                tags=["task_completion", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-003",
                task=PredictionTask.INTENT,
                input_text="My application crashes on startup with a segmentation fault.",
                expected_label="problem_solving",
                tags=["problem_solving", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-004",
                task=PredictionTask.INTENT,
                input_text="Write me a short story about a robot learning to paint.",
                expected_label="creative_assistance",
                tags=["creative_assistance", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-005",
                task=PredictionTask.INTENT,
                input_text="Should I use React or Vue for my next project?",
                expected_label="decision_making",
                tags=["decision_making", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-006",
                task=PredictionTask.INTENT,
                input_text="Tell me a joke about programming.",
                expected_label="social_interaction",
                tags=["social_interaction", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="intent-007",
                task=PredictionTask.INTENT,
                input_text="Explain quantum computing and also write a poem about it.",
                expected_label="information_seeking",
                tags=["information_seeking", "multi_intent", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="intent-008",
                task=PredictionTask.INTENT,
                input_text="I don't want to learn about history right now.",
                expected_label="information_seeking",
                tags=["information_seeking", "negation", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="intent-009",
                task=PredictionTask.INTENT,
                input_text="Oh great, another bug in the production code.",
                expected_label="problem_solving",
                tags=["problem_solving", "sarcasm", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="intent-010",
                task=PredictionTask.INTENT,
                input_text="Do it.",
                expected_label="task_completion",
                tags=["task_completion", "short", "adversarial"],
                difficulty="hard",
            ),
        ]

    @classmethod
    def domain_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="domain-001",
                task=PredictionTask.DOMAIN,
                input_text="I need to write some Python code and debug the failing unit tests.",
                expected_label="software_development",
                tags=["software_development", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-002",
                task=PredictionTask.DOMAIN,
                input_text="Can you help me analyze this dataset and write a research paper?",
                expected_label="research",
                tags=["research", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-003",
                task=PredictionTask.DOMAIN,
                input_text="What is the revenue growth strategy for our company this quarter?",
                expected_label="business",
                tags=["business", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-004",
                task=PredictionTask.DOMAIN,
                input_text="I need to file my taxes and understand investment options.",
                expected_label="finance",
                tags=["finance", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-005",
                task=PredictionTask.DOMAIN,
                input_text="Send an email to the team and schedule a meeting for next week.",
                expected_label="communication",
                tags=["communication", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-006",
                task=PredictionTask.DOMAIN,
                input_text="Add a dentist appointment to my calendar for Friday.",
                expected_label="calendar",
                tags=["calendar", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-007",
                task=PredictionTask.DOMAIN,
                input_text="The plumber needs to fix the leaky faucet in the kitchen.",
                expected_label="home_services",
                tags=["home_services", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-008",
                task=PredictionTask.DOMAIN,
                input_text="Help me understand how to bake bread.",
                expected_label="general",
                tags=["general", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="domain-009",
                task=PredictionTask.DOMAIN,
                input_text="Analyze the stock market data while also deploying my web application.",
                expected_label="software_development",
                tags=["software_development", "mixed_domain", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="domain-010",
                task=PredictionTask.DOMAIN,
                input_text="That's a run of the mill solution, just like any other.",
                expected_label="general",
                tags=["general", "tool_like_words", "adversarial"],
                difficulty="hard",
            ),
        ]

    @classmethod
    def complexity_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="complexity-001",
                task=PredictionTask.COMPLEXITY,
                input_text="Yes.",
                expected_label="simple",
                tags=["simple", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 1, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="complexity-002",
                task=PredictionTask.COMPLEXITY,
                input_text="Run the tests and deploy the service.",
                expected_label="moderate",
                tags=["moderate", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 7, "sentence_count": 1, "entity_count": 1},
            ),
            EvaluationCase(
                case_id="complexity-003",
                task=PredictionTask.COMPLEXITY,
                input_text="Analyze the distributed system architecture and propose optimizations for the database layer while ensuring backward compatibility.",
                expected_label="complex",
                tags=["complex", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 20, "sentence_count": 1, "entity_count": 4},
            ),
            EvaluationCase(
                case_id="complexity-004",
                task=PredictionTask.COMPLEXITY,
                input_text="Set up the CI pipeline, configure the load balancer, and migrate the database schema without downtime.",
                expected_label="complex",
                tags=["complex", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 16, "sentence_count": 1, "entity_count": 3},
            ),
            EvaluationCase(
                case_id="complexity-005",
                task=PredictionTask.COMPLEXITY,
                input_text="Hi.",
                expected_label="simple",
                tags=["simple", "short", "adversarial"],
                difficulty="easy",
                features={"token_count": 1, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="complexity-006",
                task=PredictionTask.COMPLEXITY,
                input_text="Please kindly help me with this small thing if you would be so kind as to assist me when you have a moment.",
                expected_label="simple",
                tags=["simple", "long_but_simple", "adversarial"],
                difficulty="hard",
                features={"token_count": 24, "sentence_count": 1, "entity_count": 0},
            ),
        ]

    @classmethod
    def ambiguity_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="ambiguity-001",
                task=PredictionTask.AMBIGUITY,
                input_text="Run the integration tests in the src directory and report any failures.",
                expected_label="clear",
                tags=["clear", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 14, "sentence_count": 1, "entity_count": 2},
            ),
            EvaluationCase(
                case_id="ambiguity-002",
                task=PredictionTask.AMBIGUITY,
                input_text="Fix the issue.",
                expected_label="moderate",
                tags=["moderate", "direct", "normal"],
                difficulty="normal",
                features={"token_count": 3, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="ambiguity-003",
                task=PredictionTask.AMBIGUITY,
                input_text="It.",
                expected_label="ambiguous",
                tags=["ambiguous", "short", "adversarial"],
                difficulty="normal",
                features={"token_count": 1, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="ambiguity-004",
                task=PredictionTask.AMBIGUITY,
                input_text="Do it.",
                expected_label="ambiguous",
                tags=["ambiguous", "short", "adversarial"],
                difficulty="normal",
                features={"token_count": 2, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="ambiguity-005",
                task=PredictionTask.AMBIGUITY,
                input_text="Handle the thing.",
                expected_label="ambiguous",
                tags=["ambiguous", "pronoun_heavy", "adversarial"],
                difficulty="normal",
                features={"token_count": 3, "sentence_count": 1, "entity_count": 0},
            ),
            EvaluationCase(
                case_id="ambiguity-006",
                task=PredictionTask.AMBIGUITY,
                input_text="The analysis of the system we discussed yesterday needs to be completed before the meeting.",
                expected_label="moderate",
                tags=["moderate", "context_dependent", "normal"],
                difficulty="hard",
                features={"token_count": 16, "sentence_count": 1, "entity_count": 2},
            ),
        ]

    @classmethod
    def memory_relevance_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="memory-001",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="Remember what we discussed about the API design yesterday.",
                expected_label="relevant",
                tags=["relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-002",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="As I mentioned before, my preferred language is Python.",
                expected_label="relevant",
                tags=["relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-003",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="Recall the previous conversation about database migration.",
                expected_label="relevant",
                tags=["relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-004",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="Continue from where we left off on the refactoring task.",
                expected_label="relevant",
                tags=["relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-005",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="What is the capital of France?",
                expected_label="not_relevant",
                tags=["not_relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-006",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="Tell me a joke about cats.",
                expected_label="not_relevant",
                tags=["not_relevant", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="memory-007",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="As I mentioned before, the sky is blue and water is wet.",
                expected_label="not_relevant",
                tags=["not_relevant", "irrelevant_memory_mention", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="memory-008",
                task=PredictionTask.MEMORY_RELEVANCE,
                input_text="My project uses React, but what is 2+2?",
                expected_label="not_relevant",
                tags=["not_relevant", "irrelevant_memory_mention", "adversarial"],
                difficulty="hard",
            ),
        ]

    @classmethod
    def capability_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="cap-001",
                task=PredictionTask.CAPABILITY,
                input_text="Search for Python tutorials online.",
                expected_label="web_search",
                expected_value=["web_search"],
                tags=["web_search", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-002",
                task=PredictionTask.CAPABILITY,
                input_text="Run the unit tests for this module.",
                expected_label="code_execution",
                expected_value=["code_execution"],
                tags=["code_execution", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-003",
                task=PredictionTask.CAPABILITY,
                input_text="Show me the contents of config.yaml.",
                expected_label="filesystem_read",
                expected_value=["filesystem_read"],
                tags=["filesystem_read", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-004",
                task=PredictionTask.CAPABILITY,
                input_text="Create a new file called output.json with the results.",
                expected_label="filesystem_write",
                expected_value=["filesystem_write"],
                tags=["filesystem_write", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-005",
                task=PredictionTask.CAPABILITY,
                input_text="Schedule a meeting with the team for tomorrow at 2pm.",
                expected_label="calendar",
                expected_value=["calendar"],
                tags=["calendar", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-006",
                task=PredictionTask.CAPABILITY,
                input_text="Analyze the trade-offs between microservices and monoliths.",
                expected_label="deep_reasoning",
                expected_value=["deep_reasoning"],
                tags=["deep_reasoning", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-007",
                task=PredictionTask.CAPABILITY,
                input_text="Return the analysis as a JSON object with fields for each option.",
                expected_label="structured_output",
                expected_value=["structured_output"],
                tags=["structured_output", "direct", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-008",
                task=PredictionTask.CAPABILITY,
                input_text="Search for Python tutorials and run the code to verify it works.",
                expected_label="web_search,code_execution",
                expected_value=["web_search", "code_execution"],
                tags=["web_search", "code_execution", "multi_label", "normal"],
                difficulty="normal",
            ),
            EvaluationCase(
                case_id="cap-009",
                task=PredictionTask.CAPABILITY,
                input_text="Analyze the data, create a JSON report, and save it to the filesystem.",
                expected_label="deep_reasoning,structured_output,filesystem_write",
                expected_value=["deep_reasoning", "structured_output", "filesystem_write"],
                tags=["deep_reasoning", "structured_output", "filesystem_write", "multi_label", "normal"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="cap-010",
                task=PredictionTask.CAPABILITY,
                input_text="That's a run of the mill solution, just execute the plan as discussed.",
                expected_label="",
                expected_value=[],
                tags=["no_capability", "tool_like_words", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="cap-011",
                task=PredictionTask.CAPABILITY,
                input_text="Execute this.",
                expected_label="",
                expected_value=[],
                tags=["no_capability", "tool_like_words", "short", "adversarial"],
                difficulty="hard",
            ),
        ]

    @classmethod
    def adversarial_cases(cls) -> list[EvaluationCase]:
        return [
            EvaluationCase(
                case_id="adv-001",
                task=PredictionTask.INTENT,
                input_text="",
                expected_label="social_interaction",
                tags=["empty_input", "adversarial"],
                difficulty="easy",
            ),
            EvaluationCase(
                case_id="adv-002",
                task=PredictionTask.INTENT,
                input_text="a" * 2000,
                expected_label="social_interaction",
                tags=["very_long", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="adv-003",
                task=PredictionTask.DOMAIN,
                input_text="a" * 2000,
                expected_label="general",
                tags=["very_long", "adversarial"],
                difficulty="hard",
            ),
            EvaluationCase(
                case_id="adv-004",
                task=PredictionTask.CAPABILITY,
                input_text="a" * 2000,
                expected_label="",
                expected_value=[],
                tags=["very_long", "adversarial"],
                difficulty="hard",
            ),
        ]
