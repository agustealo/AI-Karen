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


describe('Intelligent Search governed deep-crawl transport', () => {
  const { buildPayload } = useSearchPayload();

  it('sends only implemented crawl settings in canonical snake_case', () => {
    const payload = buildPayload('general', 'public sources', {
      crawlEnabled: true,
      crawlMaxPages: 4,
      crawlMaxDepth: 2,
      crawlUseCache: false,
      crawlIncludeDomains: [' docs.example '],
      crawlExcludeDomains: ['blocked.docs.example'],
      crawlCaptureScreenshot: true,
      crawlStructuredSchema: '{"type":"article"}',
      crawlRespectRobotsTxt: false,
    });
    expect(payload).toEqual({
      mode: 'general',
      query: 'public sources',
      context: {},
      crawl: {
        enabled: true,
        max_pages: 4,
        max_depth: 2,
        use_cache: false,
        include_domains: ['docs.example'],
        exclude_domains: ['blocked.docs.example'],
      },
    });
  });

  it('does not forward inactive deep-crawl controls or imply traversal', () => {
    const payload = buildPayload('general', 'public sources', {
      crawlEnabled: false,
      crawlMaxPages: 50,
      crawlMaxDepth: 5,
    });
    expect(payload).toEqual({mode: 'general', query: 'public sources', context: {}});
  });
});
