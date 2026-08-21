from ai_karen_engine.api_routes.chat.runtime import ChatMessage, ChatRequest
from ai_karen_engine.config.llm_provider_config import (
    AuthenticationType,
    LLMProviderConfigManager,
    ProviderAuthentication,
    ProviderConfig,
    ProviderEndpoint,
    ProviderLimits,
    ProviderModel,
    ProviderType,
)


def test_chat_request_accepts_large_requested_token_budget():
    request = ChatRequest(
        messages=[ChatMessage(content="Please write a detailed answer.")],
        max_tokens=128000,
    )

    assert request.max_tokens == 128000


def test_effective_max_tokens_comes_from_provider_model_config(tmp_path):
    manager = LLMProviderConfigManager(config_dir=tmp_path)
    manager._providers.clear()

    manager._providers["openai"] = ProviderConfig(
        name="openai",
        display_name="OpenAI",
        provider_type=ProviderType.REMOTE,
        endpoint=ProviderEndpoint(base_url="https://api.openai.com/v1"),
        authentication=ProviderAuthentication(
            type=AuthenticationType.API_KEY,
            api_key_env_var="OPENAI_API_KEY",
        ),
        models=[
            ProviderModel(
                id="gpt-4o",
                name="gpt-4o",
                context_length=128000,
                max_tokens=128000,
            )
        ],
        limits=ProviderLimits(
            max_context_length=128000,
            max_output_tokens=128000,
        ),
    )

    assert (
        manager.get_effective_max_tokens("openai", "gpt-4o", requested_max_tokens=64000)
        == 64000
    )
    assert (
        manager.get_effective_max_tokens("openai", "gpt-4o", requested_max_tokens=256000)
        == 128000
    )
    assert manager.get_effective_context_length("openai", "gpt-4o") == 128000
