import React from 'react';

export const ErrorState: React.FC<{ error: string; onRetry?: () => void }> = ({ error, onRetry }) => (
  <div className="bg-destructive/10 border border-destructive/50 rounded-lg p-4 text-destructive flex flex-col items-start bg-card border-border">
    <h3 className="font-medium mb-1 flex items-center">
      <span className="mr-2">⚠️</span> Error
    </h3>
    <p className="text-sm opacity-90 mb-3">{error}</p>
    {onRetry && (
      <button
        onClick={onRetry}
        className="px-3 py-1 bg-destructive/20 hover:bg-destructive/30 rounded text-sm transition-colors"
      >
        Retry
      </button>
    )}
  </div>
);
