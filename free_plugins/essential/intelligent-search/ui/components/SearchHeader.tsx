import React from 'react';
import { Sparkles, Shield, Radar, ArrowUpRight } from 'lucide-react';
import { ModeConfigItem } from '../configs/modeConfig';
import { IntelligentSearchState } from '../types';

interface SearchHeaderProps {
  modeConfig: ModeConfigItem;
  state: IntelligentSearchState;
}

export function SearchHeader({ modeConfig, state }: SearchHeaderProps) {
  const sourceCount = state.response?.sources?.length ?? 0;
  const resultCount = state.response?.results?.length ?? 0;
  const status = state.isLoading
    ? 'Executing live crawl'
    : state.error
      ? 'Search failed'
      : state.response
        ? 'Live response ready'
        : 'Awaiting query';

  return (
    <div className="relative overflow-hidden rounded-3xl border border-border/60 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.18),transparent_32%),radial-gradient(circle_at_top_right,rgba(16,185,129,0.12),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.05),transparent_14%),hsl(var(--card))] p-5 shadow-[0_24px_60px_rgba(0,0,0,0.18)]">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.05),transparent_24%,transparent_76%,rgba(255,255,255,0.03))]" />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5 text-[11px] uppercase tracking-[0.32em] text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            Intelligent search
          </div>
          <div className="space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
              Live web results
            </h1>
            <p className="max-w-4xl text-sm leading-6 text-muted-foreground">
              <span className="font-medium text-foreground">{modeConfig.label}</span> - {modeConfig.description}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Pill icon={<Radar className="h-3.5 w-3.5" />} label={status} />
            <Pill icon={<Shield className="h-3.5 w-3.5" />} label={`${sourceCount} sources`} />
            <Pill icon={<ArrowUpRight className="h-3.5 w-3.5" />} label={`${resultCount} cards`} />
          </div>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          <MetricBadge label="Mode" value={modeConfig.label} />
          <MetricBadge label="Sources" value={sourceCount} />
          <MetricBadge label="Cards" value={resultCount} />
        </div>
      </div>
    </div>
  );
}

function Pill({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5 text-xs text-muted-foreground">
      {icon}
      <span>{label}</span>
    </div>
  );
}

function MetricBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-background/70 px-4 py-3 text-sm shadow-sm">
      <div className="text-[11px] uppercase tracking-[0.24em] text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium text-foreground">{value}</div>
    </div>
  );
}
