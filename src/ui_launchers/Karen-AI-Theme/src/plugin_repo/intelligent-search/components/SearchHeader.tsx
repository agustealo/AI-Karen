import React from 'react';
import { Search } from 'lucide-react';
import { ModeConfigItem } from '../configs/modeConfig';
import { IntelligentSearchState } from '../types';

interface SearchHeaderProps {
  modeConfig: ModeConfigItem;
  state: IntelligentSearchState;
}

/** Human-first search status, without internal card and pipeline counts. */
export function SearchHeader({ modeConfig, state }: SearchHeaderProps) {
  const sources = state.response?.sources?.length ?? 0;
  const results = state.response?.results?.length ?? 0;
  const status = state.isLoading
    ? 'Finding sources…'
    : state.error || state.response?.status === 'error'
      ? 'Search could not finish'
      : state.isResultsStale && state.response
        ? 'Showing previous results'
        : sources > 0
          ? (sources === 1 ? '1 source retrieved' : sources + ' sources retrieved')
          : results > 0 ? 'Evidence retrieved' : state.response ? 'No sources found' : 'Ready to search';

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border/60 bg-card px-4 py-4 sm:px-5">
      <div className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Search className="h-5 w-5 text-primary" aria-hidden="true" />
          Karen Search
        </h1>
        <p className="text-sm text-muted-foreground">
          {modeConfig.label === 'Automatic'
            ? 'Ask a question. Karen finds and organizes the supporting sources.'
            : modeConfig.description}
        </p>
      </div>
      <span role="status" className="text-xs font-medium text-muted-foreground">{status}</span>
    </header>
  );
}
