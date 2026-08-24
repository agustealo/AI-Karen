import type { ChatMessage, MessageResponse } from '@/lib/types';
import { getDegradationReasonLabel } from '@/components/chat/const/constants';

type PrimitiveMetadataValue = string | number | boolean | null | undefined;

type SuggestedAction = {
  type: string;
  params?: Record<string, PrimitiveMetadataValue>;
  confidence?: number;
  description?: string;
};

type ProviderAttempt = {
  provider: string;
  model?: string;
  status: string;
  error_type?: string;
  error_message?: string;
  latency_ms?: number;
};

type BackendChatEnvelope = {
  answer?: string;
  content?: string;
  response?: string;
  mode?: string;
  message?: string;
  reason?: string;
  retry_after_seconds?: number;
  estimated_completion_time?: string | null;
  notification_supported?: boolean;
  notification_request_allowed?: boolean;
  system_status_code?: number;
  support_hint?: string;
  structured_content?: Record<string, unknown>;
  structuredContent?: Record<string, unknown>;
  actions?: SuggestedAction[];
  metadata?: Record<string, unknown>;
  correlation_id?: string;
  request_id?: string;
  response_id?: string;
  processing_time?: number;
  execution_path?: string;
  assistant_message_id?: string;
  conversation_id?: string;
  model?: string;
  usage?: Record<string, unknown>;
  used_fallback?: boolean;
  context_used?: boolean;
};

export type NormalizedChatResponse = {
  answer: string;
  structuredContent: Record<string, unknown>;
  actions: SuggestedAction[];
  metadata: Record<string, unknown>;
  correlationId: string;
};

export type DegradedPresentation = {
  hasLlmInfo: boolean;
  failureCategory: string;
  isSafetyBlocked: boolean;
  usedFallback: boolean;
  isLocalFallbackSource: boolean;
  isDegraded: boolean;
  requestedProvider: string;
  requestedModel: string;
  actualProvider: string;
  actualModel: string;
  failureReason: string;
  providerDisplayName: string;
  modelDisplayName: string;
  degradedStatusLabel: string;
  degradedBannerText: string;
  visibleDegradedNotice: string;
  detailsStatusLabel: string;
  fallbackDetailsText: string;
  shouldRenderFallbackDetails: boolean;
  shouldRenderDegradedState: boolean;
  capabilityWarning?: string;
};

export type ResponseDetailsPresentation = {
  hasMetadataDetails: boolean;
  requestedProviderLabel: string;
  requestedModelLabel: string;
  providerLabel: string;
  modelLabel: string;
  modelTitle: string;
  sourceLabel: string;
  runtimeEngineLabel: string;
  fallbackLevelLabel: string;
  speedLabel: string;
  latencyLabel: string;
  engineHeaderLabel: string;
  showStatusRow: boolean;
  statusLabel: string;
  showFallbackRow: boolean;
  fallbackLabel: string;
  showReasonRow: boolean;
  reasonLabel: string;
  showTokensRow: boolean;
  tokensLabel: string;
  memoryUsedLabel: string;
  memoryClassesLabel: string;
  recallModeLabel: string;
  memorySourcesLabel: string;
  memoryLatencyLabel: string;
  memoryDegradedLabel: string;
  writebackStatusLabel: string;
  capabilityWarning?: string;
  providerAttempts?: ProviderAttempt[];
  degradationReason?: string;
  responseSourceValue?: string;
  degradedMode?: boolean;
  degradationType?: string;
};

export type CompactBadgePresentation = {
  shouldRenderBadge: boolean;
  providerLabel: string;
  modelLabel: string;
  durationLabel: string;
  speedLabel: string;
  statusLabel: string;
  isDegraded: boolean;
};

const BUILTIN_TRANSFORMERS_PROVIDER = 'builtin_transformers';
const BUILTIN_VLLM_PROVIDER = 'builtin_vllm';
const OPENAI_COMPATIBLE_PROVIDER = 'openai_compatible';
const OLLAMA_PROVIDER = 'ollama';
const DEPRECATED_PROVIDER = 'deprecated_provider';
const FALLBACK_PROVIDER = 'fallback';
const SYSTEM_PROVIDER = 'system';


export const REMOVED_PROVIDER_WARNING =
  'This provider is no longer available as a built-in runtime. Configure a custom compatible endpoint if needed.';

