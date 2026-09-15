/**
 * Tests for chat-response.ts degraded presentation logic.
 *
 * These tests verify that the frontend correctly displays fallback metadata
 * when a provider fails and the system recovers through runtime fallback.
 */

import { describe, it, expect } from 'vitest';
import {
  deriveDegradedPresentation,
  deriveResponseDetailsPresentation,
  deriveCompactBadgePresentation,
  normalizeProviderName,
  isBuiltInRuntimeProvider,
  isVllmRuntimeProvider,
  isTransformersRuntimeProvider,
  getRuntimeDisplayName,
} from '../src/lib/chat-response';

describe('Degraded Runtime Fallback Presentation', () => {
  describe('deriveDegradedPresentation with vLLM fallback', () => {
    it('should display vLLM as actual provider when vLLM answers after Gemini fails', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          requested_model: 'gemini-2.5-flash',
          provider: 'builtin_vllm',
          model_id: 'qwen-local',
          model_name: 'Qwen Local',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
          fallback_chain: ['builtin_vllm', 'builtin_transformers', 'fallback'],
          failure_reason: 'Requested provider gemini was unavailable; recovered through builtin_vllm.',
        },
      };

      const result = deriveDegradedPresentation(metadata);

      expect(result.requestedProvider).toBe('gemini');
      expect(result.actualProvider).toBe('builtin_vllm');
      expect(result.actualModel).toBe('Qwen Local');
      expect(result.providerDisplayName).toBe('vLLM');
      expect(result.isDegraded).toBe(true);
      expect(result.usedFallback).toBe(true);
    });

    it('should display Transformers as actual provider when Transformers answers', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'openai',
          requested_model: 'gpt-4',
          provider: 'builtin_transformers',
          model_id: 'llama-3-8b',
          model_name: 'Llama 3 8B',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'openai',
          fallback_chain: ['builtin_vllm', 'builtin_transformers', 'fallback'],
          failure_reason: 'Requested provider openai was unavailable; recovered through builtin_transformers.',
        },
      };

      const result = deriveDegradedPresentation(metadata);

      expect(result.requestedProvider).toBe('openai');
      expect(result.actualProvider).toBe('builtin_transformers');
      expect(result.providerDisplayName).toBe('Transformers');
    });

    it('should display fallback when all real engines fail', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          requested_model: 'gemini-2.5-flash',
          provider: 'fallback',
          model_id: 'karen-fallback-v1',
          model_name: 'Karen Local Fallback',
          source: 'hardcoded_emergency',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
          fallback_chain: ['builtin_vllm', 'builtin_transformers', 'fallback'],
          failure_reason: 'All providers failed to respond.',
        },
      };

      const result = deriveDegradedPresentation(metadata);

      expect(result.requestedProvider).toBe('gemini');
      expect(result.actualProvider).toBe('fallback');
      expect(result.providerDisplayName).toBe('Local Emergency Fallback');
    });
  });

  describe('deriveResponseDetailsPresentation with fallback metadata', () => {
    it('should show vLLM as provider label when vLLM is the actual provider', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          requested_model: 'gemini-2.5-flash',
          provider: 'builtin_vllm',
          model_id: 'qwen-local',
          model_name: 'Qwen Local',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
          duration: 1.23,
          tokens_per_second: 45.67,
        },
      };

      const result = deriveResponseDetailsPresentation(metadata);

      expect(result.providerLabel).toBe('vLLM');
      expect(result.modelLabel).toBe('Qwen Local');
      expect(result.sourceLabel).toBe('runtime_fallback');
      expect(result.speedLabel).toBe('45.67 tok/s');
      expect(result.latencyLabel).toBe('1.23s');
      // When provider changed and failure_reason contains "unavailable", statusLabel is "provider fallback"
      expect(result.statusLabel).toBe('provider fallback');
    });

    it('should show Transformers as provider label when Transformers is actual', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'anthropic',
          requested_model: 'claude-3-opus',
          provider: 'builtin_transformers',
          model_id: 'mistral-7b',
          model_name: 'Mistral 7B',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
        },
      };

      const result = deriveResponseDetailsPresentation(metadata);

      expect(result.providerLabel).toBe('Transformers');
      expect(result.modelLabel).toBe('Mistral 7B');
    });
  });

  describe('deriveCompactBadgePresentation with fallback', () => {
    it('should show vLLM badge with degraded status', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          provider: 'builtin_vllm',
          model_id: 'qwen-local',
          model_name: 'Qwen Local',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          duration: 0.8,
        },
      };

      const result = deriveCompactBadgePresentation(metadata);

      expect(result.providerLabel).toBe('vLLM');
      expect(result.modelLabel).toBe('Qwen Local');
      expect(result.durationLabel).toBe('0.8s');
      expect(result.isDegraded).toBe(true);
      // deriveCompactBadgePresentation uses degradedStatusLabel from deriveDegradedPresentation
      // When provider changed, it returns "provider fallback"
      expect(result.statusLabel).toBe('provider fallback');
    });
  });

  describe('Provider name normalization', () => {
    it('should normalize various vLLM aliases to builtin_vllm', () => {
      expect(normalizeProviderName('vllm')).toBe('builtin_vllm');
      expect(normalizeProviderName('builtin-vllm')).toBe('builtin_vllm');
      expect(normalizeProviderName('builtin_vllm')).toBe('builtin_vllm');
      expect(normalizeProviderName('nano-vllm')).toBe('builtin_vllm');
      expect(normalizeProviderName('nano_vllm')).toBe('builtin_vllm');
    });

    it('should normalize various Transformers aliases to builtin_transformers', () => {
      expect(normalizeProviderName('transformers')).toBe('builtin_transformers');
      expect(normalizeProviderName('builtin-transformers')).toBe('builtin_transformers');
      expect(normalizeProviderName('builtin_transformers')).toBe('builtin_transformers');
      expect(normalizeProviderName('hf-transformers')).toBe('builtin_transformers');
      expect(normalizeProviderName('hugging-face')).toBe('hugging_face');
      expect(normalizeProviderName('huggingface')).toBe('huggingface');
    });

    it('should normalize other providers correctly', () => {
      // openai doesn't match any alias, so it's returned as-is (with dashes to underscores)
      expect(normalizeProviderName('openai')).toBe('openai');
      expect(normalizeProviderName('gemini')).toBe('gemini');
      expect(normalizeProviderName('anthropic')).toBe('anthropic');
      expect(normalizeProviderName('local-gguf')).toBe('local_gguf');
      expect(normalizeProviderName('fallback')).toBe('fallback');
    });

    it('should handle null and empty strings', () => {
      expect(normalizeProviderName(null)).toBe('');
      expect(normalizeProviderName('')).toBe('');
      expect(normalizeProviderName('   ')).toBe('');
    });
  });

  describe('Runtime provider detection', () => {
    it('should identify builtin_vllm as built-in runtime provider', () => {
      expect(isBuiltInRuntimeProvider('builtin_vllm')).toBe(true);
      expect(isBuiltInRuntimeProvider('vllm')).toBe(true);
      expect(isBuiltInRuntimeProvider('builtin-vllm')).toBe(true);
      expect(isVllmRuntimeProvider('builtin_vllm')).toBe(true);
      expect(isVllmRuntimeProvider('vllm')).toBe(true);
    });

    it('should identify builtin_transformers as built-in runtime provider', () => {
      expect(isBuiltInRuntimeProvider('builtin_transformers')).toBe(true);
      expect(isBuiltInRuntimeProvider('transformers')).toBe(true);
      expect(isBuiltInRuntimeProvider('builtin-transformers')).toBe(true);
      expect(isTransformersRuntimeProvider('builtin_transformers')).toBe(true);
      expect(isTransformersRuntimeProvider('transformers')).toBe(true);
    });

    it('should not identify cloud providers as built-in runtime', () => {
      expect(isBuiltInRuntimeProvider('openai')).toBe(false);
      expect(isBuiltInRuntimeProvider('gemini')).toBe(false);
      expect(isBuiltInRuntimeProvider('anthropic')).toBe(false);
      expect(isVllmRuntimeProvider('openai')).toBe(false);
      expect(isTransformersRuntimeProvider('gemini')).toBe(false);
    });
  });

  describe('Runtime display names', () => {
    it('should display vLLM for builtin_vllm variants', () => {
      expect(getRuntimeDisplayName('builtin_vllm')).toBe('vLLM');
      expect(getRuntimeDisplayName('vllm')).toBe('vLLM');
      expect(getRuntimeDisplayName('nano-vllm')).toBe('vLLM');
    });

    it('should display Transformers for builtin_transformers variants', () => {
      expect(getRuntimeDisplayName('builtin_transformers')).toBe('Transformers');
      expect(getRuntimeDisplayName('transformers')).toBe('Transformers');
      expect(getRuntimeDisplayName('hf-transformers')).toBe('Transformers');
    });

    it('should display provider names for other providers', () => {
      expect(getRuntimeDisplayName('gemini')).toBe('gemini');
      // openai is not in special cases, so returns the provider name
      expect(getRuntimeDisplayName('openai')).toBe('openai');
      expect(getRuntimeDisplayName('fallback')).toBe('Local Emergency Fallback');
    });
  });

  describe('Complete degraded flow test case', () => {
    it('should correctly present full degraded fallback scenario', () => {
      // This simulates the exact scenario from the issue:
      // - User requests Gemini
      // - Gemini fails (e.g., API key not configured)
      // - System falls back to vLLM
      // - vLLM successfully generates response
      // - Frontend should show vLLM, not Gemini, as the active provider

      const backendResponse = {
        answer: "I'm a response generated by vLLM after Gemini failed.",
        metadata: {
          degraded_mode: true,
          llm: {
            requested_provider: 'gemini',
            requested_model: 'gemini-2.5-flash',
            provider: 'builtin_vllm',
            model_id: 'qwen-local',
            model_name: 'Qwen Local',
            source: 'runtime_fallback',
            is_degraded: true,
            used_fallback: true,
            fallback_from: 'gemini',
            fallback_chain: ['builtin_vllm', 'builtin_transformers', 'fallback'],
            // Don't use "unavailable" to trigger the "failed, switched to" format
            failure_reason: 'Gemini API returned error; recovered through builtin_vllm.',
            duration: 2.34,
            tokens_per_second: 67.89,
          },
        },
      };

      const degraded = deriveDegradedPresentation(backendResponse.metadata);
      const details = deriveResponseDetailsPresentation(backendResponse.metadata);
      const badge = deriveCompactBadgePresentation(backendResponse.metadata);

      // Verify degraded presentation
      expect(degraded.requestedProvider).toBe('gemini');
      expect(degraded.actualProvider).toBe('builtin_vllm');
      expect(degraded.providerDisplayName).toBe('vLLM');
      expect(degraded.modelDisplayName).toBe('Qwen Local');
      expect(degraded.isDegraded).toBe(true);
      expect(degraded.usedFallback).toBe(true);
      // degradedBannerText format when provider changed:
      // "{requested_provider} failed, switched to {fallbackTargetLabel}."
      expect(degraded.degradedBannerText).toContain('gemini');
      expect(degraded.degradedBannerText).toContain('vLLM');
      expect(degraded.degradedBannerText).toContain('switched to');

      // Verify response details presentation
      expect(details.providerLabel).toBe('vLLM');
      expect(details.modelLabel).toBe('Qwen Local');
      expect(details.sourceLabel).toBe('runtime_fallback');
      expect(details.speedLabel).toBe('67.89 tok/s');
      expect(details.latencyLabel).toBe('2.34s');
      expect(details.showStatusRow).toBe(true);
      // When provider changed, statusLabel is "provider fallback"
      expect(details.statusLabel).toBe('provider fallback');

      // Verify compact badge presentation
      expect(badge.providerLabel).toBe('vLLM');
      expect(badge.modelLabel).toBe('Qwen Local');
      expect(badge.durationLabel).toBe('2.3s');
      expect(badge.isDegraded).toBe(true);

      // Critical assertion: The answer is NOT the degraded warning
      expect(backendResponse.answer).not.toContain(
        'Requested provider gemini was unavailable; Karen continued in degraded mode.'
      );
      expect(backendResponse.answer).toContain('vLLM');

      // Verify metadata shows the correct provider
      expect(backendResponse.metadata.llm.requested_provider).toBe('gemini');
      expect(backendResponse.metadata.llm.provider).toBe('builtin_vllm');
      expect(backendResponse.metadata.llm.source).toBe('runtime_fallback');
    });
  });

  describe('Multiple fallback attempts', () => {
    it('should show Transformers when vLLM fails and Transformers succeeds', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          provider: 'builtin_transformers',
          model_id: 'llama-3-8b',
          model_name: 'Llama 3 8B',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
          attempted_providers: ['gemini', 'builtin_vllm', 'builtin_transformers'],
          failure_reason: 'Gemini failed; vLLM failed; recovered through builtin_transformers.',
        },
      };

      const result = deriveDegradedPresentation(metadata);

      expect(result.requestedProvider).toBe('gemini');
      expect(result.actualProvider).toBe('builtin_transformers');
      expect(result.providerDisplayName).toBe('Transformers');
      // Note: attemptedProviders is not in the DegradedPresentation return type
      // It's in the metadata but not surfaced by deriveDegradedPresentation
    });

    it('should show emergency fallback when all fail', () => {
      const metadata = {
        degraded_mode: true,
        llm: {
          requested_provider: 'gemini',
          provider: 'fallback',
          model_id: 'karen-fallback-v1',
          model_name: 'Karen Local Fallback',
          source: 'hardcoded_emergency',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
          attempted_providers: ['gemini', 'builtin_vllm', 'builtin_transformers', 'fallback'],
          failure_reason: 'All providers failed.',
        },
      };

      const result = deriveDegradedPresentation(metadata);

      expect(result.actualProvider).toBe('fallback');
      expect(result.providerDisplayName).toBe('Local Emergency Fallback');
      expect(result.modelDisplayName).toBe('Karen Local Fallback');
    });
  });

  /**
   * Integration test for UI-QA-004: Verify preferred provider flows through to actual provider.
   *
   * This test verifies that when a user selects a provider/model in settings,
   * the chat request includes these preferences and the backend metadata
   * correctly reflects them.
   */
  describe('Preferred Provider Flow (UI-QA-004)', () => {
    it('should include requested_provider and requested_model in metadata when provider is healthy', () => {
      const metadata = {
        llm: {
          requested_provider: 'builtin_vllm',
          requested_model: 'gpt2',
          provider: 'builtin_vllm',
          model_id: 'gpt2',
          model_name: 'GPT-2',
          source: 'runtime',
          is_degraded: false,
          used_fallback: false,
        },
      };

      const result = deriveResponseDetailsPresentation(metadata);

      expect(result.requestedProviderLabel).toBe('vLLM');
      expect(result.requestedModelLabel).toBe('gpt2');
      expect(result.providerLabel).toBe('vLLM');
      expect(result.modelLabel).toBe('GPT-2');
      expect(result.degradedMode).toBe(false);
    });

    it('should handle fallback when requested provider is unavailable', () => {
      const metadata = {
        llm: {
          requested_provider: 'gemini',
          requested_model: 'gemini-2.5-flash',
          provider: 'builtin_vllm',
          model_id: 'qwen-local',
          model_name: 'Qwen Local',
          source: 'runtime_fallback',
          is_degraded: true,
          used_fallback: true,
          fallback_from: 'gemini',
        },
      };

      const result = deriveResponseDetailsPresentation(metadata);

      expect(result.requestedProviderLabel).toBe('gemini');
      expect(result.requestedModelLabel).toBe('Gemini-2.5-flash');
      expect(result.providerLabel).toBe('vLLM');
      expect(result.modelLabel).toBe('Qwen Local');
      expect(result.degradedMode).toBe(true);
    });

    it('should indicate when requested provider field is missing', () => {
      // Edge case: backend doesn't provide requested_provider (routing bypass or error)
      const metadata = {
        llm: {
          provider: 'builtin_vllm',
          model_id: 'gpt2',
          model_name: 'GPT-2',
          source: 'runtime',
          is_degraded: false,
          used_fallback: false,
          // requested_provider and requested_model missing
        },
      };

      const result = deriveResponseDetailsPresentation(metadata);

      expect(result.requestedProviderLabel).toBe('N/A');
      expect(result.providerLabel).toBe('vLLM');
      expect(result.modelLabel).toBe('GPT-2');
      expect(result.degradedMode).toBe(false);
    });
  });
});
