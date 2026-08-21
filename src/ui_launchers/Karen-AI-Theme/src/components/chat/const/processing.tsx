import type { ReactNode } from "react";
import {
  AlertCircle,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Database,
  Loader2,
  RadioTower,
  Route,
  Save,
  ShieldCheck,
  Sparkles,
  Split,
  Wrench,
  Zap,
} from "lucide-react";

export const DEFAULT_PROCESSING_MESSAGE = "Understanding request...";
export const STREAMING_ERROR_MESSAGE = "Connection issue. Please try again.";
export const STREAM_TIMEOUT_MESSAGE = "Request timed out. Please try again.";

export const STALLED_STAGE_THRESHOLD_MS = 18_000;
export const LONG_RUNNING_STAGE_THRESHOLD_MS = 45_000;

export type ProcessingRuntimeMetadata = {
  stage?: string | null;
  node?: string | null;
  event_type?: string | null;
  eventType?: string | null;
  phase?: string | null;
  state?: string | null;
  status?: string | null;
  type?: string | null;
  message?: string | null;

  requested_provider?: string | null;
  requested_model?: string | null;
  actual_provider?: string | null;
  actual_model?: string | null;
  provider?: string | null;
  model?: string | null;
  model_id?: string | null;
  model_name?: string | null;
  fallback_next?: string | null;

  runtime_engine?: string | null;
  response_source?: string | null;
  source?: string | null;
  degraded_mode?: boolean | null;
  degradation_reason?: string | null;
  fallback_level?: number | null;

  intent?: string | null;
  confidence?: number | string | null;
  memory_recall_count?: number | string | null;
  capsule_count?: number | string | null;
  tool_count?: number | string | null;
  tool_name?: string | null;
  plugin_name?: string | null;
  mcp_server?: string | null;
  specialist?: string | null;

  latency_ms?: number | string | null;
  elapsed_ms?: number | string | null;
  started_at?: string | number | Date | null;
  updated_at?: string | number | Date | null;
  correlation_id?: string | null;
  request_id?: string | null;

  llm?: ProcessingRuntimeMetadata | null;
  runtime?: ProcessingRuntimeMetadata | null;
  metadata?: ProcessingRuntimeMetadata | null;
  [key: string]: unknown;
};

export type ProcessingStatusKey =
  | "request_received"
  | "runtime_mode_check"
  | "auth_context_resolved"
  | "session_loaded"
  | "conversation_loaded"
  | "context_assembly"
  | "cortex_start"
  | "cortex_complete"
  | "memory_recall_start"
  | "memory_recall_complete"
  | "capsule_recall_start"
  | "capsule_recall_complete"
  | "provider_selection_start"
  | "provider_selected"
  | "provider_unavailable"
  | "provider_failed"
  | "provider_retry"
  | "fallback_started"
  | "fallback_succeeded"
  | "langgraph_start"
  | "langgraph_node"
  | "medusa_start"
  | "medusa_specialist_start"
  | "tool_call_start"
  | "tool_call_complete"
  | "generation_start"
  | "response_started"
  | "streaming_tokens"
  | "persistence_start"
  | "persistence_complete"
  | "memory_writeback_start"
  | "memory_writeback_complete"
  | "post_processing"
  | "completed"
  | "failed"
  | "cancelled"
  | "degraded"
  | "degraded_live"
  | "emergency_static";

export type ChatProcessingState =
  | "idle"
  | "queued"
  | "preparing"
  | "authenticating"
  | "context"
  | "cortex"
  | "retrieving_memory"
  | "routing"
  | "deep_reasoning"
  | "medusa"
  | "calling_tool"
  | "generating"
  | "streaming"
  | "persisting"
  | "finalizing"
  | "complete"
  | "error"
  | "degraded";

export type ChatStreamingPhase =
  | "idle"
  | "connecting"
  | "connected"
  | "receiving"
  | "reconnecting"
  | "complete"
  | "error";

export type ChatProcessingDisplay = {
  label: string;
  description: string;
  icon: ReactNode;
  toneClassName: string;
  isBusy: boolean;
};

export type ChatStreamingDisplay = {
  label: string;
  description: string;
  icon: ReactNode;
  toneClassName: string;
  isActive: boolean;
};

export type ProcessingStageProgress = {
  status: ProcessingStatusKey | null;
  state: ChatProcessingState;
  currentStep: number;
  totalSteps: number;
  percent: number;
  isTerminal: boolean;
};

export type ProcessingResolvedStatus = {
  status: ProcessingStatusKey | null;
  state: ChatProcessingState;
  message: string;
  display: ChatProcessingDisplay;
  progress: ProcessingStageProgress;
  elapsedLabel: string | null;
  isStalled: boolean;
  isLongRunning: boolean;
  stalledMessage: string | null;
};

export const PROCESSING_STATE_LABELS: Record<ChatProcessingState, string> = {
  idle: "Ready",
  queued: "Queued",
  preparing: "Analyzing your request",
  authenticating: "Checking access",
  context: "Building execution context",
  cortex: "Planning response strategy",
  retrieving_memory: "Retrieving memory",
  routing: "Selecting tools and providers",
  deep_reasoning: "Deep reasoning",
  medusa: "Specialist agents",
  calling_tool: "Using tools",
  generating: "Generating response",
  streaming: "Streaming",
  persisting: "Saving useful context...",
  finalizing: "Checking response quality...",
  complete: "Complete",
  error: "Error",
  degraded: "Degraded",
};