const BUILTIN_PROVIDER_ALIASES: Record<string, string> = {
  transformers: BUILTIN_TRANSFORMERS_PROVIDER,
  'builtin-transformers': BUILTIN_TRANSFORMERS_PROVIDER,
  builtin_transformers: BUILTIN_TRANSFORMERS_PROVIDER,
  'hf-transformers': BUILTIN_TRANSFORMERS_PROVIDER,
  hf_transformers: BUILTIN_TRANSFORMERS_PROVIDER,

  vllm: BUILTIN_VLLM_PROVIDER,
  'builtin-vllm': BUILTIN_VLLM_PROVIDER,
  builtin_vllm: BUILTIN_VLLM_PROVIDER,
  'nano-vllm': BUILTIN_VLLM_PROVIDER,
  nano_vllm: BUILTIN_VLLM_PROVIDER,
};

interface LlmMetadata {
  actual_provider?: string | null;
  provider?: string | null;
  actual_model?: string | null;
  model_id?: string | null;
  model_name?: string | null;
  requested_provider?: string | null;
  requested_model?: string | null;
  used_fallback?: boolean;
  is_fallback?: boolean;
  is_degraded?: boolean;
  failure_category?: string;
  failure_reason?: string;
  preferred_failure_reason?: string;
  response_source?: string | null;
  source?: string | null;
  runtime_engine?: string;
  fallback_level?: string | number | null;
  tokens_per_second?: number | string;
  duration?: number;
  routing_rationale?: string;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
  provider_attempts?: ProviderAttempt[];
  [key: string]: unknown;
}

interface OrchestratorMetadata {
  used_fallback?: boolean;
}

interface PersistenceMetadata {
  canonical_store?: string;
  assistant_persisted?: boolean;
}

interface ChatMetadata {
  llm?: LlmMetadata;
  orchestrator?: OrchestratorMetadata;
  persistence?: PersistenceMetadata;
  degraded_mode?: boolean;
  mode?: string;
  failure_category?: string;
  failure_reason?: string;
  error?: string;
  requested_provider?: string;
  requested_model?: string;
  actual_provider?: string;
  actual_model?: string;
  runtime_engine?: string;
  fallback_level?: string;
  correlation_id?: string;
  response_id?: string;
  request_id?: string;
  conversation_id?: string;
  ui_source?: string;
  total_ms?: number;
  context_used?: boolean;
  status?: string;
  response_source?: string;
  provider_attempts?: ProviderAttempt[];
  [key: string]: unknown;
}

const EXTERNAL_ENDPOINT_PROVIDER_ALIASES: Record<string, string> = {
  'openai-compatible': OPENAI_COMPATIBLE_PROVIDER,
  openai_compatible: OPENAI_COMPATIBLE_PROVIDER,
  openaicompatible: OPENAI_COMPATIBLE_PROVIDER,
  'openai-compatible-endpoint': OPENAI_COMPATIBLE_PROVIDER,
  openai_compatible_endpoint: OPENAI_COMPATIBLE_PROVIDER,

};

const REMOVED_LEGACY_PROVIDERS = new Set([DEPRECATED_PROVIDER]);

const INTERNAL_STRUCTURED_CONTENT_KEYS = new Set([
  'memory_classification',
  'classified_memories',
  'curated_writeback_candidates',
  'memoryClassification',
  'classifiedMemories',
  'curatedWritebackCandidates',
]);

const toCleanString = (value?: unknown): string => {
  return String(value ?? '').trim();
};

const toProviderKey = (value?: unknown): string => {
  return toCleanString(value).toLowerCase().replace(/\s+/g, '-');
};

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
};

const firstNonEmpty = (...values: unknown[]): string => {
  for (const value of values) {
    const cleaned = toCleanString(value);

    if (cleaned) {
      return cleaned;
    }
  }

  return '';
};

export const normalizeProviderName = (provider?: unknown): string => {
  const raw = toCleanString(provider);
  const key = toProviderKey(raw);

  if (!key) {
    return '';
  }

  if (BUILTIN_PROVIDER_ALIASES[key]) {
    return BUILTIN_PROVIDER_ALIASES[key];
  }

  if (EXTERNAL_ENDPOINT_PROVIDER_ALIASES[key]) {
    return EXTERNAL_ENDPOINT_PROVIDER_ALIASES[key];
  }

  const canonical = key.replace(/-/g, '_');

  if (REMOVED_LEGACY_PROVIDERS.has(canonical)) {
    return canonical;
  }

  if (key === FALLBACK_PROVIDER) {
    return FALLBACK_PROVIDER;
  }

  if (key === SYSTEM_PROVIDER) {
    return SYSTEM_PROVIDER;
  }

  return canonical;
};

