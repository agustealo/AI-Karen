import { ApiError } from '@/lib/api';

type ApiErrorPayload = Record<string, unknown>;

const DEFAULT_FAILURE_MESSAGE =
  'Karen could not complete this message. Check model availability and try again.';

const DEFAULT_DEGRADED_MESSAGE =
  'Karen is running in degraded mode right now. Model routing is currently unavailable or misconfigured.';

const AUTH_FAILURE_MESSAGE =
  'Karen could not use the requested provider with your current session permissions. Sign in again or switch to an available model.';

const NETWORK_FAILURE_MESSAGE =
  'Karen could not reach the chat service. Check your connection and try again.';

const NO_ACTIVE_MODEL_PROVIDERS_MESSAGE =
  'Karen could not find an active model provider. Check local model availability or provider configuration and try again.';

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
      return NO_ACTIVE_MODEL_PROVIDERS_MESSAGE;
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
        return NO_ACTIVE_MODEL_PROVIDERS_MESSAGE;
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
      return NO_ACTIVE_MODEL_PROVIDERS_MESSAGE;
    }
    return message;
  }

  return DEFAULT_FAILURE_MESSAGE;
};


/**
 * Safe presentation of CopilotKit/AG-UI terminal failures.
 *
 * CopilotKit can replace a backend RUN_ERROR with "Unable to complete the
 * response" or reject runAgent() without retaining its error payload.
 * Interpret only known codes and HTTP status values. Raw thrown messages,
 * stack traces, URLs, headers and provider payloads must never reach the UI.
 *
 * An unknown outcome must never suggest the prompt was not persisted, so the
 * user is directed to verified conversation history before manual retry.
 */
const RUN_FAILURE_GUIDANCE: Readonly<Record<string, string>> = {
  CHAT_RUNTIME_GATED:
    'Karen cannot accept chat execution until the runtime gate is cleared. Check system maintenance or runtime status, then retry.',
  CHAT_TRANSCRIPT_NOT_PERSISTED:
    'Karen could not confirm that the chat response was saved to conversation history. Check verified history before retrying.',
  CHAT_TRANSCRIPT_PERSISTENCE_FAILED:
    'Karen generated a response, but its conversation history could not be verified as saved. Check conversation history before sending the prompt again.',
  CHAT_EVENT_JOURNAL_UNAVAILABLE:
    'The chat event journal was unavailable. Karen cannot verify the run outcome. Check conversation history and backend health before retrying.',
  CHAT_STREAM_UPSTREAM_TERMINATED:
    'The backend connection ended before Karen confirmed completion. Check API and Redis readiness, then inspect conversation history before retrying.',
  CHAT_STREAM_UPSTREAM_INTERRUPTED:
    'The backend stream was interrupted before completion. Check API connectivity and the verified conversation history before retrying.',
  CHAT_SSE_MISSING_TERMINAL:
    'Karen received an incomplete response stream without a confirmed finish. Check conversation history and API readiness before retrying.',
  CHAT_STREAM_RUNTIME_EXCEPTION:
    'The chat runtime failed during generation. Check runtime logs, the selected model and provider availability, then inspect history before retrying.',
  CHAT_RUNTIME_ERROR:
    'Karen reported a chat runtime failure. Check runtime logs and available models, then inspect history before retrying.',
  CHAT_GENERATION_FAILED:
    'The selected model or generation runtime could not complete this answer. Check the available provider and backend logs, then verified history before retrying.',
  CHAT_EXECUTION_FAILED:
    'The chat execution failed. Check provider availability and backend logs, then inspect history before retrying.',
  CHAT_RUN_LEASE_LOST:
    'Karen lost the verified ownership of this run. Check the latest run status and conversation history before retrying.',
  CHAT_STREAM_CANCELLED:
    'The chat run was cancelled. Check verified history for any partial response before starting another run.',
  BACKEND_TARGET_NOT_CONFIGURED:
    'The chat backend address is not configured. An administrator must repair the deployment connection before prompts can run.',
  external_admin_permission_required:
    'Karen blocked an external provider because administrator authorization is not active. Choose an available local model or request external-provider approval.',
};

const RUN_FAILURE_UNKNOWN =
  'Karen could not verify completion, and the chat transport did not provide a recognized failure code. Check API readiness, the selected model and verified conversation history before retrying.';

const RUN_FAILURE_CODE = /^[A-Z][A-Z0-9_]{2,127}$/;

function runFailureDetail(value: unknown): {
  code: string | null;
  status: number | null;
} {
  const candidates: unknown[] = [value];
  const visited = new Set<unknown>();
  let status: number | null = null;
  for (let index = 0; index < candidates.length && index < 10; index += 1) {
    const item = candidates[index];
    if (!isRecord(item) || visited.has(item)) continue;
    visited.add(item);

    const code = item.code ?? item.error_code;
    if (typeof code === 'string' && RUN_FAILURE_CODE.test(code) &&
        Object.prototype.hasOwnProperty.call(RUN_FAILURE_GUIDANCE, code)) {
      return { code, status };
    }

    if (typeof item.status === 'number' &&
        Number.isInteger(item.status) && item.status >= 400 && item.status <= 599) {
      status = item.status;
    }

    for (const key of ['event', 'error', 'cause', 'detail', 'response']) {
      if (isRecord(item[key])) candidates.push(item[key]);
    }
  }
  return { code: null, status };
}

export function getCopilotRunFailureMessage(failure: unknown): string {
  const { code, status } = runFailureDetail(failure);
  if (code !== null) {
    return `${RUN_FAILURE_GUIDANCE[code]} (Code: ${code})`;
  }
  if (status === 401 || status === 403) {
    return 'Your chat session was rejected. Sign in again, then check conversation history before resending. (HTTP ' + status + ')';
  }
  if (status === 429) {
    return 'Karen is rate-limited. Check conversation history before retrying after the limit resets. (HTTP 429)';
  }
  if (status === 408 || status === 504) {
    return 'The chat request timed out. Its final outcome is unknown. Check conversation history and backend connectivity before retrying. (HTTP ' + status + ')';
  }
  if (status === 503 || status === 502) {
    return 'The chat backend or a required dependency is unavailable. Check API, Redis and model availability, then verified history before retrying. (HTTP ' + status + ')';
  }
  if (status !== null) {
    return 'The chat request was rejected by the server (HTTP ' + status + '). Check verified history and backend logs before retrying.';
  }
  return RUN_FAILURE_UNKNOWN;
}