export const PROCESSING_STATE_DESCRIPTIONS: Record<ChatProcessingState, string> = {
  idle: "Karen is ready for the next message.",
  queued: "Your request is waiting for the runtime.",
  preparing: "Karen is analyzing intent, constraints, and requested output format.",
  authenticating: "Karen is verifying session, tenant, and RBAC context.",
  context: "Karen is assembling tenant/session context and required runtime inputs.",
  cortex: "Karen is selecting the best reasoning path for this request.",
  retrieving_memory: "Karen is querying memory stores and ranking relevant context.",
  routing: "Karen is selecting tools, providers, and safe fallbacks.",
  deep_reasoning: "Karen is running the deep reasoning workflow.",
  medusa: "Karen is coordinating specialist agents.",
  calling_tool: "Karen is executing approved tools, plugins, or MCP calls.",
  generating: "Karen is drafting your response with the selected runtime.",
  streaming: "Karen is receiving response tokens.",
  persisting: "Saving useful context...",
  finalizing: "Checking response quality...",
  complete: "The response completed successfully.",
  error: "The request failed before a complete response was produced.",
  degraded: "Karen continued through a backend-reported degraded runtime path.",
};

export const STREAMING_PHASE_LABELS: Record<ChatStreamingPhase, string> = {
  idle: "Idle",
  connecting: "Connecting",
  connected: "Connected",
  receiving: "Receiving",
  reconnecting: "Reconnecting",
  complete: "Complete",
  error: "Stream error",
};

export const STREAMING_PHASE_DESCRIPTIONS: Record<ChatStreamingPhase, string> = {
  idle: "No active stream.",
  connecting: "Opening the chat stream.",
  connected: "The stream is connected.",
  receiving: "Receiving response tokens.",
  reconnecting: "Attempting to reconnect the stream.",
  complete: "The stream completed.",
  error: "The stream failed.",
};

export const BUSY_PROCESSING_STATES = new Set<ChatProcessingState>([
  "queued",
  "preparing",
  "authenticating",
  "context",
  "cortex",
  "retrieving_memory",
  "routing",
  "deep_reasoning",
  "medusa",
  "calling_tool",
  "generating",
  "streaming",
  "persisting",
  "finalizing",
]);

export const ACTIVE_STREAMING_PHASES = new Set<ChatStreamingPhase>([
  "connecting",
  "connected",
  "receiving",
  "reconnecting",
]);

export const TERMINAL_PROCESSING_STATUSES = new Set<ProcessingStatusKey>([
  "completed",
  "failed",
  "cancelled",
]);

export const PROCESSING_STAGE_ORDER: ProcessingStatusKey[] = [
  "request_received",
  "runtime_mode_check",
  "auth_context_resolved",
  "session_loaded",
  "conversation_loaded",
  "context_assembly",
  "cortex_start",
  "cortex_complete",
  "memory_recall_start",
  "memory_recall_complete",
  "capsule_recall_start",
  "capsule_recall_complete",
  "provider_selection_start",
  "provider_selected",
  "fallback_started",
  "fallback_succeeded",
  "langgraph_start",
  "langgraph_node",
  "medusa_start",
  "medusa_specialist_start",
  "tool_call_start",
  "tool_call_complete",
  "generation_start",
  "response_started",
  "streaming_tokens",
  "post_processing",
  "persistence_start",
  "persistence_complete",
  "memory_writeback_start",
  "memory_writeback_complete",
  "completed",
];