export const isBuiltInRuntimeProvider = (provider?: unknown): boolean => {
  const normalized = normalizeProviderName(provider);
  return (
    normalized === BUILTIN_TRANSFORMERS_PROVIDER ||
    normalized === BUILTIN_VLLM_PROVIDER ||
    normalized === FALLBACK_PROVIDER
  );
};

export const isTransformersRuntimeProvider = (provider?: unknown): boolean => {
  return normalizeProviderName(provider) === BUILTIN_TRANSFORMERS_PROVIDER;
};

export const isVllmRuntimeProvider = (provider?: unknown): boolean => {
  return normalizeProviderName(provider) === BUILTIN_VLLM_PROVIDER;
};

export const isLocalRuntimeProvider = (provider?: unknown): boolean => {
  return normalizeProviderName(provider) === OLLAMA_PROVIDER;
};

export const isDeprecatedProvider = (provider?: unknown): boolean => {
  return normalizeProviderName(provider) === DEPRECATED_PROVIDER;
};

export const isOpenAiCompatibleProvider = (provider?: unknown): boolean => {
  return normalizeProviderName(provider) === OPENAI_COMPATIBLE_PROVIDER;
};

export const isExternalEndpointProvider = (provider?: unknown): boolean => {
  const normalized = normalizeProviderName(provider);
  return normalized === OPENAI_COMPATIBLE_PROVIDER || normalized === 'openai';
};

export const getRuntimeDisplayName = (
  provider?: unknown,
  displayName?: unknown,
): string => {
  const normalized = normalizeProviderName(provider);
  const explicit = toCleanString(displayName);

  if (normalized === BUILTIN_TRANSFORMERS_PROVIDER) {
    return 'Transformers';
  }

  if (normalized === BUILTIN_VLLM_PROVIDER) {
    return 'vLLM';
  }

  if (normalized === OPENAI_COMPATIBLE_PROVIDER) {
    return explicit || 'OpenAI-Compatible Endpoint';
  }

  if (normalized === DEPRECATED_PROVIDER || REMOVED_LEGACY_PROVIDERS.has(normalized)) {
    return REMOVED_PROVIDER_WARNING;
  }

  if (normalized === FALLBACK_PROVIDER) {
    return 'Local Emergency Fallback';
  }

  if (normalized === SYSTEM_PROVIDER) {
    return 'Runtime Control';
  }

  return explicit || toCleanString(provider) || normalized;
};

export const getRuntimeGroupLabel = (provider?: unknown): string => {
  const normalized = normalizeProviderName(provider);

  if (normalized === BUILTIN_TRANSFORMERS_PROVIDER || normalized === BUILTIN_VLLM_PROVIDER) {
    return 'Built-in Runtime';
  }

  if (normalized === 'ollama') {
    return 'Local (Hybrid)';
  }

  if (normalized === OPENAI_COMPATIBLE_PROVIDER || normalized === 'openai') {
    return 'External Endpoint';
  }

  if (normalized === DEPRECATED_PROVIDER) {
    return 'Deprecated Provider';
  }

  if (normalized === FALLBACK_PROVIDER) {
    return 'Fallback';
  }

  if (normalized === SYSTEM_PROVIDER) {
    return 'System';
  }

  return 'Custom';
};

export const normalizeModelName = (model?: unknown): string => {
  const value = toCleanString(model).toLowerCase();

  if (!value) {
    return '';
  }

  // Remove common prefixes and handle path separators
  let processed = value;
  
  // If it's a full path, just get the file name
  if (value.includes('/') || value.includes('\\')) {
    const segments = value.split(/[/\\]/);
    processed = segments[segments.length - 1] || value;
  }
  
  // Remove provider prefix if still present (e.g. "openai:gpt-4")
  if (processed.includes(':')) {
    processed = processed.split(':').pop() || processed;
  }

  // Clean up extensions and common version/type suffixes
  return processed
    .replace(/\.(gguf|bin|safetensors|onnx|h5|pt|ckpt)$/i, '')
    .replace(/-(instruct|chat|v[0-9.]+|fp16|q[0-9].*)$/i, '')
    .replace(/[_-]/g, '-')
    .trim();
};

