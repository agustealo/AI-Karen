import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Settings, Info } from 'lucide-react';
import { IntelligentSearchOptions } from '../types';

interface CrawlOptionsPanelProps {
  options: IntelligentSearchOptions;
  onChange: (updates: Partial<IntelligentSearchOptions>) => void;
  capabilities?: {
    supports_screenshot: boolean;
    supports_structured_extraction: boolean;
  };
}

export function CrawlOptionsPanel({ options, onChange, capabilities }: CrawlOptionsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleChange = (key: keyof IntelligentSearchOptions, value: any) => {
    onChange({ [key]: value });
  };

  const handleArrayChange = (key: keyof IntelligentSearchOptions, value: string, action: 'add' | 'remove') => {
    const current = (options[key] as string[]) || [];
    if (action === 'add') {
      onChange({ [key]: [...current, value] });
    } else {
      onChange({ [key]: current.filter(item => item !== value) });
    }
  };

  const defaultCapabilities = {
    supports_screenshot: true,
    supports_structured_extraction: true,
  };

  const caps = capabilities || defaultCapabilities;

  return (
    <div className="rounded-lg border border-border/60 bg-card/40 backdrop-blur-sm overflow-hidden">
      <button
        data-testid="intelligent-search-crawl-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-accent/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Settings className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">Advanced Crawl Options</span>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {options.crawlEnabled && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                Enabled
              </span>
            )}
          </div>
        </div>
        {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>

      {isExpanded && (
        <div
          data-testid="intelligent-search-crawl-options"
          className="border-t border-border/60 px-4 py-4 space-y-4"
        >
          {/* Enable/Disable Crawl */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="crawlEnabled"
                checked={options.crawlEnabled || false}
                onChange={(e) => handleChange('crawlEnabled', e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              <label htmlFor="crawlEnabled" className="text-sm font-medium">
                Enable Deep Crawl
              </label>
              <Info className="h-3.5 w-3.5 text-muted-foreground" title="Use Crawl4AI to extract full content from web pages" />
            </div>
          </div>

          {options.crawlEnabled && (
            <div className="space-y-4 pl-6 border-l-2 border-primary/20">
              {/* Max Pages */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-muted-foreground">
                    Max Pages
                  </label>
                  <span className="text-xs text-muted-foreground">
                    {options.crawlMaxPages || 5}
                  </span>
                </div>
                <input
                  data-testid="intelligent-search-max-pages"
                  type="range"
                  min="1"
                  max="50"
                  value={options.crawlMaxPages || 5}
                  onChange={(e) => handleChange('crawlMaxPages', parseInt(e.target.value))}
                  className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>

              {/* Max Depth */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-medium text-muted-foreground">
                    Max Depth
                  </label>
                  <span className="text-xs text-muted-foreground">
                    {options.crawlMaxDepth || 1}
                  </span>
                </div>
                <input
                  data-testid="intelligent-search-max-depth"
                  type="range"
                  min="1"
                  max="5"
                  value={options.crawlMaxDepth || 1}
                  onChange={(e) => handleChange('crawlMaxDepth', parseInt(e.target.value))}
                  className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>

              {/* Cache & Robots */}
              <div className="grid grid-cols-2 gap-3">
                <div className="flex items-center gap-2">
                  <input
                    data-testid="intelligent-search-use-cache"
                    type="checkbox"
                    id="crawlUseCache"
                    checked={options.crawlUseCache !== false}
                    onChange={(e) => handleChange('crawlUseCache', e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <label htmlFor="crawlUseCache" className="text-xs">
                    Use Cache
                  </label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="crawlRespectRobotsTxt"
                    checked={options.crawlRespectRobotsTxt !== false}
                    onChange={(e) => handleChange('crawlRespectRobotsTxt', e.target.checked)}
                    className="h-4 w-4 rounded border-input"
                  />
                  <label htmlFor="crawlRespectRobotsTxt" className="text-xs">
                    Respect Robots.txt
                  </label>
                </div>
              </div>

              {/* Extraction Options */}
              <div className="space-y-2 pt-2 border-t border-border/40">
                <p className="text-xs font-medium text-muted-foreground">Extraction Options</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="crawlExtractLinks"
                      checked={options.crawlExtractLinks !== false}
                      onChange={(e) => handleChange('crawlExtractLinks', e.target.checked)}
                      className="h-4 w-4 rounded border-input"
                    />
                    <label htmlFor="crawlExtractLinks" className="text-xs">
                      Extract Links
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="crawlExtractMedia"
                      checked={options.crawlExtractMedia !== false}
                      onChange={(e) => handleChange('crawlExtractMedia', e.target.checked)}
                      className="h-4 w-4 rounded border-input"
                    />
                    <label htmlFor="crawlExtractMedia" className="text-xs">
                      Extract Media
                    </label>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="crawlExtractCleanedHtml"
                      checked={options.crawlExtractCleanedHtml !== false}
                      onChange={(e) => handleChange('crawlExtractCleanedHtml', e.target.checked)}
                      className="h-4 w-4 rounded border-input"
                    />
                    <label htmlFor="crawlExtractCleanedHtml" className="text-xs">
                      Cleaned HTML
                    </label>
                  </div>
                  {caps.supports_screenshot && (
                    <div className="flex items-center gap-2">
                      <input
                        data-testid="intelligent-search-capture-screenshot"
                        type="checkbox"
                        id="crawlCaptureScreenshot"
                        checked={options.crawlCaptureScreenshot || false}
                        onChange={(e) => handleChange('crawlCaptureScreenshot', e.target.checked)}
                        className="h-4 w-4 rounded border-input"
                      />
                      <label htmlFor="crawlCaptureScreenshot" className="text-xs">
                        Screenshot
                      </label>
                    </div>
                  )}
                </div>
              </div>

              {/* Wait for Selector */}
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Wait for Selector (CSS)
                </label>
                <input
                  data-testid="intelligent-search-wait-selector"
                  type="text"
                  value={options.crawlWaitForSelector || ''}
                  onChange={(e) => handleChange('crawlWaitForSelector', e.target.value)}
                  placeholder="e.g., .main-content, #article"
                  className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background"
                />
              </div>

              {/* Include/Exclude Domains */}
              <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/40">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">
                    Include Domains
                  </label>
                  <input
                    type="text"
                    placeholder="example.com"
                    className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background"
                    onKeyPress={(e) => {
                      if (e.key === 'Enter' && e.currentTarget.value) {
                        handleArrayChange('crawlIncludeDomains', e.currentTarget.value, 'add');
                        e.currentTarget.value = '';
                      }
                    }}
                  />
                  <div className="flex flex-wrap gap-1">
                    {(options.crawlIncludeDomains || []).map((domain) => (
                      <span
                        key={domain}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-primary/10 text-primary text-xs"
                      >
                        {domain}
                        <button
                          onClick={() => handleArrayChange('crawlIncludeDomains', domain, 'remove')}
                          className="hover:text-primary-foreground"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-muted-foreground">
                    Exclude Domains
                  </label>
                  <input
                    type="text"
                    placeholder="ads.example.com"
                    className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background"
                    onKeyPress={(e) => {
                      if (e.key === 'Enter' && e.currentTarget.value) {
                        handleArrayChange('crawlExcludeDomains', e.currentTarget.value, 'add');
                        e.currentTarget.value = '';
                      }
                    }}
                  />
                  <div className="flex flex-wrap gap-1">
                    {(options.crawlExcludeDomains || []).map((domain) => (
                      <span
                        key={domain}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-destructive/10 text-destructive text-xs"
                      >
                        {domain}
                        <button
                          onClick={() => handleArrayChange('crawlExcludeDomains', domain, 'remove')}
                          className="hover:text-destructive-foreground"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Structured Extraction Schema */}
              {caps.supports_structured_extraction && (
                <div className="space-y-1.5 pt-2 border-t border-border/40">
                  <label className="text-xs font-medium text-muted-foreground">
                    Structured Extraction Schema (JSON)
                  </label>
                  <textarea
                    data-testid="intelligent-search-structured-schema"
                    value={options.crawlStructuredSchema || ''}
                    onChange={(e) => handleChange('crawlStructuredSchema', e.target.value)}
                    placeholder='{"type": "article", "fields": [...]}'
                    rows={4}
                    className="w-full px-3 py-2 text-sm rounded-md border border-input bg-background font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    Define a JSON schema for structured data extraction from crawled pages.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
