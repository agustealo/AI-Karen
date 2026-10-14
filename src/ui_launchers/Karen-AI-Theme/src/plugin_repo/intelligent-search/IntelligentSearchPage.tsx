import React from 'react';
import { SlidersHorizontal, RotateCcw } from 'lucide-react';
import { useIntelligentSearch } from './hooks/useIntelligentSearch';
import { SearchHeader } from './components/SearchHeader';
import { SearchControlsPanel } from './components/SearchControlsPanel';
import { ResultsWorkspace } from './components/ResultsWorkspace';

/**
 * Search-first layout. The search controls remain accessible while evidence
 * and source context own the primary reading area.
 */
export default function IntelligentSearchPage() {
  const {
    state, modeConfig, setQuery, setMode, updateOptions, executeSearch, resetSearch,
  } = useIntelligentSearch();
  const [showControls, setShowControls] = React.useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-background">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-5 px-4 py-5 lg:px-8 lg:py-7">
        <SearchHeader modeConfig={modeConfig} state={state} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            Search the web, inspect evidence, then ask Karen to verify or explain a source.
          </p>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setShowControls(value => !value)}
              aria-expanded={showControls} aria-controls="search-advanced-controls"
              className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-border/70 px-4 py-2 text-sm font-medium text-foreground hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
              {showControls ? 'Hide search settings' : 'Search settings'}
            </button>
            {(state.response || state.isLoading) && <button type="button" onClick={resetSearch}
              className="inline-flex min-h-10 items-center gap-2 rounded-xl px-3 py-2 text-sm text-muted-foreground hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
              <RotateCcw className="h-4 w-4" aria-hidden="true" /> {state.isLoading ? 'Cancel search' : 'Clear'}
            </button>}
          </div>
        </div>
        <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
          <aside id="search-advanced-controls" className={showControls
            ? 'min-w-0 xl:sticky xl:top-4 xl:self-start'
            : 'min-w-0'}>
            <SearchControlsPanel state={state} modeConfig={modeConfig}
              onQueryChange={setQuery} onModeChange={setMode}
              onOptionsChange={updateOptions} onSubmit={executeSearch}
              showAdvanced={showControls} />
          </aside>
          <main className="min-w-0" aria-label="Search evidence and results">
            <ResultsWorkspace state={state} modeConfig={modeConfig} />
          </main>
        </div>
      </div>
    </div>
  );
}
