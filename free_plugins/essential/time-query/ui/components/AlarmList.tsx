import React from 'react';
import { AlarmItem } from '../types';
import { EmptyState } from './EmptyState';

interface AlarmListProps {
  alarms: AlarmItem[];
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

export const AlarmList: React.FC<AlarmListProps> = ({ alarms, onToggle, onDelete }) => {
  if (alarms.length === 0) {
    return <EmptyState title="No Alarms" message="Create an alarm using the panel to the right." />;
  }

  return (
    <div className="space-y-3 max-h-96 overflow-y-auto pr-2">
      {alarms.map((alarm) => (
        <div
          key={alarm.alarm_id}
          className={`flex items-center justify-between p-4 rounded-lg border transition-colors ${alarm.enabled ? 'bg-card border-border' : 'bg-card/50 border-border/50 opacity-60'}`}
        >
          <div>
            <div className={`text-xl font-medium ${alarm.enabled ? 'text-foreground' : 'text-muted-foreground'}`}>
              {new Date(alarm.alarm_datetime).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {alarm.title} • {new Date(alarm.alarm_datetime).toLocaleDateString()}
            </div>
            {alarm.recurrence && (
              <div className="text-xs text-primary mt-1">↻ {alarm.recurrence}</div>
            )}
          </div>

          <div className="flex items-center space-x-4">
            <button
              onClick={() => onToggle(alarm.alarm_id, !alarm.enabled)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${alarm.enabled ? 'bg-primary' : 'bg-secondary'}`}
            >
              <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${alarm.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
            <button
              onClick={() => onDelete(alarm.alarm_id)}
              className="text-muted-foreground hover:text-destructive p-1"
            >
              🗑️
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
