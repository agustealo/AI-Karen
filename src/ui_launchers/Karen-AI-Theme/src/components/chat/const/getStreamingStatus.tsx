export function getStreamingStatus(
  isBackendOffline: boolean,
  isLoading: boolean,
  processingStatus: string,
  streamingMetrics: {
    connectionHealth: string;
    chunksReceived: number;
    totalBytes?: number;
    lastChunkTime?: number;
  } | null,
): string;

export function getStreamingStatus(
  isBackendOffline: boolean,
  isLoading: boolean,
  processingStatus: string,
  streamingMetrics: {
    connectionHealth: string;
    chunksReceived: number;
    totalBytes?: number;
    lastChunkTime?: number;
  } | null,
  statusMetadata?: Record<string, unknown> | null,
): string;

export function getStreamingStatus(
  isBackendOffline: boolean,
  isLoading: boolean,
  processingStatus: string,
  streamingMetrics: {
    connectionHealth: string;
    chunksReceived: number;
    totalBytes?: number;
    lastChunkTime?: number;
  } | null,
  statusMetadata?: Record<string, unknown> | null,
): string {
  if (isBackendOffline) return 'Offline - Limited functionality';

  if (isLoading && processingStatus) {
    const statusLower = processingStatus.toLowerCase();
    const llm = isRecord(statusMetadata?.llm) ? statusMetadata.llm : statusMetadata;
    const actualProvider = formatProviderLabel(
      llm?.actual_provider || llm?.provider || statusMetadata?.actual_provider,
    );
    const requestedProvider = formatProviderLabel(
      llm?.requested_provider || statusMetadata?.requested_provider,
    );
    const statusProvider = actualProvider || requestedProvider;

    // Priority status indicators (errors take precedence)
    if (statusLower.includes('error') || statusLower.includes('failed')) {
      return `${processingStatus} ❌`;
    }
    if (statusLower.includes('timeout')) {
      return `${processingStatus} ⏰`;
    }
    if (statusLower.includes('cancelled') || statusLower.includes('aborted')) {
      return `${processingStatus} 🚫`;
    }
    if (statusLower.includes('degraded') || statusLower.includes('fallback')) {
      return `${processingStatus} ⚠️`;
    }

    // Connection health indicators with streaming metrics
    if (streamingMetrics) {
      const { connectionHealth, chunksReceived, totalBytes } = streamingMetrics;

      // Enhanced health icons with more granularity
      const healthIcons = {
        excellent: '🟢',
        good: '🟡',
        poor: '🟠',
        critical: '🔴',
        unknown: '⚪'
      };

      const healthIcon = healthIcons[connectionHealth as keyof typeof healthIcons] || '💭';

      // Show chunk count for active streaming
      if (chunksReceived > 0) {
        const bytesFormatted = totalBytes ? formatBytes(totalBytes) : '';
        const bytesText = bytesFormatted ? ` • ${bytesFormatted}` : '';
        const providerText = statusProvider ? ` • ${statusProvider}` : '';
        return `${healthIcon} ${processingStatus} (${chunksReceived} chunks${bytesText}${providerText})`;
      }

      return statusProvider
        ? `${healthIcon} ${processingStatus} • ${statusProvider}`
        : `${healthIcon} ${processingStatus}`;
    }

    // Default processing indicator
    return statusProvider
      ? `${processingStatus} • ${statusProvider} 💭`
      : `${processingStatus} 💭`;
  }

  return '';
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
};

const formatProviderLabel = (provider: unknown): string => {
  const normalized = typeof provider === 'string'
    ? provider.trim().toLowerCase().replace(/[\s-]+/g, '_')
    : String(provider ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');

  const label = normalized.replace(/_/g, ' ');
  if (!label) return '';
  if (label === 'builtin vllm' || label === 'vllm') return 'vLLM';
  if (label === 'builtin transformers' || label === 'transformers') return 'Transformers';
  if (label === 'openai compatible') return 'OpenAI-compatible provider';
  return label.charAt(0).toUpperCase() + label.slice(1);
};

// Helper function to format bytes
const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};
