import React from 'react';
import { Radar, Sparkles } from 'lucide-react';

interface SearchQueryInputProps {
  query: string;
  onQueryChange: (query: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

export function SearchQueryInput({ query, onQueryChange, onSubmit, disabled }: SearchQueryInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  };

  return (
    <div className="space-y-3 rounded-3xl border border-border/60 bg-card/80 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
        <Sparkles className="h-3.5 w-3.5 text-primary" />
        Live query
      </div>
      <label className="text-sm font-medium text-foreground">Query</label>
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Ask anything..."
          className="w-full rounded-2xl border border-border/60 bg-background/80 px-4 py-4 pr-24 text-sm text-foreground shadow-inner outline-none transition-all placeholder:text-muted-foreground/70 focus:border-primary focus:ring-2 focus:ring-primary/30 disabled:opacity-50"
        />
        <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center">
          <button
            type="button"
            onClick={onSubmit}
            disabled={disabled || !query.trim()}
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground shadow-[0_10px_24px_rgba(0,0,0,0.18)] transition-all hover:bg-primary/90 disabled:opacity-50"
          >
            <Radar className="h-3.5 w-3.5" />
            Search
          </button>
        </div>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">
        Press Enter to search. The response area will surface live crawl sources, ranked cards, and diagnostics.
      </p>
    </div>
  );
}
