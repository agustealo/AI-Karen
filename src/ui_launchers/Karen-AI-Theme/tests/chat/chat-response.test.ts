import { describe, expect, it } from 'vitest';

import { deriveDegradedPresentation, deriveResponseDetailsPresentation } from '@/lib/chat-response';

describe('chat response fallback presentation', () => {
  it('renders a human-readable fallback switch banner', () => {
    const degraded = deriveDegradedPresentation({
      degraded_mode: true,
      llm: {
        requested_provider: 'zai',
        requested_model: 'glm-4.5',
        provider: 'fallback',
        model_id: 'fallback:kari-fallback-v1',
        model_name: 'kari-fallback-v1',
        is_degraded: true,
        failure_reason: 'upstream 401',
      },
    });

    expect(degraded.providerDisplayName).toBe('Local Emergency Fallback');
    expect(degraded.modelDisplayName).toBe('kari-fallback-v1');
    expect(degraded.degradedBannerText).toContain('zai failed, switched to Local Emergency Fallback (kari-fallback-v1).');
  });

  it('does not claim failover when local runtime naming variants are equivalent', () => {
    const degraded = deriveDegradedPresentation({
      degraded_mode: false,
      llm: {
        requested_provider: 'local_gguf',
        requested_model: 'phi-3-mini-4k-instruct-q4',
        provider: 'local_gguf',
        model_id: 'local_gguf:phi-3-mini-4k-instruct-q4',
        model_name: 'phi-3-mini-4k-instruct-q4',
      },
    });

    expect(degraded.degradedBannerText).toBe('');
    expect(degraded.visibleDegradedNotice).toBe('');
  });

  it('renders emergency static without a fake provider or model', () => {
    const details = deriveResponseDetailsPresentation({
      response_source: 'emergency_static',
      fallback_level: 99,
      degraded_mode: true,
      llm: {
        requested_provider: 'gemini',
        requested_model: 'gemini-2.5-flash',
        actual_provider: null,
        actual_model: null,
        provider_attempts: [
          {
            provider: 'gemini',
            model: 'gemini-2.5-flash',
            status: 'failed',
            error_type: 'missing_api_key',
          },
        ],
      },
    });

    expect(details.statusLabel).toBe('degraded mode');
    expect(details.providerLabel).toBe('none');
    expect(details.modelLabel).toBe('none');
    expect(details.providerAttempts).toHaveLength(1);
  });
});
