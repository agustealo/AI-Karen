import { PluginExecutionEnvelope, IntelligentSearchResponse } from '../types';
import { apiClient } from '@/lib/api';

function isSearchResponse(value: unknown): value is IntelligentSearchResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }

  const record = value as Record<string, unknown>;
  return (
    'summary' in record ||
    'sources' in record ||
    'results' in record ||
    'liveSearch' in record ||
    'diagnostics' in record ||
    'metadata' in record ||
    'extractedData' in record
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

  return {
    summary: '',
  };
}

export const IntelligentSearchApi = {
  executeSearch: async (payload: any): Promise<IntelligentSearchResponse> => {
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