export const PROCESSING_STATUS_ALIASES: Record<string, ProcessingStatusKey> = {
  init: "request_received",
  initializing: "request_received",
  initialized: "request_received",
  request_started: "request_received",
  request_received: "request_received",
  queued: "request_received",
  preparing: "request_received",
  processing: "context_assembly",

  runtime: "runtime_mode_check",
  runtime_check: "runtime_mode_check",
  runtime_mode: "runtime_mode_check",
  runtime_mode_check: "runtime_mode_check",
  maintenance_check: "runtime_mode_check",
  degraded_check: "runtime_mode_check",

  auth: "auth_context_resolved",
  auth_gate: "auth_context_resolved",
  authenticated: "auth_context_resolved",
  authentication: "auth_context_resolved",
  authorization: "auth_context_resolved",
  rbac: "auth_context_resolved",
  tenant_context: "auth_context_resolved",

  session: "session_loaded",
  session_loaded: "session_loaded",
  session_state: "session_loaded",

  conversation: "conversation_loaded",
  conversation_loaded: "conversation_loaded",
  conversation_state: "conversation_loaded",
  thread_loaded: "conversation_loaded",

  context: "context_assembly",
  context_retrieval: "context_assembly",
  context_assembly_started: "context_assembly",
  context_assembly: "context_assembly",
  context_loaded: "context_assembly",
  extracting_context: "context_assembly",
  prompt_context: "context_assembly",

  cortex: "cortex_start",
  cortex_start: "cortex_start",
  cortex_started: "cortex_start",
  intent: "cortex_start",
  intent_detect: "cortex_start",
  intent_detection: "cortex_start",
  routing_intent: "cortex_complete",
  cortex_decision: "cortex_complete",
  cortex_complete: "cortex_complete",
  intent_complete: "cortex_complete",

  memory: "memory_recall_start",
  memory_fetch: "memory_recall_start",
  memory_recall: "memory_recall_start",
  memory_recall_started: "memory_recall_start",
  recalling_memory: "memory_recall_start",
  retrieving_memory: "memory_recall_start",
  memory_complete: "memory_recall_complete",
  memory_recall_complete: "memory_recall_complete",
  memory_recall_done: "memory_recall_complete",

  capsule: "capsule_recall_start",
  capsules: "capsule_recall_start",
  capsule_recall: "capsule_recall_start",
  capsule_recall_start: "capsule_recall_start",
  capsule_complete: "capsule_recall_complete",
  capsule_recall_complete: "capsule_recall_complete",

  provider_selection: "provider_selection_start",
  provider_selection_start: "provider_selection_start",
  provider_check: "provider_selection_start",
  selecting_provider: "provider_selection_start",
  router_select: "provider_selection_start",
  routing: "provider_selection_start",
  model_selection: "provider_selection_start",

  provider_ready: "provider_selected",
  provider_live: "provider_selected",
  selected_provider: "provider_selected",
  provider_selected: "provider_selected",
  model_selected: "provider_selected",

  unavailable: "provider_unavailable",
  provider_unavailable: "provider_unavailable",
  provider_error: "provider_failed",
  provider_failure: "provider_failed",
  provider_failed: "provider_failed",
  provider_timeout: "provider_failed",

  retry_provider: "provider_retry",
  provider_retry: "provider_retry",
  provider_retrying: "provider_retry",
  retry: "provider_retry",
  retrying: "provider_retry",

  fallback: "fallback_started",
  fallback_start: "fallback_started",
  fallback_started: "fallback_started",
  fallback_attempt: "fallback_started",
  fallback_success: "fallback_succeeded",
  fallback_succeeded: "fallback_succeeded",
  fallback_ready: "fallback_succeeded",
  fallback_live: "fallback_succeeded",

  langgraph: "langgraph_start",
  langgraph_start: "langgraph_start",
  deep_reasoning: "langgraph_start",
  graph_start: "langgraph_start",
  graph_node: "langgraph_node",
  langgraph_node: "langgraph_node",
  reasoning: "langgraph_node",

  medusa: "medusa_start",
  medusa_start: "medusa_start",
  agent_medusa: "medusa_start",
  specialist: "medusa_specialist_start",
  specialist_agent: "medusa_specialist_start",
  medusa_specialist: "medusa_specialist_start",

  tools: "tool_call_start",
  tool: "tool_call_start",
  tool_call: "tool_call_start",
  tool_call_start: "tool_call_start",
  tool_exec: "tool_call_start",
  plugin: "tool_call_start",
  plugin_call: "tool_call_start",
  mcp: "tool_call_start",
  mcp_call: "tool_call_start",
  tool_complete: "tool_call_complete",
  tool_call_complete: "tool_call_complete",
  plugin_complete: "tool_call_complete",

  generating: "generation_start",
  generation: "generation_start",
  generation_start: "generation_start",
  generation_started: "generation_start",
  response_start: "response_started",
  response_started: "response_started",

  stream: "streaming_tokens",
  streaming: "streaming_tokens",
  token_stream: "streaming_tokens",
  streaming_tokens: "streaming_tokens",
  tokens: "streaming_tokens",
  receiving_tokens: "streaming_tokens",

  saving: "persistence_start",
  persistence: "persistence_start",
  persisting: "persistence_start",
  persistence_start: "persistence_start",
  persistence_complete: "persistence_complete",
  persisted: "persistence_complete",

  memory_write: "memory_writeback_start",
  memory_writeback: "memory_writeback_start",
  memory_writeback_start: "memory_writeback_start",
  memory_write_complete: "memory_writeback_complete",
  memory_writeback_complete: "memory_writeback_complete",

  finalizing: "post_processing",
  finalising: "post_processing",
  postprocess: "post_processing",
  post_processing: "post_processing",
  post_processing_started: "post_processing",
  response_sanitize: "post_processing",
  formatting: "post_processing",

  degraded_mode: "degraded",
  degraded: "degraded",
  degraded_provider: "degraded_live",
  live_degraded: "degraded_live",
  degraded_live: "degraded_live",

  static_fallback: "emergency_static",
  emergency: "emergency_static",
  emergency_unavailable: "emergency_static",
  emergency_static_response: "emergency_static",
  emergency_static: "emergency_static",

  done: "completed",
  complete: "completed",
  completed: "completed",
  success: "completed",
  finished: "completed",

  error: "failed",
  failed: "failed",
  failed_request: "failed",
  failure: "failed",

  cancel: "cancelled",
  canceled: "cancelled",
  cancelled: "cancelled",
};

