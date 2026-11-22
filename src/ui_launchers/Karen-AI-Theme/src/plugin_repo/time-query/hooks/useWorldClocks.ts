import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import { ClockItem, TimePayload } from '../types';
import { ApiError } from '@/lib/api';

function isRateLimitError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 429;
}

export function useWorldClocks(api: TimeQueryApi) {
  const [multiClocksData, setMultiClocksData] = useState<ClockItem[]>([]);
  const [worldTimeData, setWorldTimeData] = useState<TimePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchClocks = useCallback(async () => {
    try {
      const res = await api.listMultiClocks();
      if (res && res.status === 'success' && res.clocks) {
        setMultiClocksData(res.clocks);
        setError(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load world clocks');
      if (!isRateLimitError(e)) {
        console.error(e);
      }
    }
  }, [api]);

  const searchWorldTime = useCallback(async (query: string): Promise<TimePayload | null> => {
    try {
      const res = await api.getWorldTime(query);
      if (res && res.status === 'success') {
        setWorldTimeData(res as TimePayload);
        return res as TimePayload;
      }
      return null;
    } catch (e) {
      if (!isRateLimitError(e)) {
        console.error(e);
      }
      return null;
    }
  }, [api]);

  const addClock = useCallback(async (timezone: string) => {
    await api.addMultiClock(timezone);
    await fetchClocks();
  }, [api, fetchClocks]);

  const removeClock = useCallback(async (timezone: string) => {
    await api.removeMultiClock(timezone);
    await fetchClocks();
  }, [api, fetchClocks]);

  useEffect(() => {
    fetchClocks();
  }, [fetchClocks]);

  return {
    multiClocksData,
    savedClocks: multiClocksData,
    error,
    worldTimeData,
    searchWorldTime,
    addClock,
    removeClock,
    refreshClocks: fetchClocks
  };
}
