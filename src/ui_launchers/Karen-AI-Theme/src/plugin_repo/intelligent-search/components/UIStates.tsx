import React from 'react';
import { Loader2, TriangleAlert, Inbox } from 'lucide-react';
import { IntelligentSearchState } from '../types';

export function LoadingState({ state }: { state: IntelligentSearchState }) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center p-8 text-muted-foreground">
      <div className="mb-6 rounded-full border border-border/60 bg-card/80 p-4 shadow-[0_20px_60px_rgba(0,0,0,0.2)]">
        <Loader2 className="h-10 w-10 animate-spin text-primary" />
      </div>
      <div className="max-w-xl text-center">
        <div className="mb-3 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
          Crawl4AI live search
        </div>
        <h3 className="text-2xl font-semibold tracking-tight text-foreground">
          Scanning live sources
        </h3>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          Running <span className="font-semibold text-primary">{state.mode}</span> mode for
          <span className="font-medium text-foreground"> "{state.query.slice(0, 48)}{state.query.length > 48 ? '...' : ''}"</span>
        </p>
      </div>
    </div>
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center p-8 text-red-500/80">
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full border border-red-500/20 bg-red-500/10">
        <TriangleAlert className="h-8 w-8 text-red-400" />
      </div>
      <h3 className="mb-2 text-xl font-semibold text-red-400">Search execution failed</h3>
      <p className="max-w-2xl break-words rounded-2xl border border-red-500/20 bg-red-950/20 p-4 font-mono text-sm leading-6 text-red-300">
        {error.message || "An unknown error occurred while communicating with the plugin host."}
      </p>
    </div>
  );
}

export function EmptyState() {
  return (
    <div className="flex min-h-[460px] flex-col items-center justify-center p-8 text-muted-foreground">
      <div className="mb-6 flex h-20 w-20 items-center justify-center rounded-3xl border border-border/60 bg-card/80 shadow-[0_18px_50px_rgba(0,0,0,0.16)]">
        <Inbox className="h-10 w-10 text-muted-foreground/50" />
      </div>
      <h3 className="mb-2 text-2xl font-semibold tracking-tight text-foreground">Workspace ready</h3>
      <p className="max-w-xl text-center text-sm leading-6">
        Enter a query, pick a mode, and the response area will render live crawl results, ranked source cards, and diagnostics.
      </p>
    </div>
  );
}