const STATUS_TO_STATE: Record<ProcessingStatusKey, ChatProcessingState> = {
  request_received: "preparing",
  runtime_mode_check: "preparing",
  auth_context_resolved: "authenticating",
  session_loaded: "preparing",
  conversation_loaded: "preparing",
  context_assembly: "context",
  cortex_start: "cortex",
  cortex_complete: "cortex",
  memory_recall_start: "retrieving_memory",
  memory_recall_complete: "retrieving_memory",
  capsule_recall_start: "retrieving_memory",
  capsule_recall_complete: "retrieving_memory",
  provider_selection_start: "routing",
  provider_selected: "routing",
  provider_unavailable: "routing",
  provider_failed: "routing",
  provider_retry: "routing",
  fallback_started: "degraded",
  fallback_succeeded: "degraded",
  langgraph_start: "deep_reasoning",
  langgraph_node: "deep_reasoning",
  medusa_start: "medusa",
  medusa_specialist_start: "medusa",
  tool_call_start: "calling_tool",
  tool_call_complete: "calling_tool",
  generation_start: "generating",
  response_started: "generating",
  streaming_tokens: "streaming",
  persistence_start: "persisting",
  persistence_complete: "persisting",
  memory_writeback_start: "persisting",
  memory_writeback_complete: "persisting",
  post_processing: "finalizing",
  completed: "complete",
  failed: "error",
  cancelled: "complete",
  degraded: "degraded",
  degraded_live: "degraded",
  emergency_static: "degraded",
};

const PROCESSING_STATUS_SET = new Set<ProcessingStatusKey>([
  "request_received",
  "runtime_mode_check",
  "auth_context_resolved",
  "session_loaded",
  "conversation_loaded",
  "context_assembly",
  "cortex_start",
  "cortex_complete",
  "memory_recall_start",
  "memory_recall_complete",
  "capsule_recall_start",
  "capsule_recall_complete",
  "provider_selection_start",
  "provider_selected",
  "provider_unavailable",
  "provider_failed",
  "provider_retry",
  "fallback_started",
  "fallback_succeeded",
  "langgraph_start",
  "langgraph_node",
  "medusa_start",
  "medusa_specialist_start",
  "tool_call_start",
  "tool_call_complete",
  "generation_start",
  "response_started",
  "streaming_tokens",
  "persistence_start",
  "persistence_complete",
  "memory_writeback_start",
  "memory_writeback_complete",
  "post_processing",
  "completed",
  "failed",
  "cancelled",
  "degraded",
  "degraded_live",
  "emergency_static",
]);

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
};

const toCleanString = (value: unknown): string => {
  return typeof value === "string" ? value.trim() : String(value ?? "").trim();
};

const toFiniteNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

const toDisplayWords = (value: string): string => {
  return value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
};

const capitalizeWords = (value: string): string => {
  return toDisplayWords(value).replace(/\b[a-z]/g, (char) => char.toUpperCase());
};

const normalizeKey = (value: string): string => {
  return value.trim().toLowerCase().replace(/[\s-]+/g, "_");
};

export const normalizeProcessingStatusKey = (status: unknown): string => {
  if (status == null) {
    return "";
  }

  if (typeof status === "string") {
    return normalizeKey(status);
  }

  if (isRecord(status)) {
    const preferred =
      status.value ??
      status.status ??
      status.event_type ??
      status.eventType ??
      status.phase ??
      status.stage ??
      status.state ??
      status.type ??
      status.node ??
      status.message;

    if (typeof preferred === "string") {
      return normalizeKey(preferred);
    }
  }

  return normalizeKey(String(status));
};

const isProcessingStatusKey = (key: string): key is ProcessingStatusKey => {
  return PROCESSING_STATUS_SET.has(key as ProcessingStatusKey);
};

export const normalizeProcessingStatus = (status: unknown): ProcessingStatusKey | null => {
  const key = normalizeProcessingStatusKey(status);

  if (!key) {
    return null;
  }

  if (isProcessingStatusKey(key)) {
    return key;
  }

  if (key in PROCESSING_STATUS_ALIASES) {
    return PROCESSING_STATUS_ALIASES[key];
  }

  if (key.includes("runtime") && (key.includes("mode") || key.includes("health"))) {
    return "runtime_mode_check";
  }

  if (key.includes("auth") || key.includes("rbac") || key.includes("tenant")) {
    return "auth_context_resolved";
  }

  if (key.includes("session")) {
    return "session_loaded";
  }

  if (key.includes("conversation") || key.includes("thread")) {
    return "conversation_loaded";
  }

  if (key.includes("context") || key.includes("prompt")) {
    return "context_assembly";
  }

  if (key.includes("cortex") || key.includes("intent")) {
    return key.includes("complete") || key.includes("decision")
      ? "cortex_complete"
      : "cortex_start";
  }

  if (key.includes("memory") || key.includes("recall")) {
    if (key.includes("write")) {
      return key.includes("complete") || key.includes("done")
        ? "memory_writeback_complete"
        : "memory_writeback_start";
    }

    return key.includes("complete") || key.includes("done")
      ? "memory_recall_complete"
      : "memory_recall_start";
  }

  if (key.includes("capsule")) {
    return key.includes("complete") || key.includes("done")
      ? "capsule_recall_complete"
      : "capsule_recall_start";
  }

  if (key.includes("langgraph") || key.includes("graph") || key.includes("reasoning")) {
    return key.includes("node") || key.includes("step") ? "langgraph_node" : "langgraph_start";
  }

  if (key.includes("medusa") || key.includes("specialist")) {
    return key.includes("specialist") ? "medusa_specialist_start" : "medusa_start";
  }

  if (key.includes("tool") || key.includes("plugin") || key.includes("mcp")) {
    return key.includes("complete") || key.includes("done")
      ? "tool_call_complete"
      : "tool_call_start";
  }

  if (key.includes("fallback") && (key.includes("success") || key.includes("live") || key.includes("ready"))) {
    return "fallback_succeeded";
  }

  if (key.includes("fallback")) {
    return "fallback_started";
  }

  if (key.includes("provider") && key.includes("retry")) {
    return "provider_retry";
  }

  if (
    key.includes("provider") &&
    (key.includes("fail") || key.includes("error") || key.includes("timeout"))
  ) {
    return "provider_failed";
  }

  if (key.includes("provider") && key.includes("unavailable")) {
    return "provider_unavailable";
  }

  if (key.includes("provider") || key.includes("router") || key.includes("model_selection")) {
    return "provider_selection_start";
  }

  if (key.includes("stream") || key.includes("token")) {
    return "streaming_tokens";
  }

  if (key.includes("persist") || key.includes("save")) {
    return key.includes("complete") || key.includes("done")
      ? "persistence_complete"
      : "persistence_start";
  }

  if (key.includes("sanitize") || key.includes("format") || key.includes("post")) {
    return "post_processing";
  }

  if (key.includes("generat")) {
    return "generation_start";
  }

  if (key.includes("degraded") && key.includes("live")) {
    return "degraded_live";
  }

  if (key.includes("degraded")) {
    return "degraded";
  }

  if (key.includes("emergency") || key.includes("static")) {
    return "emergency_static";
  }

  if (key.includes("complete") || key.includes("done") || key.includes("success")) {
    return "completed";
  }

  if (key.includes("cancel")) {
    return "cancelled";
  }

  if (key.includes("error") || key.includes("fail")) {
    return "failed";
  }

  return null;
};

