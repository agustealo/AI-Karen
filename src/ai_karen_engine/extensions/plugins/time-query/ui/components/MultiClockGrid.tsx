import React from 'react';
import { ClockItem } from '../types';
import { EmptyState } from './EmptyState';

interface ClockItemWithError extends ClockItem {
  error?: string;
}

const isClockWithError = (clock: ClockItem): clock is ClockItemWithError => {
  return 'error' in clock && typeof clock.error === 'string';
};

export const MultiClockGrid: React.FC<{ clocks: ClockItem[]; onRemove: (tz: string) => void }> = ({ clocks, onRemove }) => {
  if (clocks.length === 0) {
    return <EmptyState title="No Clocks Saved" message="Search and add a world clock to keep track of it here." />;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {clocks.map((c, i) => {
        // if there's an error in the payload it might not have standard payload fields
        if (isClockWithError(c)) {
          return (
            <div key={i} className="bg-card/80 border border-destructive/50 rounded flex justify-between items-center p-4">
              <span className="text-destructive text-sm">{c.error}</span>
              <button className="text-muted-foreground hover:text-foreground" onClick={() => onRemove(c.timezone)}>×</button>
            </div>
          );
        }
        return (
          <div key={c.timezone} className="bg-card/80 border border-border rounded p-4 relative group">
            <button
              onClick={() => onRemove(c.timezone)}
              className="absolute top-2 right-2 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
              title="Remove"
            >
               ×
            </button>
            <div className="text-xs text-muted-foreground uppercase tracking-widest mb-1">{c.label}</div>
            <div className="text-2xl font-light text-foreground">{c.time}</div>
            <div className="text-xs text-muted-foreground mt-1">{c.weekday}, {c.date}</div>
            <div className="text-xs text-muted-foreground mt-2">{c.utc_offset}</div>
          </div>
        );
      })}
    </div>
  );
};
