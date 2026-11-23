import { describe, expect, it } from 'vitest';

import { useSearchPayload } from '../src/plugin_repo/intelligent-search/hooks/useSearchPayload';

describe('Intelligent Search canonical search option payload', () => {
  const { buildPayload } = useSearchPayload();

  it('normalizes browser controls to backend strategy keys and arrays', () => {
    const payload = buildPayload('news', 'release updates', {
      maxUrls: 8,
      freshnessBias: '0.95',
      allowedDomains: [' allowed.example ', 'docs.example'],
      blockedDomains: ' blocked.example, ads.example ' as unknown as string[],
      preferRecent: true,
      timeRange: 'w',
    });

    expect(payload).toEqual({
      mode: 'news',
      query: 'release updates',
      context: {
        max_urls: 8,
        freshness_bias: '0.95',
        allowed_domains: ['allowed.example', 'docs.example'],
        blocked_domains: ['blocked.example', 'ads.example'],
        prefer_recent: true,
        time_range: 'w',
      },
    });
  });

  it('preserves automatic routing and unrelated mode options', () => {
    expect(buildPayload('auto', 'weather in Detroit', { location: 'Detroit' })).toEqual({
      query: 'weather in Detroit',
      context: { location: 'Detroit' },
    });
  });

  it('omits empty domain filters without inventing restrictions', () => {
    const payload = buildPayload('general', 'research', {
      allowedDomains: ' , ' as unknown as string[],
      blockedDomains: [],
    });
    expect(payload.context).toEqual({});
  });
});
