import { PluginExecutionEnvelope, IntelligentSearchResponse } from '../types';
import { apiClient } from '@/lib/api';

function isSearchResponse(value: unknown): value is IntelligentSearchResponse {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }

  const record = value as Record<string, unknown>;
  return (
    record.status === 'needs_location' ||
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
      return normalizeSearchResponse(candidate);
    }
    if (isSearchResponse(record.response)) {
      return normalizeSearchResponse(record.response);
    }
  }

  throw new Error('Search returned an invalid response. Please check plugin runtime health and try again.');
}

const RUNTIME_RETRIEVAL_KEYS = new Set([
  'allowed_domains', 'blocked_domains', 'time_range', 'prefer_recent', 'max_urls',
]);

export function canUseRuntimeSearch(payload: Record<string, unknown>): boolean {
  if (payload.mode !== 'general' || payload.crawl !== undefined) return false;
  const context = payload.context;
  return Boolean(context && typeof context === 'object' && !Array.isArray(context) &&
    Object.keys(context).every(key => RUNTIME_RETRIEVAL_KEYS.has(key)));
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function evidenceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) return null;
    url.hash = '';
    return url.href;
  } catch {
    return null;
  }
}

export function normalizeRuntimeSearch(value: unknown, query: string): IntelligentSearchResponse {
  const response = asRecord(value);
  const metadata = asRecord(response.metadata);
  const composition = metadata.answer_composition_status;
  if (composition !== 'grounded_model' && composition !== 'retrieved_evidence') {
    throw new Error('The runtime could not complete an authorized general search.');
  }
  const sources = (Array.isArray(response.sources) ? response.sources : []).flatMap((item, index) => {
    const source = asRecord(item);
    const url = evidenceUrl(source.url);
    if (!url) return [];
    if (![source.snippet, source.content].some(text => typeof text === 'string' && text.trim())) return [];
    return [{
      id: typeof source.id === 'string' ? source.id : String(index),
      url,
      title: typeof source.title === 'string' ? source.title : url,
      ...(typeof source.snippet === 'string' ? { snippet: source.snippet } : {}),
      ...(typeof source.content === 'string' ? { content: source.content } : {}),
      ...(typeof source.article_id === 'string' ? { article_id: source.article_id } : {}),
    }];
  });
  if (!sources.length) throw new Error('Search returned no usable source evidence.');
  const sourceByUrl = new Map(sources.map(source => [source.url, source]));
  const citedUrls = new Set<string>();
  const citations = (Array.isArray(response.citations) ? response.citations : []).flatMap(item => {
    const citation = asRecord(item);
    const url = evidenceUrl(citation.url);
    const source = url ? sourceByUrl.get(url) : undefined;
    if (!url || !source || citedUrls.has(url)) return [];
    citedUrls.add(url);
    return [{ url, title: source.title, sourceId: source.id }];
  });
  const grounded = composition === 'grounded_model' &&
    metadata.response_source === 'grounded_search_model' &&
    metadata.degraded_mode === false &&
    typeof metadata.actual_provider === 'string' && Boolean(metadata.actual_provider.trim()) &&
    typeof metadata.actual_model === 'string' && Boolean(metadata.actual_model.trim()) &&
    typeof response.content === 'string' && Boolean(response.content.trim());
  return {
    summary: '',
    query,
    mode: 'general',
    status: 'success',
    can_execute: true,
    sources,
    citations,
    metadata,
    provider: typeof metadata.capability_data_provider === 'string' ? metadata.capability_data_provider : undefined,
    runtimeAnswer: grounded ? {
      text: response.content as string,
      provider: metadata.actual_provider as string,
      model: metadata.actual_model as string,
    } : undefined,
  };
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
    if (canUseRuntimeSearch(payload)) {
      const query = typeof payload.query === 'string' ? payload.query : '';
      const response = await apiClient.post<unknown>('/api/chat', {
        messages: [{ content: query, message_type: 'user' }],
        search_retrieval_options: payload.context,
      }, { signal });
      return normalizeRuntimeSearch(response, query);
    }
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
    // Examine all supported envelope shapes, not only the first present key.
    // An invalid first key must never conceal a valid structured clarification,
    // and conflicting execution results must fail rather than be cherry-picked.
    const responseCandidates: unknown[] = [
      envelope?.result, envelope?.data, envelope?.payload,
      response && typeof response === 'object' && 'response' in response
        ? (response as { response?: unknown }).response : undefined,
    ].filter((candidate) => candidate !== undefined);
    const directResponse = responseCandidates.length === 0 && isSearchResponse(response) &&
      (response as IntelligentSearchResponse).status === 'needs_location';
    const locationRequired = directResponse || (responseCandidates.length > 0 &&
      responseCandidates.every((candidate) =>
        isSearchResponse(candidate) && candidate.status === 'needs_location'));
    if (envelope?.success === false && !locationRequired) {
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
