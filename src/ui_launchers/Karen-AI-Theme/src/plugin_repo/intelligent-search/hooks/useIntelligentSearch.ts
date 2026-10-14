import { useState, useCallback, useEffect, useRef } from 'react';
import { SearchModeId, IntelligentSearchOptions, IntelligentSearchState } from '../types';
import { useSearchPayload } from './useSearchPayload';
import { IntelligentSearchApi } from '../services/IntelligentSearchApi';
import { MODE_CONFIG } from '../configs/modeConfig';

export function useIntelligentSearch() {
  const [state, setState] = useState<IntelligentSearchState>({
    query: '',
    mode: 'general',
    options: {},
    isLoading: false,
    error: null,
    response: null,
  });

  const { buildPayload } = useSearchPayload();
  const requestSequence = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, []);

  const setQuery = useCallback((query: string) => {
    requestSequence.current += 1;
    setState((prev) => ({ ...prev, query, isLoading: false, response: null, error: null }));
  }, []);

  const setMode = useCallback((mode: SearchModeId) => {
    requestSequence.current += 1;
    setState((prev) => ({ ...prev, mode, options: {}, isLoading: false, response: null, error: null }));
  }, []);

  const updateOptions = useCallback((newOptions: Partial<IntelligentSearchOptions>) => {
    requestSequence.current += 1;
    setState((prev) => ({ ...prev, options: { ...prev.options, ...newOptions }, isLoading: false, response: null, error: null }));
  }, []);

  const executeSearch = useCallback(async () => {
    if (!state.query.trim() && !['weather', 'stock_market'].includes(state.mode)) {
      setState((prev) => ({ ...prev, error: new Error('Query cannot be empty for this mode.') }));
      return;
    }

    const requestId = ++requestSequence.current;
    setState((prev) => ({ ...prev, isLoading: true, error: null, response: null }));

    try {
      const payload = buildPayload(state.mode, state.query, state.options);
      const response = await IntelligentSearchApi.executeSearch(payload);
      if (mounted.current && requestId === requestSequence.current) {
        setState((prev) => ({ ...prev, isLoading: false, response }));
      }
    } catch (error: unknown) {
      if (mounted.current && requestId === requestSequence.current) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: error instanceof Error ? error : new Error(String(error))
        }));
      }
    }
  }, [state.query, state.mode, state.options, buildPayload]);

  const resetSearch = useCallback(() => {
    requestSequence.current += 1;
    setState((prev) => ({ ...prev, query: '', isLoading: false, error: null, response: null }));
  }, []);

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
