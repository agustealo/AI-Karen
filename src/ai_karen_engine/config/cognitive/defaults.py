from ai_karen_engine.config.cognitive.models import (
    BehaviorPolicyConfig,
    BeliefPolicyConfig,
    CognitivePolicyConfig,
    ContextPolicyConfig,
    LearningPolicyConfig,
    MemoryPolicyConfig,
    MetaCognitionPolicyConfig,
    SaliencePolicyConfig,
)


def cognitive_policy_defaults() -> CognitivePolicyConfig:
    return CognitivePolicyConfig(
        meta=MetaCognitionPolicyConfig(),
        belief=BeliefPolicyConfig(),
        salience=SaliencePolicyConfig(),
        context=ContextPolicyConfig(),
        behavior=BehaviorPolicyConfig(),
        learning=LearningPolicyConfig(),
        memory=MemoryPolicyConfig(),
    )


def meta_cognition_defaults() -> MetaCognitionPolicyConfig:
    return MetaCognitionPolicyConfig()


def belief_defaults() -> BeliefPolicyConfig:
    return BeliefPolicyConfig()


def salience_defaults() -> SaliencePolicyConfig:
    return SaliencePolicyConfig()


def context_defaults() -> ContextPolicyConfig:
    return ContextPolicyConfig()


def behavior_defaults() -> BehaviorPolicyConfig:
    return BehaviorPolicyConfig()


def learning_defaults() -> LearningPolicyConfig:
    return LearningPolicyConfig()


def memory_defaults() -> MemoryPolicyConfig:
    return MemoryPolicyConfig()


DEFAULT_COGNITIVE_POLICY = cognitive_policy_defaults()
