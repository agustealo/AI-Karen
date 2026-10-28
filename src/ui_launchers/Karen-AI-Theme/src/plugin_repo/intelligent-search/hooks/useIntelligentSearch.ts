import { useState, useCallback, useEffect, useRef } from 'react';
import { SearchModeId, IntelligentSearchOptions, IntelligentSearchState } from '../types';
import { useSearchPayload } from './useSearchPayload';
import { IntelligentSearchApi } from '../services/IntelligentSearchApi';
import { MODE_CONFIG } from '../configs/modeConfig';

export function useIntelligentSearch() {
  const [state, setState] = useState<IntelligentSearchState>({
    query: '',
    mode: 'auto',
    options: {},
    isLoading: false,
    error: null,
    response: null,
  });

  const { buildPayload } = useSearchPayload();
  const requestSequence = useRef(0);
  const mounted = useRef(true);
  const activeRequest = useRef<AbortController | null>(null);

  const invalidatePending = useCallback(() => {
    requestSequence.current += 1;
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      invalidatePending();
    };
  }, [invalidatePending]);

  const setQuery = useCallback((query: string) => {
    invalidatePending();
    setState((prev) => ({ ...prev, query, isLoading: false, response: null, error: null }));
  }, [invalidatePending]);

  const setMode = useCallback((mode: SearchModeId) => {
    invalidatePending();
    setState((prev) => ({ ...prev, mode, options: {}, isLoading: false, response: null, error: null }));
  }, [invalidatePending]);

  const updateOptions = useCallback((newOptions: Partial<IntelligentSearchOptions>) => {
    invalidatePending();
    // Keep the last completed evidence visible while the user adjusts settings.
    // Invalidate any in-flight execution so its result cannot overwrite this state.
    setState((prev) => ({ ...prev, options: { ...prev.options, ...newOptions }, isLoading: false, error: null }));
  }, [invalidatePending]);

  const executeSearch = useCallback(async () => {
    if (!state.query.trim() && !['weather', 'stock_market'].includes(state.mode)) {
      setState((prev) => ({ ...prev, error: new Error('Query cannot be empty for this mode.') }));
      return;
    }

    invalidatePending();
    const requestId = requestSequence.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    setState((prev) => ({ ...prev, isLoading: true, error: null, response: null }));

    try {
      const payload = buildPayload(state.mode, state.query, state.options);
      const response = await IntelligentSearchApi.executeSearch(payload, controller.signal);
      if (mounted.current && requestId === requestSequence.current) {
        setState((prev) => ({ ...prev, isLoading: false, response }));
      }
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      if (mounted.current && requestId === requestSequence.current) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: error instanceof Error ? error : new Error(String(error))
        }));
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }, [state.query, state.mode, state.options, buildPayload, invalidatePending]);

  const resetSearch = useCallback(() => {
    invalidatePending();
    setState((prev) => ({ ...prev, query: '', isLoading: false, error: null, response: null }));
  }, [invalidatePending]);

  return {
    state,
    modeConfig: MODE_CONFIG[state.mode],
    setQuery,
    setMode,
    updateOptions,
    executeSearch,
    resetSearch,
  };
}
