import React, { useState } from 'react';
import { TimePayload } from '../types';

interface WorldClockSearchProps {
  onSearch: (query: string) => Promise<TimePayload | null>;
  onAddClock: (tz: string) => void;
}

export const WorldClockSearch: React.FC<WorldClockSearchProps> = ({ onSearch, onAddClock }) => {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<TimePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    
    setLoading(true);
    setError(null);
    try {
      const res = await onSearch(query);
      if (res) {
        setResult(res);
      } else {
        setError('Could not resolve timezone for that location.');
      }
    } catch {
      setError('An error occurred during search.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <h2 className="text-lg font-medium text-foreground mb-4">World Time Lookup</h2>

      <form onSubmit={handleSearch} className="flex gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. Tokyo, Lusaka, America/New_York"
          className="bg-background border border-border px-3 py-1.5 rounded-md text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !query}
          className="bg-primary text-primary-foreground px-4 py-2 rounded font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Searching...' : 'Lookup'}
        </button>
      </form>

      {error && <div className="text-destructive text-sm mb-4">{error}</div>}

      {result && (
        <div className="bg-background/50 border border-border rounded p-4 flex flex-col sm:flex-row justify-between items-center">
          <div>
            <div className="text-2xl font-light text-foreground">{result.time}</div>
            <div className="text-muted-foreground text-sm text-center sm:text-left">{result.weekday}, {result.date}</div>
            <div className="text-xs text-muted-foreground mt-1">{result.timezone}</div>
          </div>
          <button
            onClick={() => onAddClock(result.timezone)}
            className="mt-3 sm:mt-0 text-sm bg-secondary hover:bg-secondary/80 text-secondary-foreground px-3 py-1.5 rounded transition-colors"
          >
            Add to Clocks
          </button>
        </div>
      )}
    </div>
  );
};
