import React, { useState } from 'react';
import { AlarmItem } from '../types';
import { AlarmList } from './AlarmList';
import { AlarmEditor } from './AlarmEditor';

interface AlarmPanelProps {
  alarms: AlarmItem[];
  onCreate: (data: any) => Promise<void>;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
}

export const AlarmPanel: React.FC<AlarmPanelProps> = ({ alarms, onCreate, onToggle, onDelete }) => {
  const [isEditing, setIsEditing] = useState(false);

  return (
    <div className="flex flex-col h-full bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-border bg-muted/10 flex items-center justify-between">
        <h2 className="text-lg font-medium text-foreground">Alarms</h2>
        {!isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="text-sm px-3 py-1 bg-primary/10 text-primary hover:bg-primary/20 rounded transition-colors"
          >
            + New
          </button>
        )}
      </div>

      <div className="p-5 flex-1 relative">
        {isEditing ? (
          <AlarmEditor
            onSave={async (d) => { await onCreate(d); setIsEditing(false); }}
            onCancel={() => setIsEditing(false)}
          />
        ) : (
          <AlarmList alarms={alarms} onToggle={onToggle} onDelete={onDelete} />
        )}
      </div>
    </div>
  );
};