const getRuntimeMetadata = (context?: ProcessingRuntimeMetadata): ProcessingRuntimeMetadata => {
  if (!context || !isRecord(context)) {
    return {};
  }

  const metadata = isRecord(context.metadata) ? context.metadata : {};
  const runtime = isRecord(context.runtime) ? context.runtime : {};
  const llm = isRecord(context.llm) ? context.llm : {};

  return {
    ...context,
    ...metadata,
    ...runtime,
    ...llm,
  };
};

const formatProviderLabel = (provider: unknown): string => {
  const raw = toCleanString(provider);

  if (!raw) {
    return "";
  }

  const normalized = normalizeProcessingStatusKey(raw);

  if (normalized === "builtin_vllm" || normalized === "vllm") {
    return "vLLM";
  }

  if (normalized === "builtin_transformers" || normalized === "transformers") {
    return "Transformers";
  }

  if (normalized === "ollama") {
    return "Ollama";
  }

  if (normalized === "openai") {
    return "OpenAI";
  }

  if (normalized === "openai_compatible") {
    return "OpenAI-compatible provider";
  }

  if (normalized === "gemini") {
    return "Gemini";
  }

  if (normalized === "anthropic") {
    return "Anthropic";
  }

  if (normalized === "deepseek") {
    return "DeepSeek";
  }

  if (normalized === "zai" || normalized === "z_ai") {
    return "Z.AI";
  }

  if (normalized === "emergency_static") {
    return "emergency unavailable-response path";
  }

  return capitalizeWords(normalized);
};

const formatModelLabel = (model: unknown): string => {
  return toCleanString(model);
};

const formatProviderModel = (provider: unknown, model: unknown): string => {
  const providerLabel = formatProviderLabel(provider);
  const modelLabel = formatModelLabel(model);

  if (providerLabel && modelLabel) {
    return `${providerLabel}/${modelLabel}`;
  }

  return providerLabel || modelLabel;
};

const formatCount = (value: unknown): string => {
  const count = toFiniteNumber(value);

  if (count == null) {
    return "";
  }

  return Math.max(0, Math.floor(count)).toLocaleString();
};

