import { describe, expect, it } from 'vitest';

import { normalizeRuntimeProviderCatalogResponse } from '@/lib/model-runtime-inventory';

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
