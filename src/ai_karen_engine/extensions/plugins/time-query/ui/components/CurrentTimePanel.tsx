import React from 'react';
import { TimePayload } from '../types';

export const CurrentTimePanel: React.FC<{ payload: TimePayload | null }> = ({ payload }) => {
  // We do not want to tick the entire payload, but we can do a local tick on just the time display if needed.
  // In this implementation, the TimeHeader is handling the big display. This panel can handle details.
  
  if (!payload) return null;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="px-5 py-4 border-b border-border bg-muted/10 flex items-center justify-between">
        <h2 className="text-lg font-medium text-foreground">System Time Details</h2>
        <span className="text-xs px-2 py-1 bg-primary/10 text-primary rounded ring-1 ring-primary/20">
          {payload.source}
        </span>
      </div>
      <div className="p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
        <DetailRow label="Timezone" value={payload.timezone} />
        <DetailRow label="UTC Offset" value={payload.utc_offset} />
        <DetailRow label="ISO Format" value={payload.iso} isMono />
        <DetailRow label="Unix Timestamp" value={payload.timestamp_unix.toString()} isMono />
        <DetailRow label="UTC Datetime" value={payload.timestamp_utc} isMono />
      </div>
    </div>
  );
};

const DetailRow: React.FC<{ label: string; value: string; isMono?: boolean }> = ({ label, value, isMono }) => (
  <div className="flex flex-col">
    <span className="text-xs text-muted-foreground mb-1">{label}</span>
    <span className={`text-sm text-foreground ${isMono ? 'font-mono' : ''}`}>{value}</span>
  </div>
);
