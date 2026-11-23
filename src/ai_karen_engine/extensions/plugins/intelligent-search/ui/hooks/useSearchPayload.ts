import { SearchModeId, IntelligentSearchOptions } from '../types';

// Consumer field names are translated once at the API boundary. The backend
// handlers and runtime retain their existing snake_case strategy contract.
const SEARCH_OPTION_KEYS: Partial<Record<keyof IntelligentSearchOptions, string>> = {
  maxUrls: 'max_urls',
  freshnessBias: 'freshness_bias',
  allowedDomains: 'allowed_domains',
  blockedDomains: 'blocked_domains',
  timeRange: 'time_range',
  preferRecent: 'prefer_recent',
};

export function useSearchPayload() {
  const buildPayload = (mode: SearchModeId, query: string, options: IntelligentSearchOptions) => {
    // Separate crawl options from other options
    const crawlKeys: Array<keyof IntelligentSearchOptions> = [
      'crawlEnabled',
      'crawlMaxPages',
      'crawlMaxDepth',
      'crawlCaptureScreenshot',
      'crawlUseCache',
      'crawlRespectRobotsTxt',
      'crawlIncludeDomains',
      'crawlExcludeDomains',
      'crawlExtractLinks',
      'crawlExtractMedia',
      'crawlExtractCleanedHtml',
      'crawlStructuredSchema',
      'crawlWaitForSelector',
    ];

    // Build crawl object if any crawl options are present
    const crawlOptions: Record<string, unknown> = {};
    let hasCrawlOptions = false;

    crawlKeys.forEach(key => {
      if (options[key] !== undefined && options[key] !== '') {
        // Remove 'crawl' prefix for backend
        const backendKey = key.replace('crawl', '');
        const lowerCaseKey = backendKey.charAt(0).toLowerCase() + backendKey.slice(1);
        crawlOptions[lowerCaseKey] = options[key];
        hasCrawlOptions = true;
      }
    });

    // Build context with non-crawl options
    const context: Record<string, unknown> = {};
    Object.entries(options).forEach(([key, value]) => {
      if (
        value !== undefined &&
        value !== '' &&
        !crawlKeys.includes(key as keyof IntelligentSearchOptions)
      ) {
        const backendKey = SEARCH_OPTION_KEYS[key as keyof IntelligentSearchOptions] ?? key;
        if (key === 'allowedDomains' || key === 'blockedDomains') {
          // Existing text controls supply comma-separated strings even though
          // the public option type also accepts arrays.
          const domains = (Array.isArray(value) ? value : String(value).split(','))
            .map((domain) => domain.trim())
            .filter(Boolean);
          if (domains.length > 0) context[backendKey] = domains;
        } else {
          context[backendKey] = value;
        }
      }
    });

    const payload: Record<string, unknown> = {
      ...(mode === 'auto' ? {} : { mode }),
      query,
      context,
    };

    // Add crawl options if present
    if (hasCrawlOptions) {
      payload.crawl = {
        enabled: crawlOptions.enabled === true,
        ...crawlOptions,
      };
    }

    return payload;
  };

  return { buildPayload };
}
