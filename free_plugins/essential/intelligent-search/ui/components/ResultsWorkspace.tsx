import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Database, Radar, Sparkles } from 'lucide-react';
import { IntelligentSearchState } from '../types';
import { ModeConfigItem } from '../configs/modeConfig';
import { LoadingState, EmptyState, ErrorState } from './UIStates';
import { ResultsPanel, SourcesPanel, ExtractedDataPanel, InsightsPanel, DiagnosticsPanel } from './Panels';

interface ResultsWorkspaceProps {
  state: IntelligentSearchState;
  modeConfig: ModeConfigItem;
}

export function ResultsWorkspace({ state, modeConfig }: ResultsWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<string>(modeConfig.resultTabs[0] || 'results');
  const [activeSourceIndex, setActiveSourceIndex] = useState(0);

  const validTabs = modeConfig.resultTabs;
  const currentTab = validTabs.includes(activeTab) ? activeTab : validTabs[0];
  const response = state.response;
  const sources = response?.sources ?? [];
  const sourceCount = response?.sources?.length ?? 0;
  const resultCount = response?.results?.length ?? 0;
  const providerLabel = response?.provider || response?.metadata?.provider || 'crawl4ai';
  const elapsed = response?.execution_time_ms ? `${response.execution_time_ms}ms` : 'live';
  const featuredItem = response?.results?.[0] ?? response?.sources?.[0];
  const featuredPreview =
    featuredItem?.content ||
    featuredItem?.snippet ||
    response?.summary ||
    'No live preview is available yet.';
  const featuredHref = featuredItem?.url || '';
  const statusLabel = response?.diagnostics?.degraded ? 'Degraded live fallback' : 'Live crawl';
  const capabilityTags = [
    `Provider ${providerLabel}`,
    `${sourceCount} sources`,
    `${resultCount} cards`,
    statusLabel,
  ];

  useEffect(() => {
    if (activeSourceIndex > sources.length - 1) {
      setActiveSourceIndex(0);
    }

    if (
      response?.sources?.length &&
      !response?.results?.length &&
      validTabs.includes('sources') &&
      currentTab === 'results'
    ) {
      setActiveTab('sources');
    }
  }, [activeSourceIndex, currentTab, response?.results?.length, response?.sources?.length, sources.length, validTabs]);

  // Handle states where we don't show the tabs
  if (state.isLoading) return <LoadingState state={state} />;
  if (state.error) return <ErrorState error={state.error} />;
  if (!response) return <EmptyState />;

  const renderTabContent = () => {
    switch (currentTab) {
      case 'results':
        return <ResultsPanel response={response} />;
      case 'sources':
        return <SourcesPanel response={response} />;
      case 'extractedData':
        return <ExtractedDataPanel response={response} />;
      case 'insights':
        return <InsightsPanel response={response} />;
      case 'diagnostics':
        return <DiagnosticsPanel response={response} />;
      default:
        return <div className="text-muted-foreground p-8">Unknown tab: {currentTab}</div>;
    }
  };

  return (
    <div className="relative flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-tl-3xl border-l border-t border-border/60 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.12),transparent_30%),radial-gradient(circle_at_top_right,rgba(16,185,129,0.10),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent_18%),hsl(var(--background))] shadow-[0_-1px_0_rgba(255,255,255,0.03),0_24px_70px_rgba(0,0,0,0.35)]">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.04),transparent_22%,transparent_78%,rgba(255,255,255,0.03))]" />

      <div className="relative border-b border-border/60 bg-background/70 px-5 py-5 backdrop-blur-xl lg:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/80 px-3 py-1.5 text-[11px] uppercase tracking-[0.32em] text-muted-foreground shadow-sm">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              Live crawl workspace
            </div>
            <div className="space-y-2">
              <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
                {modeConfig.label}
              </h2>
              <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
                {response.summary || modeConfig.description}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <StatBadge label="Sources" value={sourceCount} />
            <StatBadge label="Cards" value={resultCount} />
            <StatBadge label="Latency" value={elapsed} />
            <StatBadge label="Mode" value={state.mode.replace(/_/g, ' ')} />
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <SignalTile label="Query" value={response.query || 'live request'} icon={<Radar className="h-4 w-4" />} />
          <SignalTile label="Provider" value={providerLabel} icon={<Database className="h-4 w-4" />} />
          <SignalTile label="URLs" value={response.diagnostics?.urlsFound ?? sourceCount} icon={<ArrowUpRight className="h-4 w-4" />} />
          <SignalTile label="Chunks" value={response.diagnostics?.chunksProduced ?? resultCount} icon={<Sparkles className="h-4 w-4" />} />
        </div>
      </div>

      <div className="relative grid min-h-0 flex-1 gap-6 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:px-6 lg:py-6">
        <section className="flex min-h-0 flex-col gap-4">
          <div className="rounded-3xl border border-border/60 bg-card/70 p-2 shadow-sm backdrop-blur">
            <div className="flex flex-wrap gap-2">
              {validTabs.map((tabId) => {
                const label = tabId.replace(/([A-Z])/g, ' $1').replace(/^./, (str) => str.toUpperCase());
                const isActive = currentTab === tabId;

                return (
                  <button
                    key={tabId}
                    onClick={() => setActiveTab(tabId)}
                    className={`rounded-2xl px-4 py-2.5 text-sm font-medium transition-all ${
                      isActive
                        ? 'bg-primary text-primary-foreground shadow-[0_10px_24px_rgba(0,0,0,0.2)]'
                        : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto rounded-3xl border border-border/60 bg-card/80 p-4 shadow-[0_24px_60px_rgba(0,0,0,0.18)] lg:p-6">
            {renderTabContent()}
          </div>
        </section>

        <aside className="min-h-0 overflow-y-auto rounded-3xl border border-border/60 bg-card/75 p-4 shadow-[0_24px_60px_rgba(0,0,0,0.18)] lg:p-5">
          <div className="space-y-4">

            <div className="rounded-3xl border border-border/60 bg-background/70 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-muted-foreground">
                Featured preview
              </p>
              <div className="mt-3 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="space-y-1">
                    <p className="text-[11px] uppercase tracking-[0.24em] text-muted-foreground">
                      {featuredItem?.domain || featuredItem?.url ? 'Live source' : 'Summary'}
                    </p>
                    <h3 className="text-base font-semibold leading-6 text-foreground">
                      {featuredItem?.title || 'Latest crawl excerpt'}
                    </h3>
                  </div>
                  {featuredHref && (
                    <a
                      href={featuredHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-border/60 bg-card/80 text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
                      aria-label="Open featured source"
                    >
                      <ArrowUpRight className="h-4 w-4" />
                    </a>
                  )}
                </div>

                <div className="max-h-56 overflow-auto rounded-2xl border border-border/60 bg-card/80 px-4 py-3">
                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">
                    {featuredPreview}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-border/60 bg-background/70 p-4">
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-muted-foreground">
                Capability strip
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {capabilityTags.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/80 px-3 py-1.5 text-xs text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function StatBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/80 px-3 py-1.5 text-xs text-muted-foreground shadow-sm">
      <span className="uppercase tracking-[0.24em]">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  );
}

function SignalTile({
  label,
  value,
  icon,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-border/60 bg-card/80 px-4 py-3 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.24em] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-2 text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}
