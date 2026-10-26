import { beforeEach, describe, expect, it, vi } from 'vitest';

const post = vi.fn();

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
