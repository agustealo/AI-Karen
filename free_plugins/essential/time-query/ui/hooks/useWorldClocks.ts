import { useState, useCallback, useEffect } from 'react';
import { TimeQueryApi } from '../services/timeQueryApi';
import { ClockItem, TimePayload } from '../types';
import { PluginExtensionError } from '@/lib/extensions/hooks/usePluginExtension';

function isRateLimitError(error: unknown): boolean {
  return error instanceof PluginExtensionError && error.status === 429;
}

export const useWorldClocks = (api: TimeQueryApi) => {
  const [multiClocksData, setMultiClocksData] = useState<ClockItem[]>([]);
  const [worldTimeData, setWorldTimeData] = useState<TimePayload | null>(null);

  const fetchClocks = useCallback(async () => {
    try {
      const res = await api.listMultiClocks();
      if (res && res.status === 'success' && res.clocks) {
        setMultiClocksData(res.clocks);
      }
    } catch (e) {
      if (!isRateLimitError(e)) {
        console.error(e);
      }
    }
  }, [api]);

  const searchWorldTime = async (query: string) => {
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
  };

  const addClock = async (timezone: string) => {
    await api.addMultiClock(timezone);
    await fetchClocks();
  };

  const removeClock = async (timezone: string) => {
    // Assuming timezone acts as clock_id here due to simplicity of legacy, though ideally it should be ID.
    // Let's pass timezone. Let backend remove it.
    await api.removeMultiClock(timezone);
    await fetchClocks();
  };

  useEffect(() => {
    fetchClocks();
  }, [fetchClocks]);

  return { 
    multiClocksData, 
    worldTimeData, 
    searchWorldTime, 
    addClock, 
    removeClock, 
    refreshClocks: fetchClocks 
  };
};
