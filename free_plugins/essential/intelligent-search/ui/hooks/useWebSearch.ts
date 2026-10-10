import { useState, useCallback } from 'react';
import { SearchModeId, IntelligentSearchOptions, IntelligentSearchState, IntelligentSearchResponse } from '../types';
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
    response: null
  });

  const { buildPayload } = useSearchPayload();

  const setQuery = useCallback((query: string) => {
    setState(prev => ({ ...prev, query }));
  }, []);

  const setMode = useCallback((mode: SearchModeId) => {
    // Reset options when mode changes to prevent stale config bleeding
    setState(prev => ({ ...prev, mode, options: {}, error: null }));
  }, []);

  const updateOptions = useCallback((newOptions: Partial<IntelligentSearchOptions>) => {
    setState(prev => ({ ...prev, options: { ...prev.options, ...newOptions } }));
  }, []);

  const executeSearch = useCallback(async () => {
    if (!state.query.trim() && !['weather', 'stock_market'].includes(state.mode)) {
      setState(prev => ({ ...prev, error: new Error("Query cannot be empty for this mode.") }));
      return;
    }

    setState(prev => ({ ...prev, isLoading: true, error: null, response: null }));

    try {
      const payload = buildPayload(state.mode, state.query, state.options);
      const response = await IntelligentSearchApi.executeSearch(payload);
      
      setState(prev => ({ ...prev, isLoading: false, response }));
    } catch (error: any) {
      setState(prev => ({ ...prev, isLoading: false, error }));
    }
  }, [state.query, state.mode, state.options, buildPayload]);

  const resetSearch = useCallback(() => {
    setState(prev => ({ ...prev, query: '', error: null, response: null }));
  }, []);

  return {
    state,
    modeConfig: MODE_CONFIG[state.mode],
    setQuery,
    setMode,
    updateOptions,
    executeSearch,
    resetSearch
  };
}
