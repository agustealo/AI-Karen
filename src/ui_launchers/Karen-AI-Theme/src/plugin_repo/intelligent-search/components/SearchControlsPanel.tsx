import React from 'react';
import { PlayCircle } from 'lucide-react';
import { SearchQueryInput } from './SearchQueryInput';
import { ModeSelector } from './ModeSelector';
import { ModeSpecificControls } from './ModeSpecificControls';
import { IntelligentSearchState, IntelligentSearchOptions, SearchModeId } from '../types';
import { ModeConfigItem } from '../configs/modeConfig';

interface SearchControlsPanelProps {
  state: IntelligentSearchState;
  modeConfig: ModeConfigItem;
  onQueryChange: (q: string) => void;
  onModeChange: (m: SearchModeId) => void;
  onOptionsChange: (opts: Partial<IntelligentSearchOptions>) => void;
  onSubmit: () => void;
  showAdvanced?: boolean;
}

export function SearchControlsPanel({
  state, modeConfig, onQueryChange, onModeChange, onOptionsChange,
  onSubmit, showAdvanced = false,
}: SearchControlsPanelProps) {
  const disabled = state.isLoading;
  const canSearch = Boolean(state.query.trim()) || ['weather', 'stock_market'].includes(state.mode);
  return (
    <div className="space-y-4 rounded-2xl border border-border/60 bg-card/70 p-4 shadow-sm">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-foreground">Your search</h2>
        <p className="text-xs leading-5 text-muted-foreground">Choose what to look for. Refine settings only when needed.</p>
      </div>
      <SearchQueryInput query={state.query} onQueryChange={onQueryChange}
        onSubmit={onSubmit} disabled={disabled} allowEmptyQuery={['weather', 'stock_market'].includes(state.mode)} />
      {showAdvanced && (
        <div className="space-y-3 border-t border-border/60 pt-4" aria-label="Additional search settings">
          <h3 className="text-sm font-medium text-foreground">Advanced options</h3>
          <ModeSpecificControls modeConfig={modeConfig}
            options={state.options} onOptionsChange={onOptionsChange}
            disabled={disabled} />
        </div>
      )}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <ModeSelector currentMode={state.mode} onModeChange={onModeChange} disabled={disabled} />
        <div className="sm:pt-5">
      <button type="button" onClick={onSubmit} disabled={disabled || !canSearch}
        className="inline-flex min-h-11 w-full items-center justify-center gap-2 sm:w-auto rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50">
        <PlayCircle className="h-4 w-4" aria-hidden="true" />
        {disabled ? 'Searching…' : state.response ? 'Update results' : 'Search'}
      </button>
        </div>
      </div>
    </div>
  );
}
