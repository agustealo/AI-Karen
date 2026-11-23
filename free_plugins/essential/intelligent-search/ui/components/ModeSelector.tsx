import React from 'react';
import { MODE_CONFIG } from '../configs/modeConfig';
import { SearchModeId } from '../types';

interface ModeSelectorProps {
  currentMode: SearchModeId;
  onModeChange: (mode: SearchModeId) => void;
  disabled?: boolean;
}

export function ModeSelector({ currentMode, onModeChange, disabled }: ModeSelectorProps) {
  return (
    <div className="min-w-0 flex-1 space-y-1 sm:max-w-[320px]">
      <label htmlFor="intelligent-search-mode" className="block text-xs font-medium text-muted-foreground">
        Search mode
      </label>
      <select
        id="intelligent-search-mode"
        value={currentMode}
        onChange={event => onModeChange(event.target.value as SearchModeId)}
        disabled={disabled}
        aria-describedby="intelligent-search-mode-description"
        className="min-h-11 w-full rounded-xl border border-border/70 bg-background px-3 py-2 text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {(Object.entries(MODE_CONFIG) as [SearchModeId, typeof MODE_CONFIG[SearchModeId]][]).map(([mode, config]) => (
          <option key={mode} value={mode}>{config.label}</option>
        ))}
      </select>
      <p id="intelligent-search-mode-description" className="text-xs text-muted-foreground">
        {MODE_CONFIG[currentMode].description}
      </p>
    </div>
  );
}
