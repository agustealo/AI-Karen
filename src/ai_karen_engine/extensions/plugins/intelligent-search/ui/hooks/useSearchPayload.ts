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

    // The canonical backend validates limits against its authorized budget.
    // Do not send inactive or unsupported crawl features as accepted options.
    if (options.crawlEnabled === true) {
      const domains = (values: string[] | undefined) =>
        (values || []).map((value) => value.trim()).filter(Boolean);
      payload.crawl = {
        enabled: true,
        ...(options.crawlMaxPages !== undefined && { max_pages: options.crawlMaxPages }),
        ...(options.crawlMaxDepth !== undefined && { max_depth: options.crawlMaxDepth }),
        ...(options.crawlUseCache !== undefined && { use_cache: options.crawlUseCache }),
        ...(domains(options.crawlIncludeDomains).length > 0 && {
          include_domains: domains(options.crawlIncludeDomains),
        }),
        ...(domains(options.crawlExcludeDomains).length > 0 && {
          exclude_domains: domains(options.crawlExcludeDomains),
        }),
      };
    }

    return payload;
  };

  return { buildPayload };
}