export const getDisplayModelName = (
  modelId?: unknown,
  modelName?: unknown,
): string => {
  const explicitName = toCleanString(modelName);

  if (explicitName) {
    return explicitName;
  }

  const rawModelId = toCleanString(modelId);

  if (!rawModelId) {
    return '';
  }

  return rawModelId
    .split(':')
    .pop()
    ?.split('/')
    .pop()
    ?.replace(/\.(gguf|bin|safetensors)$/i, '')
    .replace(/[-_]/g, ' ')
    .trim() || rawModelId;
};

const getFriendlyProviderLabel = (
  provider?: unknown,
): string => {
  return getRuntimeDisplayName(provider, provider);
};

const getFriendlyModelLabel = (
  modelId?: unknown,
  modelName?: unknown,
): string => {
  return getDisplayModelName(modelId, modelName);
};

const reasonLooksUnavailable = (reason?: string | null): boolean => {
  const lower = toCleanString(reason).toLowerCase();

  return (
    lower.includes('unavailable') ||
    lower.includes('connection refused') ||
    lower.includes('connection reset') ||
    lower.includes('timeout') ||
    lower.includes('timed out') ||
    lower.includes('host.docker.internal') ||
    lower.includes('172.17.0.1') ||
    lower.includes('127.0.0.1') ||
    lower.includes('localhost') ||
    lower.includes('loopback') ||
    lower.includes('econnrefused') ||
    lower.includes('enetunreach') ||
    lower.includes('service not ready') ||
    lower.includes('provider not ready') ||
    lower.includes('model not loaded') ||
    lower.includes('model load failed')
  );
};

const reasonLooksRateLimited = (reason?: string | null): boolean => {
  const lower = toCleanString(reason).toLowerCase();

  return (
    lower.includes('rate limit') ||
    lower.includes('ratelimit') ||
    lower.includes('too many requests') ||
    lower.includes('429') ||
    lower.includes('quota') ||
    lower.includes('insufficient balance') ||
    lower.includes('resource package')
  );
};

export const sanitizeChatContent = (content?: string | null): string => {
  return String(content || '')
    .replace(/^<div class="ui-[^"]+">\s*/i, '')
    .replace(/<\/div>\s*$/i, '')
    .replace(/^<section[^>]*>\s*/i, '')
    .replace(/<\/section>\s*$/i, '')
    .replace(/^<div role="article"[^>]*>\s*/i, '')
    .replace(/<\/div>\s*$/i, '')
    .trim();
};

export const sanitizeStructuredContent = (
  structuredContent?: Record<string, unknown> | null,
): Record<string, unknown> => {
  const source = isRecord(structuredContent) ? structuredContent : {};

  return Object.fromEntries(
    Object.entries(source).filter(([key]) => !INTERNAL_STRUCTURED_CONTENT_KEYS.has(key)),
  );
};

