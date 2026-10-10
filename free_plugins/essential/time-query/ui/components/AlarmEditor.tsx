import React, { useState } from 'react';

interface AlarmEditorProps {
  onSave: (data: any) => Promise<void>;
  onCancel: () => void;
}

export const AlarmEditor: React.FC<AlarmEditorProps> = ({ onSave, onCancel }) => {
  const [title, setTitle] = useState('New Alarm');
  // Initialize to next hour
  const d = new Date();
  d.setHours(d.getHours() + 1);
  d.setMinutes(0);
  // Ensure we do local ISO formatting
  const isoLocal = new Date(d.getTime() - (d.getTimezoneOffset() * 60000)).toISOString().slice(0,16);
  
  const [datetime, setDatetime] = useState(isoLocal);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    
    // Convert local datetime-local back to proper ISO
    const properIso = new Date(datetime).toISOString();
    
    await onSave({
      title,
      alarm_datetime: properIso,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      enabled: true
    });
    setLoading(false);
  };

  return (
    <form onSubmit={handleSubmit} className="bg-card border border-border rounded-xl p-5 space-y-4">
      <h3 className="font-medium text-foreground mb-2">Create Alarm</h3>

      <div>
        <label className="block text-xs text-muted-foreground mb-1">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          className="w-full bg-background border border-border px-3 py-1.5 rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all disabled:opacity-50"
        />
      </div>

      <div>
        <label className="block text-xs text-muted-foreground mb-1">Time</label>
        <input
          type="datetime-local"
          value={datetime}
          onChange={(e) => setDatetime(e.target.value)}
          required
          className="w-full bg-background border border-border px-3 py-1.5 rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all disabled:opacity-50"
        />
      </div>

      <div className="flex space-x-3 pt-2">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 px-4 py-2 bg-secondary hover:bg-secondary/80 text-secondary-foreground rounded transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={loading}
          className="flex-1 px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground rounded transition-colors"
        >
          {loading ? 'Saving...' : 'Save'}
        </button>
      </div>
    </form>
  );
};
