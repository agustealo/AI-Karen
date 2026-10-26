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
    // The plugin envelope can be HTTP-successful while capability execution
    // failed. Honor execution truth rather than rendering diagnostics as results.
    const status = typeof value.status === 'string' ? value.status.toLowerCase() : '';
    if (status === 'needs_location') return value;
    if (status === 'error' || status === 'failed' || value.can_execute === false && value.reason) {
      throw new Error(
        typeof value.reason === 'string' && value.reason.trim()
          ? value.reason
          : 'The requested search capability is unavailable. Please retry.'
      );
    }
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
  fetchArticle: async (articleId: string): Promise<string> => {
    const result = await apiClient.get<{ article_id: string; full_content: string }>(
      `/api/plugins/search/articles/${encodeURIComponent(articleId)}`
    );
    if (result.article_id !== articleId || typeof result.full_content !== 'string') {
      throw new Error('Stored article response was invalid.');
    }
    return result.full_content;
  },
  executeSearch: async (payload: Record<string, unknown>, signal?: AbortSignal): Promise<IntelligentSearchResponse> => {
    const response = await apiClient.post<PluginExecutionEnvelope<IntelligentSearchResponse> | IntelligentSearchResponse>(
      '/api/plugins/execute',
      {
        plugin_name: 'intelligent-search',
        parameters: payload,
      },
      { signal }
    );
    const envelope = response as PluginExecutionEnvelope<IntelligentSearchResponse>;

    if (envelope?.error) {
      throw new Error(envelope.error);
    }

    // A plugin execution failure may still contain response-shaped diagnostics.
    // Never mistake those diagnostics for successful search evidence.
    if (envelope?.success === false && !(envelope.result && typeof envelope.result === 'object' && (envelope.result as IntelligentSearchResponse).status === 'needs_location') && !(envelope.data && typeof envelope.data === 'object' && (envelope.data as IntelligentSearchResponse).status === 'needs_location')) {
      throw new Error(envelope.message || 'Search could not be completed. Please try again.');
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