export const deriveDegradedPresentation = (
  metadata?: Record<string, unknown>,
): DegradedPresentation => {
  const safeMetadata = (isRecord(metadata) ? metadata : {}) as ChatMetadata;
  const llm = (isRecord(safeMetadata?.llm) ? safeMetadata.llm : {}) as LlmMetadata;

  const failureCategory = toCleanString(safeMetadata?.failure_category || llm?.failure_category);
  const isSafetyBlocked = failureCategory === 'safety_blocked';

  const usedFallback =
    safeMetadata?.orchestrator?.used_fallback === true ||
    safeMetadata?.used_fallback === true ||
    llm?.used_fallback === true ||
    llm?.is_fallback === true;

  const requestedProvider = toCleanString(safeMetadata?.requested_provider || llm?.requested_provider);
  const requestedModel = toCleanString(safeMetadata?.requested_model || llm?.requested_model);
  const actualProvider = toCleanString(safeMetadata?.actual_provider || llm?.actual_provider || llm?.provider);
  const actualModelId = toCleanString(safeMetadata?.actual_model || llm?.actual_model || llm?.model_id);
  const actualModel = getFriendlyModelLabel(
    safeMetadata?.actual_model || llm?.actual_model || llm?.model_id,
    safeMetadata?.model_name || llm?.model_name,
  );

  const normalizedActualProvider = normalizeProviderName(actualProvider);
  const normalizedRequestedProvider = normalizeProviderName(requestedProvider);
  const normalizedRequestedModel = normalizeModelName(requestedModel);
  const normalizedActualModel = normalizeModelName(
    safeMetadata?.actual_model || llm?.actual_model || llm?.model_id || llm?.model_name || actualModel,
  );

  const providerChanged = Boolean(
    normalizedRequestedProvider &&
      normalizedActualProvider &&
      normalizedRequestedProvider !== normalizedActualProvider &&
      normalizedRequestedProvider !== 'auto',
  );

  const modelChanged = Boolean(
    normalizedRequestedModel &&
      normalizedActualModel &&
      normalizedRequestedModel !== normalizedActualModel &&
      normalizedRequestedModel !== 'auto',
  );

  const failureReason = toCleanString(
    safeMetadata?.failure_reason ||
      safeMetadata?.degradation_reason ||
      llm?.failure_reason,
  );

  const isDegraded = safeMetadata?.degraded_mode === true || usedFallback || providerChanged || modelChanged;

  const hasLlmInfo = Boolean(
    llm && (llm.actual_provider || llm.provider || llm.actual_model || llm.model_id || llm.model_name),
  );

  const actualProviderLabel = getFriendlyProviderLabel(actualProvider);

  const selectedRuntimeUnavailable =
    Boolean(requestedProvider) && reasonLooksUnavailable(failureReason);

  const providerOrModelChanged = providerChanged || modelChanged;
  const fallbackTransitionText =
    providerOrModelChanged &&
    requestedProvider &&
    (actualProviderLabel || actualProvider)
      ? `${requestedProvider} failed, switched to ${actualProviderLabel || actualProvider}${actualModel && actualModel !== 'none' && actualModel !== 'auto' ? ` (${actualModel})` : ''}.`
      : '';

  const degradedStatusLabel = isSafetyBlocked
    ? 'provider policy block'
    : reasonLooksRateLimited(failureReason)
      ? `${requestedProvider || 'provider'} rate limited`
      : selectedRuntimeUnavailable
        ? 'requested provider unavailable'
        : providerOrModelChanged
          ? 'provider fallback'
          : isDegraded
            ? 'degraded mode'
            : '';

  const degradedBannerText =
    fallbackTransitionText ||
    getDegradationReasonLabel(failureReason) ||
    (isDegraded ? 'System is operating in degraded mode.' : '');

  const visibleDegradedNotice =
    fallbackTransitionText ||
    getDegradationReasonLabel(failureReason) ||
    degradedBannerText;

  const shouldRenderDegradedState = isDegraded || isSafetyBlocked || Boolean(visibleDegradedNotice);

  const actualModelLower = actualModelId.toLowerCase();
  let capabilityWarning = toCleanString(llm?.capability_warning);
  if (!capabilityWarning && (actualModelLower.includes('gpt2') || actualModelLower.includes('gpt-2'))) {
    capabilityWarning = 'Selected model is a base completion model and may produce continuation-style responses.';
  }

  const providerDisplayName = actualProviderLabel || (actualProvider && actualProvider !== 'none' ? actualProvider : '');

  const modelDisplayName = isSafetyBlocked
    ? 'Safety Blocked'
    : (actualModel && actualModel !== 'none' && actualModel !== 'auto' ? actualModel : '');

  const finalStatusLabel = isSafetyBlocked
    ? 'Safety Blocked'
    : degradedStatusLabel || (isDegraded ? 'Degraded Mode' : (capabilityWarning ? 'limited capability' : 'ok'));

  const fallbackDetailsText = fallbackTransitionText || degradedBannerText;
  const shouldRenderFallbackDetails = Boolean(fallbackDetailsText && !failureReason);

  return {
    hasLlmInfo,
    failureCategory,
    isSafetyBlocked,
    usedFallback,
    isLocalFallbackSource: false,
    isDegraded,
    requestedProvider,
    requestedModel,
    actualProvider,
    actualModel,
    failureReason,
    providerDisplayName,
    modelDisplayName,
    degradedStatusLabel,
    degradedBannerText,
    visibleDegradedNotice,
    detailsStatusLabel: finalStatusLabel,
    fallbackDetailsText,
    shouldRenderFallbackDetails,
    shouldRenderDegradedState,
    capabilityWarning,
  };
};

