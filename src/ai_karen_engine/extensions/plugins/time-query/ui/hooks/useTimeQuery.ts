import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import { TimePayload } from '../types';

export function useTimeQuery(api: TimeQueryApi) {
  const [data, setData] = useState<TimePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTime = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getCurrentTime();
      if (res && res.status === 'success') {
        setData(res);
        setError(null);
      } else {
        setError(res?.error || 'Failed to fetch time');
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error occurred');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    fetchTime();
  }, [fetchTime]);

  return { data, loading, error, refresh: fetchTime };
}
