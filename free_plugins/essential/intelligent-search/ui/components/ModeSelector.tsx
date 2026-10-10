import React from 'react';
import { BadgeCheck } from 'lucide-react';
import { MODE_CONFIG } from '../configs/modeConfig';
import { SearchModeId } from '../types';

interface ModeSelectorProps {
  currentMode: SearchModeId;
  onModeChange: (mode: SearchModeId) => void;
  disabled?: boolean;
}

export function ModeSelector({ currentMode, onModeChange, disabled }: ModeSelectorProps) {
  return (
    <div className="space-y-3 rounded-3xl border border-border/60 bg-card/80 p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.28em] text-muted-foreground">
        <BadgeCheck className="h-3.5 w-3.5 text-primary" />
        Search mode
      </div>
      <label className="text-sm font-medium text-foreground">Search mode</label>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(Object.entries(MODE_CONFIG) as [SearchModeId, typeof MODE_CONFIG[SearchModeId]][]).map(([mode, config]) => (
          <button
            key={mode}
            type="button"
            disabled={disabled}
            onClick={() => onModeChange(mode)}
            className={`
              group text-left rounded-2xl border px-3 py-3 text-sm transition-all
              ${currentMode === mode 
                ? 'border-primary bg-primary/10 text-primary shadow-[0_10px_24px_rgba(0,0,0,0.14)]' 
                : 'border-border/60 bg-background/80 text-muted-foreground hover:border-primary/40 hover:bg-muted/50 hover:text-foreground'
              }
              ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
            `}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{config.label}</span>
              {currentMode === mode && <span className="h-2 w-2 rounded-full bg-primary" />}
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground/80">
              {config.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
