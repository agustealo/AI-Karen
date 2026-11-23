import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import type { AlarmItem, AlarmCreateParams } from '../types';
import { ApiError } from '@/lib/api';

const isRateLimitError = (error: unknown) =>
  error instanceof ApiError && error.status === 429;

export function useAlarms(api: TimeQueryApi) {
  const [alarms, setAlarms] = useState<AlarmItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAlarms = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getAlarms();
      if (res && res.status === 'success' && res.alarms) {
        setAlarms(res.alarms);
        setError(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load alarms');
      if (!isRateLimitError(e)) {
        console.error(e);
      }
    } finally {
      setLoading(false);
    }
  }, [api]);

  const createAlarm = useCallback(async (data: AlarmCreateParams) => {
    await api.createAlarm(data);
    await fetchAlarms();
  }, [api, fetchAlarms]);

  const deleteAlarm = useCallback(async (id: string) => {
    await api.deleteAlarm(id);
    await fetchAlarms();
  }, [api, fetchAlarms]);

  const toggleAlarm = useCallback(async (id: string, enabled: boolean) => {
    await api.setAlarmStatus(id, enabled);
    await fetchAlarms();
  }, [api, fetchAlarms]);

  useEffect(() => {
    fetchAlarms();
  }, [fetchAlarms]);

  return { alarms, loading, error, fetchAlarms, createAlarm, deleteAlarm, toggleAlarm };
}
