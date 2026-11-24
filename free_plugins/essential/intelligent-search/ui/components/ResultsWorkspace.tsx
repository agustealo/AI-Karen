import React, { useState } from 'react';
import { ArrowUpRight, Database, Radar, Sparkles } from 'lucide-react';
import { IntelligentSearchState } from '../types';
import { ModeConfigItem } from '../configs/modeConfig';
import { LoadingState, EmptyState, ErrorState } from './UIStates';
import { EvidenceGraphPanel } from './EvidenceGraphPanel';
import { ResultsPanel, SourcesPanel, ExtractedDataPanel, InsightsPanel, DiagnosticsPanel } from './Panels';

interface ResultsWorkspaceProps {
  state: IntelligentSearchState;
  modeConfig: ModeConfigItem;
}

export function ResultsWorkspace({ state, modeConfig }: ResultsWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<string>(modeConfig.resultTabs[0] || 'results');
  const [showResearchTools, setShowResearchTools] = useState(false);
  const [detailsWidth, setDetailsWidth] = useState(280);
  const [showDetails, setShowDetails] = useState(false);

  const response = state.response;
  const validTabs = React.useMemo(
    () => response?.evidenceGraph && !modeConfig.resultTabs.includes('graph')
      ? [modeConfig.resultTabs[0], 'graph', ...modeConfig.resultTabs.slice(1)]
      : modeConfig.resultTabs,
    [modeConfig.resultTabs, response?.evidenceGraph],
  );
  const currentTab = showResearchTools && validTabs.includes(activeTab) ? activeTab : 'results';
  const sources = response?.sources ?? [];
  const sourceCount = response?.sources?.length ?? 0;
  const resultCount = response?.results?.length ?? 0;
  const distinctHosts = new Set(sources.map((source) => {
    try { return new URL(source.url).hostname.replace(/^www\./, '').toLowerCase(); }
    catch { return ''; }
  }).filter(Boolean)).size;
  const actualMode = String(response?.mode || 'unknown');
  const searchProviders = Array.isArray(response?.metadata?.search_providers)
    ? response.metadata.search_providers.filter((value): value is string => typeof value === 'string')
    : [];
  const correlationId = typeof response?.metadata?.correlation_id === 'string'
    ? response.metadata.correlation_id : null;
  const providerLabel = String(
    response?.provider || response?.metadata?.provider || 'Unknown',
  );
  const elapsed = response?.execution_time_ms ? `${response.execution_time_ms}ms` : 'live';
  const featuredItem = response?.results?.[0] ?? response?.sources?.[0];
  const featuredPreview =
    featuredItem?.content ||
    featuredItem?.snippet ||
    'No retrieved preview available.';
  const featuredHref = featuredItem?.url || '';
  const hasEvidence = sourceCount > 0 || resultCount > 0;
  const weatherData = response?.mode === 'weather' && response.extractedData &&
    typeof response.extractedData === 'object' ? response.extractedData : null;
  const measuredTemperature = weatherData?.temperature_f;
  const hasWeatherObservation = typeof measuredTemperature === 'number' &&
    Number.isFinite(measuredTemperature) &&
    typeof weatherData?.observed_at === 'string' &&
    typeof weatherData?.location === 'string' &&
    (response?.sources?.length ?? 0) > 0;
  const failedExecution = response?.metadata?.degraded === true && response?.status === 'error';
  const searchFailure = response?.status === 'error' || response?.can_execute === false && response?.reason;
  const failureMessage = typeof response?.reason === 'string' ? response.reason : 'The requested live information is unavailable. Please retry or refine your search.';


  // Handle states where we don't show the tabs
  if (state.isLoading) return <LoadingState state={state} />;
  if (state.error) return <ErrorState error={state.error} />;
  if (!response) return <EmptyState />;
  if (response.status === 'needs_location') return (
    <section role="status" aria-label="Weather location required"
      className="rounded-2xl border border-border/60 bg-card p-8 space-y-3">
      <h2 className="text-lg font-semibold">Which location should I check?</h2>
      <p className="text-sm text-muted-foreground">
        Enter a city and state or country in the search field, such as
        {' "weather in Detroit, MI"'}, then search again.
        No weather observation has been retrieved yet.
      </p>
    </section>
  );
  if (searchFailure || failedExecution) return <div role="alert" className="rounded-2xl border border-border/60 bg-card p-8 space-y-3"><h2 className="text-lg font-semibold">Search could not be completed</h2><p className="text-muted-foreground">{failureMessage}</p></div>;
  if (!hasEvidence) return <div role="status" className="rounded-2xl border border-border/60 bg-card p-8 space-y-3"><h2 className="text-lg font-semibold">No sources found</h2><p className="text-muted-foreground">The search did not return usable evidence. No search evidence retrieved. No result or citation has been verified. Search failed: no evidence. Try a broader query or a different search mode.</p></div>;

  const renderTabContent = () => {
    switch (currentTab) {
      case 'results':
        return <ResultsPanel response={response} />;
      case 'sources':
        return <SourcesPanel response={response} />;
      case 'graph':
        return <EvidenceGraphPanel graph={response.evidenceGraph} />;
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
    <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-border/60 bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-base font-semibold">Search evidence</h2>
          <span className="text-xs text-muted-foreground">{sourceCount} sources · {distinctHosts} websites</span>
        </div>
        <button type="button"
          onClick={() => {
            setShowResearchTools(value => !value);
            setShowDetails(false);
          }}
          aria-expanded={showResearchTools}
          className="min-h-10 rounded-xl border border-border/60 px-3 py-2 text-sm font-medium hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {showResearchTools ? 'Hide research tools' : 'Research tools'}
        </button>
      </div>
      {showResearchTools && (
        <details className="mx-4 mt-3 rounded-xl border border-border/50 bg-background p-3">
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground">Technical search details</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SignalTile label="Query" value={response.query || 'live request'} icon={<Radar className="h-4 w-4" />} />
            <SignalTile label="Provider" value={providerLabel} icon={<Database className="h-4 w-4" />} />
            <SignalTile label="Actual mode" value={actualMode} icon={<Radar className="h-4 w-4" />} />
            <SignalTile label="Providers used" value={searchProviders.length ? searchProviders.join(', ') : 'Not reported'} icon={<Database className="h-4 w-4" />} />
            <SignalTile label="Correlation ID" value={correlationId || 'Not reported'} icon={<Radar className="h-4 w-4" />} />
            <SignalTile label="URLs" value={response.diagnostics?.urlsFound ?? sourceCount} icon={<ArrowUpRight className="h-4 w-4" />} />
            <SignalTile label="Retrieved chunks" value={response.diagnostics?.chunksProduced ?? resultCount} icon={<Sparkles className="h-4 w-4" />} />
          </div>
        </details>
      )}

      {response.runtimeAnswer && (
        <section aria-label="Grounded search answer" className="mx-4 mt-4 space-y-3 rounded-2xl border border-border/60 bg-card p-5 lg:mx-6">
          <h3 className="text-lg font-semibold">Answer</h3>
          <p className="whitespace-pre-wrap break-words text-sm leading-7">{response.runtimeAnswer.text}</p>
          <p className="break-words text-xs text-muted-foreground">
            Generated by {response.runtimeAnswer.provider} / {response.runtimeAnswer.model}
          </p>
          <p className="text-xs text-muted-foreground">Supporting sources appear below.</p>
          {Boolean(response.citations?.length) && (
            <nav aria-label="Supporting citations" className="space-y-2">
              <h4 className="text-sm font-medium">Supporting citations</h4>
              <p className="text-xs text-muted-foreground">Retrieved evidence references, not individually verified answer claims.</p>
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                {response.citations?.map(citation => (
                  <li key={citation.url} className="break-words">
                    <a href={citation.url} target="_blank" rel="noopener noreferrer" className="text-primary underline">{citation.title}</a>
                  </li>
                ))}
              </ol>
            </nav>
          )}
        </section>
      )}
      {hasWeatherObservation && weatherData && (
        <section aria-label="Weather observation" className="relative mx-4 mt-4 rounded-2xl border border-border/60 bg-card p-5 lg:mx-6">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Live provider observation</p>
          <h3 className="mt-2 text-lg font-semibold text-foreground">{String(weatherData.location)}</h3>
          <p className="mt-2 text-3xl font-semibold text-foreground">{String(measuredTemperature)} °F</p>
          <p className="mt-2 text-sm text-muted-foreground">Provider timestamp: {String(weatherData.observed_at)} {typeof weatherData.timezone === 'string' ? weatherData.timezone : ''}</p>
          <p className="mt-1 text-xs text-muted-foreground">Structured weather data, not an AI-generated forecast explanation.</p>
          {response.sources?.[0]?.url?.startsWith('https://') && (
            <a href={response.sources[0].url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-sm text-primary underline">
              View weather data provider
            </a>
          )}
        </section>
      )}

      <div className={`relative grid min-h-[65vh] flex-1 grid-cols-1 gap-4 px-4 py-4 lg:px-6 lg:py-6 ${showResearchTools && showDetails ? 'lg:grid-cols-[minmax(0,1fr)_var(--detail-width)]' : ''}`}
        style={{ '--detail-width': `${detailsWidth}px` } as React.CSSProperties}>
        <section className="flex min-h-[55vh] min-w-0 flex-col gap-4">
          {showResearchTools && <div className="rounded-xl border border-border/60 bg-background/70 p-2">
            <div className="flex items-center justify-between gap-2 px-2 pb-2"><span className="text-xs text-muted-foreground">Research workspace</span><button type="button" onClick={() => setShowDetails(value => !value)} className="min-h-10 rounded-lg border border-border/60 px-3 py-1 text-xs" aria-expanded={showDetails}>{showDetails ? 'Hide details' : 'Show details'}</button></div>
            <nav aria-label="Search result sections" className="flex flex-wrap gap-2">
              {validTabs.map((tabId) => {
                const label = tabId.replace(/([A-Z])/g, ' $1').replace(/^./, (str) => str.toUpperCase());
                const isActive = currentTab === tabId;

                return (
                  <button
                    key={tabId}
                    onClick={() => setActiveTab(tabId)}
                    type="button"
                    aria-current={isActive ? "page" : undefined}
                    aria-label={`Show ${label} search information`}
                    className={`min-h-11 rounded-2xl px-4 py-2.5 text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${
                      isActive
                        ? 'bg-primary text-primary-foreground shadow-[0_10px_24px_rgba(0,0,0,0.2)]'
                        : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </nav>
          </div>}

          <div className="min-h-[50vh] min-w-0 flex-1 overflow-y-auto rounded-3xl border border-border/60 bg-card/80 p-4 shadow-[0_24px_60px_rgba(0,0,0,0.18)] lg:p-6">
            {renderTabContent()}
          </div>
        </section>

        {showResearchTools && showDetails && <aside className="min-h-[50vh] min-w-0 overflow-y-auto rounded-3xl border border-border/60 bg-card/75 p-4 shadow-[0_24px_60px_rgba(0,0,0,0.18)] lg:p-5">
          <div className="space-y-4">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">Details width<input aria-label="Details width" type="range" min={240} max={600} step={20} value={detailsWidth} onChange={event => setDetailsWidth(Number(event.target.value))} className="min-w-0 flex-1" /></label>
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


          </div>
        </aside>}
      </div>
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
