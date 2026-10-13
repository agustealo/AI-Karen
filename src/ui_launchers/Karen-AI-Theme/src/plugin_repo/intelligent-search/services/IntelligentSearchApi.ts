import { PluginExecutionEnvelope, IntelligentSearchResponse } from '../types';
import { apiClient } from '@/lib/api';

function isSearchResponse(value: unknown): value is IntelligentSearchResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }

  const record = value as Record<string, unknown>;
  return (
    typeof record.summary === 'string' ||
    Array.isArray(record.sources) ||
    Array.isArray(record.results) ||
    (record.diagnostics !== null && typeof record.diagnostics === 'object') ||
    (record.extractedData !== null && typeof record.extractedData === 'object') ||
    (record.liveSearch !== null && typeof record.liveSearch === 'object')
  );
}

function normalizeSearchResponse(value: unknown): IntelligentSearchResponse {
  if (isSearchResponse(value)) {
    return value;
  }

  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    const candidate = record.result ?? record.data ?? record.payload;
    if (isSearchResponse(candidate)) {
      return candidate;
    }
    if (isSearchResponse(record.response)) {
      return record.response as IntelligentSearchResponse;
    }
  }

  throw new Error('Search returned an invalid response. Please check plugin runtime health and try again.');
}

export const IntelligentSearchApi = {
  executeSearch: async (payload: Record<string, unknown>): Promise<IntelligentSearchResponse> => {
    const response = await apiClient.post<PluginExecutionEnvelope<IntelligentSearchResponse> | IntelligentSearchResponse>(
      '/api/plugins/execute',
      {
        plugin_name: 'intelligent-search',
        parameters: payload,
      }
    );
    const envelope = response as PluginExecutionEnvelope<IntelligentSearchResponse>;

    if (envelope?.error) {
      throw new Error(envelope.error);
    }

    if (envelope?.result !== undefined) {
      return normalizeSearchResponse(envelope.result);
    }

    if (envelope?.data !== undefined) {
      return normalizeSearchResponse(envelope.data);
    }

    if (envelope?.payload !== undefined) {
      return normalizeSearchResponse(envelope.payload);
    }

    return normalizeSearchResponse(response);
  },
};
