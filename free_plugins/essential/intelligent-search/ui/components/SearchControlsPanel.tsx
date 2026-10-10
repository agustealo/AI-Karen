import React from 'react';
import { PlayCircle, Sparkles } from 'lucide-react';
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
}

export function SearchControlsPanel({ 
  state, modeConfig, onQueryChange, onModeChange, onOptionsChange, onSubmit 
}: SearchControlsPanelProps) {
  const isDisabled = state.isLoading;
  const hasResponse = Boolean(state.response);

  return (
    <div className="flex flex-col gap-4 p-4 md:p-0">
      <div className="rounded-3xl border border-border/60 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.12),transparent_30%),linear-gradient(180deg,rgba(255,255,255,0.03),transparent_18%),hsl(var(--card))] p-4 shadow-[0_24px_60px_rgba(0,0,0,0.16)]">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          Command center
        </div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          Configure the crawl, switch modes, and execute a live internet intelligence run.
        </p>
      </div>

      <SearchQueryInput 
        query={state.query} 
        onQueryChange={onQueryChange} 
        onSubmit={onSubmit} 
        disabled={isDisabled} 
      />
      
      <ModeSelector 
        currentMode={state.mode} 
        onModeChange={onModeChange} 
        disabled={isDisabled} 
      />

      <ModeSpecificControls 
        modeConfig={modeConfig} 
        options={state.options} 
        onOptionsChange={onOptionsChange} 
        disabled={isDisabled} 
      />

      <div className="rounded-3xl border border-border/60 bg-card/80 p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between text-xs uppercase tracking-[0.24em] text-muted-foreground">
          <span>Run search</span>
          <span>{hasResponse ? 'Refresh live results' : 'Ready'}</span>
        </div>
        <button
          onClick={onSubmit}
          disabled={isDisabled || (!state.query.trim() && !['weather', 'stock_market'].includes(state.mode))}
          className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-primary px-4 py-3 font-semibold text-primary-foreground shadow-[0_16px_30px_rgba(0,0,0,0.18)] transition-colors hover:bg-primary/90 disabled:opacity-50"
        >
          <PlayCircle className="h-4 w-4" />
          {isDisabled ? 'Searching...' : 'Execute Search'}
        </button>
      </div>
    </div>
  );
}
