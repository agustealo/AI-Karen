import { useMemo } from 'react';
import { TimePayload } from '../types';

export function useTimePayload(payload: TimePayload | null) {
  return useMemo(() => {
    if (!payload) return null;
    return {
      ...payload,
      isSystem: payload.source === 'system_clock',
    };
  }, [payload]);
}
