import { SearchModeId, IntelligentSearchOptions } from '../types';

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
    const crawlOptions: Record<string, any> = {};
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
    const context: Record<string, any> = {};
    Object.entries(options).forEach(([key, value]) => {
      if (
        value !== undefined &&
        value !== '' &&
        !crawlKeys.includes(key as keyof IntelligentSearchOptions)
      ) {
        context[key] = value;
      }
    });

    const payload: Record<string, any> = {
      mode,
      query,
      context,
    };

    // Add crawl options if present
    if (hasCrawlOptions) {
      payload.crawl = {
        enabled: crawlOptions.enabled || false,
        ...crawlOptions,
      };
    }

    return payload;
  };

  return { buildPayload };
}
