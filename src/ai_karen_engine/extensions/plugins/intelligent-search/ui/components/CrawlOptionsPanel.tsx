import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Settings, Info } from 'lucide-react';
import { IntelligentSearchOptions } from '../types';

interface CrawlOptionsPanelProps {
  options: IntelligentSearchOptions;
  onChange: (updates: Partial<IntelligentSearchOptions>) => void;
}

export function CrawlOptionsPanel({ options, onChange }: CrawlOptionsPanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleChange = <K extends keyof IntelligentSearchOptions>(key: K, value: IntelligentSearchOptions[K]) => {
    onChange({ [key]: value } as Pick<IntelligentSearchOptions, K>);
  };

  const handleArrayChange = (key: keyof IntelligentSearchOptions, value: string, action: 'add' | 'remove') => {
    const current = (options[key] as string[]) || [];
    if (action === 'add') {
      onChange({ [key]: [...current, value] });
    } else {
      onChange({ [key]: current.filter(item => item !== value) });
    }
  };

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
              <span title="Use Crawl4AI to extract full content from web pages">
                <Info className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              </span>
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
                    {options.crawlMaxPages ?? 5}
                  </span>
                </div>
                <input
                  data-testid="intelligent-search-max-pages"
                  type="range"
                  min="1"
                  max="25"
                  value={options.crawlMaxPages ?? 5}
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
                    {options.crawlMaxDepth ?? 1}
                  </span>
                </div>
                <input
                  data-testid="intelligent-search-max-depth"
                  type="range"
                  min="1"
                  max="5"
                  value={options.crawlMaxDepth ?? 1}
                  onChange={(e) => handleChange('crawlMaxDepth', parseInt(e.target.value))}
                  className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>

              <p className="text-xs text-muted-foreground">
                Crawl depth and pages are bounded by your runtime budget.
                Robots policy and private-network protections remain server-controlled.
              </p>
              <div className="flex items-center gap-2">
                <input data-testid="intelligent-search-use-cache" type="checkbox"
                  id="crawlUseCache" checked={options.crawlUseCache !== false}
                  onChange={(e) => handleChange('crawlUseCache', e.target.checked)}
                  className="h-4 w-4 rounded border-input" />
                <label htmlFor="crawlUseCache" className="text-xs">Use Cache</label>
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

            </div>
          )}
        </div>
      )}
    </div>
  );
}
