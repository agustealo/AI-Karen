import React from 'react';
import { MultiClockGrid } from './MultiClockGrid';
import { ClockItem } from '../types';

interface SavedClocksPanelProps {
  clocksData: ClockItem[];
  onRemoveClock: (tz: string) => void;
  onRefresh: () => void;
}

export const SavedClocksPanel: React.FC<SavedClocksPanelProps> = ({ clocksData, onRemoveClock, onRefresh }) => {
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden flex flex-col h-full">
      <div className="px-5 py-4 border-b border-border bg-muted/10 flex items-center justify-between">
        <h2 className="text-lg font-medium text-foreground">Saved Clocks</h2>
        <button
          onClick={onRefresh}
          className="text-xs px-2 py-1 bg-secondary hover:bg-secondary/80 text-secondary-foreground rounded transition-colors"
        >
          Refresh All
        </button>
      </div>
      <div className="p-5 flex-1 overflow-y-auto">
        <MultiClockGrid clocks={clocksData} onRemove={onRemoveClock} />
      </div>
    </div>
  );
};
