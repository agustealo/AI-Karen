import React from 'react';

export const EmptyState: React.FC<{ title: string; message: string }> = ({ title, message }) => (
  <div className="flex flex-col items-center justify-center p-8 text-center text-muted-foreground border border-border rounded-lg border-dashed">
    <h3 className="text-lg font-medium text-foreground mb-2">{title}</h3>
    <p>{message}</p>
  </div>
);
