import React from 'react';

export const DiagnosticsPanel: React.FC<{ payload: unknown }> = ({ payload }) => {
  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden mt-6">
      <div className="px-5 py-3 border-b border-border bg-muted/10">
        <h2 className="text-sm font-medium text-muted-foreground">Plugin Diagnostics & Raw Payload</h2>
      </div>
      <div className="p-0 max-h-48 overflow-y-auto">
        <pre className="text-xs font-mono text-muted-foreground p-4">
          {JSON.stringify(payload, null, 2)}
        </pre>
      </div>
    </div>
  );
};
