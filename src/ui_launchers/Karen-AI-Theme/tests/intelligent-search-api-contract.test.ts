import { beforeEach, describe, expect, it, vi } from 'vitest';

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock('@/lib/api', () => ({
  apiClient: { post, get: vi.fn() },
}));

import { IntelligentSearchApi } from '../src/plugin_repo/intelligent-search/services/IntelligentSearchApi';

const clarification = {
  mode: 'weather',
  status: 'needs_location',
  success: false,
  can_execute: false,
  reason: 'Explicit location required for live weather',
  missing_requirements: ['location.current'],
  sources: [],
  results: [],
};

describe('Intelligent Search API execution truth', () => {
  beforeEach(() => post.mockReset());

  it.each(['result', 'data', 'payload', 'response'] as const)(
    'preserves a valid missing-location response wrapped in %s',
    async (key) => {
      post.mockResolvedValue({ success: false, [key]: clarification });
      const result = await IntelligentSearchApi.executeSearch({ query: 'Whats the weather' });
      expect(result.status).toBe('needs_location');
      expect(result.sources).toEqual([]);
    },
  );

  it('passes through a direct missing-location response', async () => {
    post.mockResolvedValue(clarification);
    expect((await IntelligentSearchApi.executeSearch({ query: 'weather' })).status)
      .toBe('needs_location');
  });

  it('rejects conflicting envelope results even when one requests location', async () => {
    post.mockResolvedValue({
      success: false,
      result: clarification,
      data: { status: 'error', reason: 'unauthorized', sources: [] },
    });
    await expect(IntelligentSearchApi.executeSearch({ query: 'weather' })).rejects.toThrow();
  });

  it('rejects an envelope that failed despite response-shaped evidence', async () => {
    post.mockResolvedValue({
      success: false,
      result: { status: 'error', summary: 'Everything worked', sources: [{ url: 'https://example.org' }] },
    });
    await expect(IntelligentSearchApi.executeSearch({ query: 'weather' })).rejects.toThrow();
  });

  it('rejects nested execution errors even when the HTTP envelope succeeded', async () => {
    post.mockResolvedValue({
      success: true,
      response: { status: 'error', reason: 'provider_unavailable', sources: [] },
    });
    await expect(IntelligentSearchApi.executeSearch({ query: 'weather' }))
      .rejects.toThrow('provider_unavailable');
  });
});


describe('Canonical general search adapter', () => {
  beforeEach(() => post.mockReset());

  const payload = { mode: 'general', query: 'release notes', context: { allowed_domains: ['example.org'], prefer_recent: false } };
  const response = {
    content: 'A grounded answer',
    metadata: { answer_composition_status: 'grounded_model', response_source: 'grounded_search_model', degraded_mode: false, actual_provider: 'local', actual_model: 'test-model' },
    sources: [
      { id: 's1', url: 'https://example.org/release', title: 'Release', snippet: 'Retrieved evidence' },
      { url: 'https://example.org/empty' },
      { url: 'javascript:alert(1)', snippet: 'Unsafe' },
    ],
    citations: [
      { url: 'https://example.org/release#section', title: 'Untrusted title' },
      { url: 'https://example.org/release' },
      { url: 'https://unknown.example/' },
      { url: 'https://example.org/empty' },
    ],
  };

  it('preserves restrictions and cancellation and matches citations to usable sources', async () => {
    post.mockResolvedValue(response);
    const signal = new AbortController().signal;
    const result = await IntelligentSearchApi.executeSearch(payload, signal);
    expect(post).toHaveBeenCalledWith('/api/chat', {
      messages: [{ content: payload.query, message_type: 'user' }],
      search_retrieval_options: payload.context,
    }, { signal });
    expect(result.runtimeAnswer).toEqual({ text: response.content, provider: 'local', model: 'test-model' });
    expect(result.sources).toHaveLength(1);
    expect(result.citations).toEqual([{ url: 'https://example.org/release', title: 'Release', sourceId: 's1' }]);
  });

  it('does not label degraded synthesis as grounded', async () => {
    post.mockResolvedValue({ ...response, metadata: { ...response.metadata, degraded_mode: true } });
    expect((await IntelligentSearchApi.executeSearch(payload)).runtimeAnswer).toBeUndefined();
  });

  it('does not retry through the plugin endpoint after runtime denial', async () => {
    const denial = new Error('denied');
    post.mockImplementationOnce(async () => { throw denial; });
    let rejected: unknown;
    try {
      await IntelligentSearchApi.executeSearch(payload);
    } catch (error) {
      rejected = error;
    }
    expect(rejected).toBe(denial);
    expect(post).toHaveBeenCalledTimes(1);
    expect(post.mock.calls[0]?.[0]).toBe('/api/chat');
  });

  it('preserves unsupported advanced options on the existing plugin path', async () => {
    const advanced = { ...payload, crawl: { enabled: true } };
    post.mockResolvedValue({ success: true, result: { summary: '', sources: [] } });
    await IntelligentSearchApi.executeSearch(advanced);
    expect(post).toHaveBeenCalledWith('/api/plugins/execute', { plugin_name: 'intelligent-search', parameters: advanced }, { signal: undefined });
  });
});