export const deriveResponseDetailsPresentation = (
  metadata?: Record<string, unknown>,
): ResponseDetailsPresentation => {
  const safeMetadata = (isRecord(metadata) ? metadata : {}) as ChatMetadata;
  const llm = (isRecord(safeMetadata?.llm) ? safeMetadata.llm : {}) as LlmMetadata;
  const degraded = deriveDegradedPresentation(safeMetadata);
  const usage = (isRecord(llm?.usage) ? llm.usage : {}) as {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };

  const promptTokens = Number(usage.prompt_tokens || 0);
  const completionTokens = Number(usage.completion_tokens || 0);
  const totalTokens = Number(usage.total_tokens || 0);

  const hasMetadataDetails = Boolean(safeMetadata && Object.keys(safeMetadata).length > 0);
  const requestedProviderLabel = degraded.requestedProvider
    ? getFriendlyProviderLabel(degraded.requestedProvider)
    : 'N/A';
  const requestedModelLabel = degraded.requestedModel
    ? getFriendlyModelLabel(degraded.requestedModel, degraded.requestedModel)
    : 'N/A';
  const providerLabel = degraded.actualProvider ? degraded.providerDisplayName : 'none';
  const modelLabel = degraded.actualModel ? degraded.modelDisplayName : 'none';
  const modelTitle = toCleanString(safeMetadata?.actual_model || llm?.actual_model || llm?.model_id || llm?.model_name);
  const sourceLabel = toCleanString(safeMetadata?.response_source || llm?.response_source || llm?.source || 'direct');
  const runtimeEngineLabel = toCleanString(safeMetadata?.runtime_engine || llm?.runtime_engine || 'N/A');
  const fallbackLevelLabel = toCleanString(
    safeMetadata?.fallback_level ?? llm?.fallback_level ?? '0',
  );

  const speedLabel = llm?.tokens_per_second
    ? `${Number(llm.tokens_per_second).toFixed(2)} tok/s`
    : 'N/A';

  const latencyLabel =
    typeof llm?.duration === 'number'
      ? `${llm.duration.toFixed(2)}s`
      : typeof safeMetadata?.total_ms === 'number'
        ? `${(safeMetadata.total_ms / 1000).toFixed(2)}s`
        : 'N/A';

  const engineHeaderLabel = providerLabel;
  const showStatusRow = degraded.shouldRenderDegradedState;
  const statusLabel = degraded.detailsStatusLabel;
  const showFallbackRow = degraded.shouldRenderFallbackDetails;
  const fallbackLabel = degraded.fallbackDetailsText;
  const showReasonRow = Boolean(degraded.failureReason);
  const reasonLabel = getDegradationReasonLabel(degraded.failureReason);
  const showTokensRow = Boolean(llm?.usage);

  const tokensLabel = promptTokens || completionTokens
    ? `${promptTokens}i + ${completionTokens}o`
    : totalTokens
      ? `${totalTokens} total`
      : 'N/A';

  const memory = (isRecord(safeMetadata.memory) ? safeMetadata.memory : (isRecord(llm.memory) ? llm.memory : {})) as Record<string, unknown>;
  const memoryUsedLabel = (safeMetadata.memory_used ?? memory.used) ? 'yes' : 'no';
  const memoryClassesLabel = toCleanString(
    safeMetadata.memory_classes || (Array.isArray(memory.classes) ? memory.classes.join(', ') : memory.classes) || 'N/A'
  );
  const recallModeLabel = toCleanString(
    safeMetadata.memory_activation_mode || safeMetadata.recall_mode || memory.recall_mode || 'N/A'
  );
  const memorySourcesLabel = toCleanString(
    safeMetadata.memory_sources || safeMetadata.stores_queried || (Array.isArray(memory.sources) ? memory.sources.join(', ') : memory.sources) || 'N/A'
  );
  const memoryLatencyLabel = typeof safeMetadata.memory_latency_ms === 'number' 
    ? `${safeMetadata.memory_latency_ms} ms` 
    : typeof memory.latency_ms === 'number'
      ? `${Number(memory.latency_ms).toFixed(0)} ms`
      : 'N/A';
  const memoryDegradedLabel = (safeMetadata.memory_degraded ?? memory.degraded) ? 'yes' : 'no';
  const writebackStatusLabel = toCleanString(safeMetadata.memory_writeback_status || memory.writeback_status || 'N/A');
  const capabilityWarning = degraded.capabilityWarning;
  const providerAttempts =
    Array.isArray(safeMetadata.provider_attempts)
      ? (safeMetadata.provider_attempts as ProviderAttempt[])
      : Array.isArray(llm?.provider_attempts)
        ? (llm.provider_attempts as ProviderAttempt[])
        : undefined;

  return {
    hasMetadataDetails,
    requestedProviderLabel,
    requestedModelLabel,
    providerLabel,
    modelLabel,
    modelTitle,
    sourceLabel,
    runtimeEngineLabel,
    fallbackLevelLabel,
    speedLabel,
    latencyLabel,
    engineHeaderLabel,
    showStatusRow,
    statusLabel,
    showFallbackRow,
    fallbackLabel,
    showReasonRow,
    reasonLabel,
    showTokensRow,
    tokensLabel,
    memoryUsedLabel,
    memoryClassesLabel,
    recallModeLabel,
    memorySourcesLabel,
    memoryLatencyLabel,
    memoryDegradedLabel,
    writebackStatusLabel,
    capabilityWarning,
    providerAttempts,
    degradationReason: degraded.visibleDegradedNotice,
    responseSourceValue: sourceLabel,
    degradedMode: degraded.isDegraded,
    degradationType: degraded.degradedStatusLabel,
  };
};

