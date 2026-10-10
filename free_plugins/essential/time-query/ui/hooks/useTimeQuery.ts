import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import { TimePayload, TimeQueryState } from '../types';

export const useTimeQuery = (api: TimeQueryApi) => {
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
    } catch (err: any) {
      setError(err.message || 'Error occurred');
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    fetchTime();
    // Setting up a local tick just to keep the payload 'formatted' time updating
    // We could do this purely client side, but we'll fetch once and client-tick it if needed
  }, [fetchTime]);

  return { data, loading, error, refresh: fetchTime };
};