export const formatElapsedMs = (value: unknown): string | null => {
  const ms = toFiniteNumber(value);

  if (ms == null || ms < 0) {
    return null;
  }

  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }

  const seconds = ms / 1000;

  if (seconds < 60) {
    return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`;
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);

  return `${minutes}m ${remainingSeconds}s`;
};

const timestampToMs = (value: unknown): number | null => {
  if (value instanceof Date) {
    const time = value.getTime();
    return Number.isFinite(time) ? time : null;
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 10_000_000_000 ? value : value * 1000;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

export const getElapsedMs = (
  context?: ProcessingRuntimeMetadata,
  nowMs: number = Date.now(),
): number | null => {
  const runtime = getRuntimeMetadata(context);
  const explicitElapsed = toFiniteNumber(runtime.elapsed_ms ?? runtime.latency_ms);

  if (explicitElapsed != null) {
    return explicitElapsed;
  }

  const startedAt = timestampToMs(runtime.started_at);
  if (startedAt == null) {
    return null;
  }

  return Math.max(0, nowMs - startedAt);
};

export const getProcessingStageProgress = (
  status: unknown,
): ProcessingStageProgress => {
  const normalized = normalizeProcessingStatus(status);
  const state = normalizeProcessingState(normalized || status);
  const totalSteps = PROCESSING_STAGE_ORDER.length;
  const index = normalized ? PROCESSING_STAGE_ORDER.indexOf(normalized) : -1;
  const currentStep = index >= 0 ? index + 1 : state === "idle" ? 0 : 1;
  const isTerminal = normalized ? TERMINAL_PROCESSING_STATUSES.has(normalized) : false;

  return {
    status: normalized,
    state,
    currentStep,
    totalSteps,
    percent:
      isTerminal && normalized === "completed"
        ? 100
        : Math.max(0, Math.min(99, Math.round((currentStep / totalSteps) * 100))),
    isTerminal,
  };
};

export function normalizeProcessingState(
  state: unknown,
): ChatProcessingState {
  const normalized = normalizeProcessingStatusKey(state || "idle");

  if (normalized in PROCESSING_STATE_LABELS) {
    return normalized as ChatProcessingState;
  }

  const status = normalizeProcessingStatus(normalized);
  if (status) {
    return STATUS_TO_STATE[status];
  }

  return "idle";
}

export function normalizeStreamingPhase(
  phase: ChatStreamingPhase | string | null | undefined,
): ChatStreamingPhase {
  const normalized = normalizeProcessingStatusKey(phase || "idle");

  if (normalized in STREAMING_PHASE_LABELS) {
    return normalized as ChatStreamingPhase;
  }

  if (normalized.includes("connect") && normalized.includes("re")) {
    return "reconnecting";
  }

  if (normalized.includes("connect")) {
    return "connecting";
  }

  if (normalized.includes("receive") || normalized.includes("stream") || normalized.includes("token")) {
    return "receiving";
  }

  if (normalized.includes("complete") || normalized.includes("done") || normalized.includes("success")) {
    return "complete";
  }

  if (normalized.includes("error") || normalized.includes("fail")) {
    return "error";
  }

  return "idle";
}

export function isBusyProcessingState(
  state: ChatProcessingState | ProcessingStatusKey | string | null | undefined,
): boolean {
  return BUSY_PROCESSING_STATES.has(normalizeProcessingState(state));
}

export function isActiveStreamingPhase(
  phase: ChatStreamingPhase | string | null | undefined,
): boolean {
  return ACTIVE_STREAMING_PHASES.has(normalizeStreamingPhase(phase));
}

export function getProcessingIcon(state: ChatProcessingState): ReactNode {
  switch (state) {
    case "queued":
      return <Clock className="h-3.5 w-3.5" />;
    case "preparing":
      return <Wrench className="h-3.5 w-3.5" />;
    case "authenticating":
      return <ShieldCheck className="h-3.5 w-3.5" />;
    case "context":
      return <Sparkles className="h-3.5 w-3.5" />;
    case "cortex":
      return <BrainCircuit className="h-3.5 w-3.5" />;
    case "retrieving_memory":
      return <Database className="h-3.5 w-3.5" />;
    case "routing":
      return <RadioTower className="h-3.5 w-3.5" />;
    case "deep_reasoning":
      return <Route className="h-3.5 w-3.5" />;
    case "medusa":
      return <Split className="h-3.5 w-3.5" />;
    case "calling_tool":
      return <Zap className="h-3.5 w-3.5" />;
    case "generating":
    case "streaming":
    case "finalizing":
      return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    case "persisting":
      return <Save className="h-3.5 w-3.5" />;
    case "complete":
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case "error":
    case "degraded":
      return <AlertCircle className="h-3.5 w-3.5" />;
    case "idle":
    default:
      return <Bot className="h-3.5 w-3.5" />;
  }
}

export function getStreamingIcon(phase: ChatStreamingPhase): ReactNode {
  switch (phase) {
    case "connecting":
    case "connected":
    case "receiving":
    case "reconnecting":
      return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    case "complete":
      return <CheckCircle2 className="h-3.5 w-3.5" />;
    case "error":
      return <AlertCircle className="h-3.5 w-3.5" />;
    case "idle":
    default:
      return <Bot className="h-3.5 w-3.5" />;
  }
}

export function getProcessingToneClassName(state: ChatProcessingState): string {
  switch (state) {
    case "error":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    case "degraded":
      return "border-yellow-500/30 bg-yellow-500/10 text-yellow-700 dark:text-yellow-300";
    case "complete":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "idle":
      return "border-border bg-muted/40 text-muted-foreground";
    default:
      return "border-primary/30 bg-primary/10 text-primary";
  }
}

export function getStreamingToneClassName(phase: ChatStreamingPhase): string {
  switch (phase) {
    case "error":
      return "border-destructive/30 bg-destructive/10 text-destructive";
    case "complete":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "idle":
      return "border-border bg-muted/40 text-muted-foreground";
    default:
      return "border-primary/30 bg-primary/10 text-primary";
  }
}

export function getProcessingDisplay(
  state: ChatProcessingState | ProcessingStatusKey | string | null | undefined,
): ChatProcessingDisplay {
  const normalized = normalizeProcessingState(state);

  return {
    label: PROCESSING_STATE_LABELS[normalized],
    description: PROCESSING_STATE_DESCRIPTIONS[normalized],
    icon: getProcessingIcon(normalized),
    toneClassName: getProcessingToneClassName(normalized),
    isBusy: BUSY_PROCESSING_STATES.has(normalized),
  };
}

export function getStreamingDisplay(
  phase: ChatStreamingPhase | string | null | undefined,
): ChatStreamingDisplay {
  const normalized = normalizeStreamingPhase(phase);

  return {
    label: STREAMING_PHASE_LABELS[normalized],
    description: STREAMING_PHASE_DESCRIPTIONS[normalized],
    icon: getStreamingIcon(normalized),
    toneClassName: getStreamingToneClassName(normalized),
    isActive: ACTIVE_STREAMING_PHASES.has(normalized),
  };
}

export const getProcessingStatusVariantMessages = (
  status: unknown,
  context?: ProcessingRuntimeMetadata,
): string[] => {
  const normalized = normalizeProcessingStatus(status);

  if (!normalized) {
    return [];
  }

  return [resolveProcessingStatusMessage(normalized, undefined, context)];
};

export const getProcessingStatusMessageVariant = (
  status: unknown,
  variantIndex = 0,
  context?: ProcessingRuntimeMetadata,
): string | null => {
  const messages = getProcessingStatusVariantMessages(status, context);

  if (messages.length === 0) {
    return null;
  }

  const safeIndex = Math.abs(Math.trunc(variantIndex)) % messages.length;
  return messages[safeIndex];
};

const buildStalledMessage = (
  status: ProcessingStatusKey | null,
  context?: ProcessingRuntimeMetadata,
): string | null => {
  if (!status || TERMINAL_PROCESSING_STATUSES.has(status)) {
    return null;
  }

  const runtime = getRuntimeMetadata(context);
  const actualRuntime = formatProviderModel(
    runtime.actual_provider ?? runtime.provider,
    runtime.actual_model ?? runtime.model ?? runtime.model_id ?? runtime.model_name,
  );

  switch (status) {
    case "provider_selection_start":
      return "Provider selection is taking longer than expected. Karen is still checking availability and fallback policy.";
    case "provider_unavailable":
    case "provider_failed":
    case "fallback_started":
      return "Fallback recovery is taking longer than expected. Karen is still looking for a live runtime path.";
    case "generation_start":
    case "response_started":
    case "streaming_tokens":
      return actualRuntime
        ? `${actualRuntime} is still generating. Large local models can take longer on CPU or cold GPU starts.`
        : "The selected model is still generating. Local model starts can take longer than cloud calls.";
    case "memory_recall_start":
      return "Memory recall is taking longer than expected. Karen is waiting on the memory backend.";
    case "persistence_start":
    case "memory_writeback_start":
      return "Saving is taking longer than expected. Karen is waiting on persistence/writeback services.";
    case "langgraph_start":
    case "langgraph_node":
      return "Deep reasoning is still running. Karen is processing a multi-step workflow.";
    case "tool_call_start":
      return "The tool call is still running. Karen is waiting for the tool result.";
    default:
      return "This stage is taking longer than expected, but the request is still active.";
  }
};

export const resolveProcessingStatusMessage = (
  status: unknown,
  fallbackMessage?: string,
  context?: ProcessingRuntimeMetadata,
): string => {
  const runtime = getRuntimeMetadata(context);
  const normalized = normalizeProcessingStatus(
    status ??
      runtime.status ??
      runtime.stage ??
      runtime.event_type ??
      runtime.eventType ??
      runtime.phase ??
      runtime.state,
  );

  if (typeof runtime.message === "string" && runtime.message.trim()) {
    return runtime.message.trim();
  }

  if (!normalized) {
    return fallbackMessage?.trim() || DEFAULT_PROCESSING_MESSAGE;
  }

  const requestedRuntime = formatProviderModel(
    runtime.requested_provider ?? runtime.provider,
    runtime.requested_model ?? runtime.model ?? runtime.model_id ?? runtime.model_name,
  );

  const actualRuntime = formatProviderModel(
    runtime.actual_provider ?? runtime.provider,
    runtime.actual_model ?? runtime.model ?? runtime.model_id ?? runtime.model_name,
  );

  const fallbackNext = formatProviderLabel(runtime.fallback_next);
  const memoryCount = formatCount(runtime.memory_recall_count);
  const capsuleCount = formatCount(runtime.capsule_count);
  const toolCount = formatCount(runtime.tool_count);
  const toolName =
    toCleanString(runtime.tool_name) ||
    toCleanString(runtime.plugin_name) ||
    toCleanString(runtime.mcp_server) ||
    "approved tool";
  const specialist = toCleanString(runtime.specialist) || "specialist agent";
  const node = toCleanString(runtime.node || runtime.stage);
  const intent = toCleanString(runtime.intent);
  const reason = toCleanString(runtime.degradation_reason);
  const fallbackLevel = toFiniteNumber(runtime.fallback_level);

  switch (normalized) {
    case "request_received":
      return "Received your message and opened a traced runtime request.";
    case "runtime_mode_check":
      return "Checking runtime mode, maintenance state, and degraded capability flags.";
    case "auth_context_resolved":
      return "Verified session, tenant, and permission context.";
    case "session_loaded":
      return "Loaded session state for this conversation.";
    case "conversation_loaded":
      return "Loaded conversation history and thread context.";
    case "context_assembly":
      return "Assembling profile, conversation, files, and prompt context.";
    case "cortex_start":
      return "Running CORTEX intent classification and policy routing.";
    case "cortex_complete":
      return intent
        ? `CORTEX classified the request as ${capitalizeWords(intent)} and selected routing policy.`
        : "CORTEX finished routing intent, memory strategy, and tool eligibility.";
    case "memory_recall_start":
      return "Retrieving governed short-term, episodic, and long-term memory.";
    case "memory_recall_complete":
      return memoryCount
        ? `Memory recall complete. Retrieved ${memoryCount} relevant item(s).`
        : "Memory recall complete. No relevant memory was added.";
    case "capsule_recall_start":
      return "Checking capsules for governed context packets.";
    case "capsule_recall_complete":
      return capsuleCount
        ? `Capsule recall complete. Added ${capsuleCount} capsule(s).`
        : "Capsule recall complete. No capsules were needed.";
    case "provider_selection_start":
      return requestedRuntime
        ? `Checking requested runtime ${requestedRuntime}.`
        : "Selecting an available provider and model.";
    case "provider_selected":
      return actualRuntime
        ? `Selected ${actualRuntime} for this response.`
        : "Selected a live provider for this response.";
    case "provider_unavailable":
      return requestedRuntime
        ? `${requestedRuntime} is unavailable. Checking fallback options.`
        : "Requested provider is unavailable. Checking fallback options.";
    case "provider_failed":
      return requestedRuntime
        ? `${requestedRuntime} failed during generation. Preparing recovery path.`
        : "The selected provider failed during generation. Preparing recovery path.";
    case "provider_retry":
      return requestedRuntime
        ? `Retrying ${requestedRuntime}.`
        : "Retrying the provider request.";
    case "fallback_started":
      if (fallbackNext && fallbackLevel != null) {
        return `Trying fallback level ${fallbackLevel}: ${fallbackNext}.`;
      }

      return fallbackNext
        ? `Trying fallback provider ${fallbackNext}.`
        : "Trying the next backend-approved fallback provider.";
    case "fallback_succeeded":
      return actualRuntime
        ? `Recovered through ${actualRuntime}.`
        : "Recovered through a live fallback provider.";
    case "langgraph_start":
      return "Starting LangGraph deep reasoning workflow.";
    case "langgraph_node":
      return node
        ? `LangGraph is running node: ${capitalizeWords(node)}.`
        : "LangGraph is running the next reasoning node.";
    case "medusa_start":
      return "Starting Medusa specialist arbitration.";
    case "medusa_specialist_start":
      return `Medusa is consulting ${capitalizeWords(specialist)}.`;
    case "tool_call_start":
      return toolCount
        ? `Calling ${capitalizeWords(toolName)} with ${toolCount} approved tool action(s).`
        : `Calling ${capitalizeWords(toolName)}.`;
    case "tool_call_complete":
      return `${capitalizeWords(toolName)} finished.`;
    case "generation_start":
      return actualRuntime
        ? `${actualRuntime} is generating the answer.`
        : "The selected model is generating the answer.";
    case "response_started":
      return actualRuntime
        ? `${actualRuntime} started responding.`
        : "The response stream has started.";
    case "streaming_tokens":
      return "Receiving response tokens.";
    case "persistence_start":
      return "Saving conversation, runtime metadata, and audit trail.";
    case "persistence_complete":
      return "Conversation and runtime metadata saved.";
    case "memory_writeback_start":
      return "Evaluating approved memory candidates for writeback.";
    case "memory_writeback_complete":
      return "Memory writeback completed.";
    case "post_processing":
      return "Sanitizing output and preparing final response metadata.";
    case "degraded":
      return reason
        ? `Running in degraded mode: ${toDisplayWords(reason)}.`
        : "Running in degraded mode with limited capabilities.";
    case "degraded_live":
      return actualRuntime
        ? `Using degraded live path through ${actualRuntime}.`
        : "Using a degraded live runtime path.";
    case "emergency_static":
      return "No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.";
    case "completed":
      return "Response complete.";
    case "failed":
      return "Processing failed before a complete response was produced.";
    case "cancelled":
      return "Request was cancelled.";
    default:
      return fallbackMessage?.trim() || DEFAULT_PROCESSING_MESSAGE;
  }
};

export const resolveProcessingStatus = (
  status: unknown,
  fallbackMessage?: string,
  context?: ProcessingRuntimeMetadata,
  nowMs: number = Date.now(),
): ProcessingResolvedStatus => {
  const runtime = getRuntimeMetadata(context);
  const normalized = normalizeProcessingStatus(
    status ??
      runtime.status ??
      runtime.stage ??
      runtime.event_type ??
      runtime.eventType ??
      runtime.phase ??
      runtime.state,
  );
  const state = normalizeProcessingState(normalized || status);
  const display = getProcessingDisplay(state);
  const elapsedMs = getElapsedMs(runtime, nowMs);
  const elapsedLabel = formatElapsedMs(elapsedMs);
  const isTerminal = normalized ? TERMINAL_PROCESSING_STATUSES.has(normalized) : false;
  const isStalled =
    !isTerminal &&
    elapsedMs != null &&
    elapsedMs >= STALLED_STAGE_THRESHOLD_MS;
  const isLongRunning =
    !isTerminal &&
    elapsedMs != null &&
    elapsedMs >= LONG_RUNNING_STAGE_THRESHOLD_MS;
  const stalledMessage = isStalled ? buildStalledMessage(normalized, runtime) : null;

  return {
    status: normalized,
    state,
    message: stalledMessage || resolveProcessingStatusMessage(status, fallbackMessage, runtime),
    display,
    progress: getProcessingStageProgress(normalized || status),
    elapsedLabel,
    isStalled,
    isLongRunning,
    stalledMessage,
  };
};