export const deriveCompactBadgePresentation = (
  metadata?: Record<string, unknown>,
): CompactBadgePresentation => {
  const safeMetadata = (isRecord(metadata) ? metadata : {}) as ChatMetadata;
  const llm = (isRecord(safeMetadata?.llm) ? safeMetadata.llm : {}) as LlmMetadata;
  const degraded = deriveDegradedPresentation(safeMetadata);

  const hasMetadataDetails = Boolean(safeMetadata && Object.keys(safeMetadata).length > 0);
  const hasLlmInfo = degraded.hasLlmInfo;

  const shouldRenderBadge =
    hasLlmInfo || hasMetadataDetails || safeMetadata?.degraded_mode === true || Boolean(degraded.capabilityWarning);

  const providerLabel = degraded.providerDisplayName;
  const modelLabel = degraded.modelDisplayName;

  const durationLabel =
    typeof llm?.duration === 'number'
      ? `${llm.duration.toFixed(1)}s`
      : typeof safeMetadata?.total_ms === 'number'
        ? `${(safeMetadata.total_ms / 1000).toFixed(1)}s`
        : '';

  const speedLabel = llm?.tokens_per_second
    ? `${Number(llm.tokens_per_second).toFixed(2)} tok/s`
    : '';

  const statusLabel = degraded.shouldRenderDegradedState
    ? degraded.degradedStatusLabel || 'degraded mode'
    : (degraded.capabilityWarning ? 'limited capability' : '');

  return {
    shouldRenderBadge,
    providerLabel,
    modelLabel,
    durationLabel,
    speedLabel,
    statusLabel,
    isDegraded: degraded.shouldRenderDegradedState,
  };
};

const mapBackendStatusToMessageStatus = (
  status?: string | null,
): ChatMessage['status'] => {
  const normalized = toCleanString(status).toLowerCase();

  if (normalized === 'failed') {
    return 'failed';
  }

  if (normalized === 'pending') {
    return 'pending';
  }

  if (normalized === 'streaming') {
    return 'streaming';
  }

  return 'completed';
};

const ensureLlmMetadata = (
  metadata: Record<string, unknown>,
  raw: BackendChatEnvelope,
): Record<string, unknown> => {
  const m = metadata as ChatMetadata;
  const llm = (isRecord(m.llm) ? { ...m.llm } : {}) as LlmMetadata;

  if (raw.model && !llm.model_name && !llm.model_id) {
    llm.model_name = raw.model;
  }

  if (raw.usage && !llm.usage) {
    llm.usage = raw.usage as LlmMetadata['usage'];
  }

  if (typeof raw.processing_time === 'number' && llm.duration == null) {
    llm.duration = raw.processing_time;
  }

  if (Object.keys(llm).length > 0) {
    m.llm = llm;
  }

  return m;
};

