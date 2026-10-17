import { describe, expect, it } from 'vitest';

import { normalizeRuntimeProviderCatalogResponse, resolveChatProviderModelSelection } from '@/lib/model-runtime-inventory';

describe('runtime provider catalog normalization', () => {
  it('keeps one canonical catalog and preserves provider configuration gaps', () => {
    const normalized = normalizeRuntimeProviderCatalogResponse({
      default_provider: 'gemini',
      default_model: 'gemini-2.5-flash',
      fallback_order: ['builtin_transformers', 'builtin_vllm', 'ollama', 'gemini'],
      providers: [
        {
          id: 'gemini',
          label: 'Google Gemini',
          category: 'external',
          enabled: true,
          configured: true,
          healthy: true,
          runtime_engine: 'gemini',
          transport: 'http',
          compatibility_profile: 'google_ai',
          selected_model: 'gemini-2.5-flash',
          default_model: 'gemini-2.5-flash',
          api_key_env_var: 'GEMINI_API_KEY',
          api_key_header: 'Authorization',
          api_key_prefix: 'Bearer',
          models: [
            {
              id: 'gemini-2.5-flash',
              label: 'Gemini 2.5 Flash',
              available: true,
              default: true,
              capabilities: ['chat', 'streaming'],
            },
          ],
          degradation_reason: null,
          allowed_for_current_user: true,
          requires_api_key: true,
          requires_base_url: false,
        },
        {
          id: 'ollama',
          label: 'Ollama',
          category: 'local',
          enabled: true,
          configured: true,
          healthy: true,
          runtime_engine: 'ollama',
          transport: 'http',
          selected_model: 'qwen3:4b',
          default_model: 'qwen3:4b',
          models: [],
          degradation_reason: null,
          allowed_for_current_user: true,
          requires_api_key: false,
          requires_base_url: true,
        },
      ],
    });

    const gemini = normalized.providers.find((provider) => provider.id === 'gemini');
    const ollama = normalized.providers.find((provider) => provider.id === 'ollama');

    expect(normalized.selected_provider).toBe('gemini');
    expect(normalized.selected_model).toBe('gemini-2.5-flash');
    expect(gemini?.provider_type).toBe('external');
    expect(gemini?.requires_api_key).toBe(true);
    expect(gemini?.api_key_env_var).toBe('GEMINI_API_KEY');
    expect(ollama?.provider_type).toBe('local');
    expect(ollama?.requires_api_key).toBe(false);
    // A configured selection is not evidence that Ollama has the model installed.
    expect(ollama?.selected_model).toBe('qwen3:4b');
    expect(ollama?.models).toEqual([]);
  });
});


describe('chat provider/model selector reflects Application Settings discovery', () => {
  const selectedModel = 'goekdenizguelmez/JOSIEFIED-Qwen3:8b';
  const secondModel = 'qwen2.5:7b';
  const inventory = normalizeRuntimeProviderCatalogResponse({
    default_provider: 'ollama',
    default_model: selectedModel,
    providers: [{
      id: 'ollama',
      label: 'Ollama',
      category: 'local',
      enabled: true,
      configured: true,
      healthy: true,
      selected_model: selectedModel,
      models: [
        { id: secondModel, label: secondModel, available: true },
        { id: selectedModel, label: selectedModel, available: true },
      ],
    }],
  });

  it('shows installed Ollama models in chat and selects the saved model by default', () => {
    const provider = inventory.selectableProviders.find((item) => item.id === 'ollama');
    expect(provider?.models.map((model) => model.id)).toEqual([selectedModel, secondModel]);
    expect(inventory.selected_provider).toBe('ollama');
    expect(inventory.selected_model).toBe(selectedModel);
    expect(resolveChatProviderModelSelection(inventory, '', '')).toEqual({
      provider: 'ollama', model: selectedModel, preferenceUnavailable: false,
    });
  });

  it('allows a user to select another installed model from chat', () => {
    expect(resolveChatProviderModelSelection(inventory, 'ollama-local', secondModel)).toEqual({
      provider: 'ollama', model: secondModel, preferenceUnavailable: false,
    });
  });

  it('does not select a removed model from an outdated user preference', () => {
    expect(resolveChatProviderModelSelection(inventory, 'ollama', 'removed:latest')).toEqual({
      provider: 'ollama', model: selectedModel, preferenceUnavailable: false,
    });
  });

  it('does not manufacture an installed model from a saved default after discovery fails', () => {
    const empty = normalizeRuntimeProviderCatalogResponse({
      default_provider: 'ollama',
      default_model: selectedModel,
      providers: [{
        id: 'ollama',
        label: 'Ollama',
        category: 'local',
        enabled: true,
        configured: true,
        healthy: false,
        selected_model: selectedModel,
        models: [],
      }],
    });
    expect(empty.providers[0].models).toEqual([]);
    expect(resolveChatProviderModelSelection(empty, 'ollama', selectedModel).model).toBe('');
  });
});


describe('empty runtime inventory is not a selectable Chat provider', () => {
  it('keeps degraded Ollama diagnostics but prevents selection of empty models', () => {
    const inventory = normalizeRuntimeProviderCatalogResponse({
      default_provider: 'ollama',
      default_model: 'auto',
      providers: [{
        id: 'ollama', label: 'Ollama', category: 'local', enabled: true,
        configured: true, healthy: false,
        degradation_reason: 'Ollama installed-model inventory unavailable',
        selected_model: null, models: [],
      }],
    });
    expect(inventory.providers).toHaveLength(1);
    expect(inventory.providers[0].degradation_reason).toContain('unavailable');
    expect(inventory.selectableProviders).toEqual([]);
    expect(resolveChatProviderModelSelection(inventory, 'ollama', 'auto')).toEqual({
      provider: '', model: '', preferenceUnavailable: true,
    });
  });

  it('excludes the unverified bootstrap provider without losing its health state', () => {
    const inventory = normalizeRuntimeProviderCatalogResponse({
      catalog_version: 'bootstrap', default_provider: 'builtin_transformers',
      default_model: 'auto',
      providers: [{
        id: 'builtin_transformers', label: 'Transformers', category: 'builtin',
        enabled: true, configured: false, healthy: false,
        selected_model: null, models: [],
      }],
    });
    expect(inventory.systemFallbackProvider?.healthy).toBe(false);
    expect(inventory.selectableProviders).toHaveLength(0);
    expect(inventory.selected_provider).toBe('');
    expect(inventory.selected_model).toBe('');
  });
});
