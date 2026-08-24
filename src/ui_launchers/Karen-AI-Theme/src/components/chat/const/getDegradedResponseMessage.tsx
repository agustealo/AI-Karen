import { ApiError } from '@/lib/api';

type ApiErrorPayload = Record<string, unknown>;

const DEFAULT_FAILURE_MESSAGE =
  'Karen could not complete this message. Check model availability and try again.';

const DEFAULT_DEGRADED_MESSAGE =
  'Karen is running in degraded mode right now. Model routing is currently unavailable or misconfigured.';

const NO_ACTIVE_CLOUD_PROVIDERS_MESSAGE =
  'No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.';

const AUTH_FAILURE_MESSAGE =
  'Karen could not use the requested provider with your current session permissions. Sign in again or switch to an available model.';

const NETWORK_FAILURE_MESSAGE =
  'Karen could not reach the chat service. Check your connection and try again.';

const cleanString = (value: unknown): string => {
  return typeof value === 'string' ? value.trim() : '';
};

const isRecord = (value: unknown): value is ApiErrorPayload => {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
};

const isUsefulMessage = (value: unknown): value is string => {
  const cleaned = cleanString(value);

  if (!cleaned || cleaned.length < 3) {
    return false;
  }

  const lowered = cleaned.toLowerCase();

  return ![
    'error',
    'failed',
    'unknown',
    'undefined',
    'null',
    '[object object]',
  ].includes(lowered);
};

const normalizeRuntimeMode = (value: unknown): string => {
  return cleanString(value).toLowerCase().replace(/[\s-]+/g, '_');
};

const getNestedPayloads = (payload: unknown): ApiErrorPayload[] => {
  if (!isRecord(payload)) {
    return [];
  }

  const nestedKeys = ['detail', 'error', 'message', 'data', 'payload', 'runtime'];
  const nestedPayloads: ApiErrorPayload[] = [payload];

  nestedKeys.forEach((key) => {
    const nested = payload[key];

    if (isRecord(nested)) {
      nestedPayloads.push(nested);
    }
  });

  return nestedPayloads;
};

const extractRuntimeModeMessage = (payload: unknown): string => {
  const payloads = getNestedPayloads(payload);

  for (const item of payloads) {
    const runtimeMode = normalizeRuntimeMode(item.mode ?? item.status);

    if (
      ['maintenance', 'emergency_fallback', 'degraded', 'degraded_mode'].includes(
        runtimeMode,
      )
    ) {
      const message =
        cleanString(item.message) ||
        cleanString(item.detail) ||
        cleanString(item.error);

      if (isUsefulMessage(message)) {
        if (
          message.toLowerCase().includes('no configured provider could generate a response') ||
          message.toLowerCase().includes('no active cloud providers') ||
          message.toLowerCase().includes('expression engine is currently inactive')
        ) {
          return NO_ACTIVE_CLOUD_PROVIDERS_MESSAGE;
        }
        return message;
      }
    }
  }

  return '';
};

const extractPayloadMessage = (payload: unknown): string => {
  const payloads = getNestedPayloads(payload);

  const keys = [
    'message',
    'detail',
    'error',
    'description',
    'reason',
    'failure_reason',
    'degradation_reason',
    'status_message',
  ];

  for (const item of payloads) {
    for (const key of keys) {
      const value = item[key];

      if (isUsefulMessage(value)) {
        return value;
      }
    }
  }

  return '';
};

const getStatusMessage = (status: number, fallbackDetail: string): string => {
  if (status === 401 || status === 403) {
    return AUTH_FAILURE_MESSAGE;
  }

  if (status === 408 || status === 504) {
    return 'Karen timed out while waiting for the chat runtime. Try again or switch to another available provider.';
  }

  if (status === 404) {
    return fallbackDetail || 'Karen could not find the requested chat endpoint or provider route.';
  }

  if (status === 429) {
    return fallbackDetail || 'Karen hit a provider or runtime rate limit. Try again shortly or switch providers.';
  }

  if (status >= 500) {
    if (
      fallbackDetail.toLowerCase().includes('no configured provider could generate a response') ||
      fallbackDetail.toLowerCase().includes('expression engine is currently inactive')
    ) {
      return NO_ACTIVE_CLOUD_PROVIDERS_MESSAGE;
    }

    return fallbackDetail || DEFAULT_DEGRADED_MESSAGE;
  }

  if (status >= 400) {
    return fallbackDetail || 'Karen encountered an API error while processing your request.';
  }

  return fallbackDetail || DEFAULT_FAILURE_MESSAGE;
};

export const getDegradedResponseMessage = (error: unknown): string => {
  if (error instanceof ApiError) {
    const errorPayload = isRecord(error.details) ? error.details : {};
    const runtimeMessage = extractRuntimeModeMessage(errorPayload);

    if (runtimeMessage) {
      return runtimeMessage;
    }

    const payloadMessage = extractPayloadMessage(errorPayload);

    if (payloadMessage) {
      return getStatusMessage(error.status, payloadMessage);
    }

    const directMessage = cleanString(error.message);

    if (isUsefulMessage(directMessage)) {
      return getStatusMessage(error.status, directMessage);
    }

    return getStatusMessage(error.status, '');
  }

  if (error instanceof TypeError) {
    const message = cleanString(error.message);

    if (
      message.toLowerCase().includes('failed to fetch') ||
      message.toLowerCase().includes('network') ||
      message.toLowerCase().includes('connection')
    ) {
      return NETWORK_FAILURE_MESSAGE;
    }

    return message || NETWORK_FAILURE_MESSAGE;
  }

  if (error instanceof DOMException && error.name === 'AbortError') {
    return 'Karen timed out or the chat request was cancelled before completion.';
  }

  if (error instanceof Error) {
    const message = cleanString(error.message);

    if (isUsefulMessage(message)) {
      if (
        message.toLowerCase().includes('no configured provider could generate a response') ||
        message.toLowerCase().includes('expression engine is currently inactive')
      ) {
        return NO_ACTIVE_CLOUD_PROVIDERS_MESSAGE;
      }
      return message;
    }
  }

  if (isUsefulMessage(error)) {
    const message = cleanString(error);
    if (
      message.toLowerCase().includes('no configured provider could generate a response') ||
      message.toLowerCase().includes('expression engine is currently inactive')
    ) {
      return NO_ACTIVE_CLOUD_PROVIDERS_MESSAGE;
    }
    return message;
  }

  return DEFAULT_FAILURE_MESSAGE;
};