const ensurePersistenceMetadata = (
  metadata: Record<string, unknown>,
): Record<string, unknown> => {
  const m = metadata as ChatMetadata;
  const existingPersistence = (isRecord(m.persistence) ? m.persistence : {}) as PersistenceMetadata;

  m.persistence = {
    canonical_store: existingPersistence.canonical_store || 'postgres',
    assistant_persisted:
      existingPersistence.assistant_persisted ??
      Boolean(m.assistant_message_id),
    ...existingPersistence,
  };

  return m;
};

export function normalizeBackendChatResponse(
  raw: BackendChatEnvelope,
): NormalizedChatResponse {
  const answer = sanitizeChatContent(raw.answer ?? raw.content ?? raw.response);
  const correlationId = firstNonEmpty(
    raw.correlation_id,
    raw.request_id,
    raw.response_id,
    isRecord(raw.metadata) ? raw.metadata.correlation_id : undefined,
    `assistant-${Date.now()}`,
  );

  const metadata = (isRecord(raw.metadata) ? { ...raw.metadata } : {}) as ChatMetadata;

  metadata.correlation_id = metadata.correlation_id || correlationId;
  metadata.response_id = metadata.response_id || raw.response_id;
  metadata.request_id = metadata.request_id || raw.request_id;
  metadata.conversation_id = metadata.conversation_id || raw.conversation_id;
  metadata.assistant_message_id =
    metadata.assistant_message_id || raw.assistant_message_id;
  metadata.execution_path =
    metadata.execution_path || raw.execution_path || 'direct_llm';
  metadata.status = metadata.status || 'completed';

  if (typeof raw.processing_time === 'number' && metadata.total_ms == null) {
    metadata.total_ms = raw.processing_time * 1000;
  }

  if (typeof raw.context_used === 'boolean' && metadata.context_used == null) {
    metadata.context_used = raw.context_used;
  }

  if (typeof raw.used_fallback === 'boolean') {
    metadata.orchestrator = {
      ...(isRecord(metadata.orchestrator) ? metadata.orchestrator : {}),
      used_fallback: raw.used_fallback,
    } as OrchestratorMetadata;
  }

  ensurePersistenceMetadata(metadata);
  ensureLlmMetadata(metadata, raw);

  const fallbackAnswer =
    firstNonEmpty(raw.message) ||
    (toCleanString(raw.mode) === 'maintenance'
      ? 'Karen is temporarily unavailable while scheduled maintenance is in progress.'
      : toCleanString(raw.mode) === 'emergency_fallback'
        ? 'Karen is temporarily unavailable. Please try again shortly.'
        : 'Karen returned an empty response.');

  return {
    answer: answer || sanitizeChatContent(fallbackAnswer),
    structuredContent: sanitizeStructuredContent(
      raw.structured_content || raw.structuredContent || {},
    ),
    actions: Array.isArray(raw.actions) ? raw.actions : [],
    metadata,
    correlationId,
  };
}

export function normalizeConversationMessage(
  message: MessageResponse,
): ChatMessage {
  const metadata = (isRecord(message.metadata) ? { ...message.metadata } : {}) as ChatMetadata;

  if (message.ui_source && !metadata.ui_source) {
    metadata.ui_source = message.ui_source;
  }

  if (typeof message.processing_time_ms === 'number' && metadata.total_ms == null) {
    metadata.total_ms = message.processing_time_ms;
  }

  if (message.model_used || typeof message.tokens_used === 'number') {
    metadata.llm = {
      ...(isRecord(metadata.llm) ? metadata.llm : {}),
      model_name: metadata.llm?.model_name || message.model_used,
      usage:
        metadata.llm?.usage ||
        (typeof message.tokens_used === 'number'
          ? { total_tokens: message.tokens_used }
          : undefined),
    } as LlmMetadata;
  }

  metadata.status = metadata.status || 'completed';

  return {
    id: message.id,
    role: message.role as ChatMessage['role'],
    content: sanitizeChatContent(message.content),
    timestamp: new Date(message.timestamp),
    status: mapBackendStatusToMessageStatus(metadata.status),
    structuredContent: sanitizeStructuredContent(message.structured_content),
    actions: Array.isArray(message.actions) ? message.actions : [],
    metadata,
  };
}
