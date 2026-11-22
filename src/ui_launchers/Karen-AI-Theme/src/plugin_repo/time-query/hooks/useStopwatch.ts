import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import { StopwatchState } from '../types';
import { ApiError } from '@/lib/api';

const isRateLimitError = (error: unknown) =>
  error instanceof ApiError && error.status === 429;

export function useStopwatch(api: TimeQueryApi) {
  const [state, setState] = useState<StopwatchState | null>(null);
  const [loading, setLoading] = useState(false);

  const performAction = useCallback(async (action: string) => {
    setLoading(true);
    try {
      const res = await api.setStopwatchAction(action);
      if (res && res.status === 'success' && res.stopwatch) {
        setState(res.stopwatch as StopwatchState);
      }
    } catch (e) {
      if (!isRateLimitError(e)) {
        console.error(e);
      }
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    const init = async () => {
      try {
        const res = await api.setStopwatchAction('status');
        if (res && res.status === 'success' && res.stopwatch) {
          setState(res.stopwatch as StopwatchState);
        }
      } catch {}
    };
    init();
  }, [api]);

  return { state, loading, performAction };
}
