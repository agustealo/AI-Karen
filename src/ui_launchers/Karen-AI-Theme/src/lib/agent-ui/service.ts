import apiClient from '../api';
import { normalizeBackendChatResponse } from '../chat-response';

type BackendExecutionMode = 'native' | 'langgraph' | 'deep_agents';
type BackendAgentStatus =
  | 'initializing'
  | 'idle'
  | 'processing'
  | 'streaming'
  | 'error'
  | 'terminated';

interface BackendAgentInfo {
  agent_id: string;
  name: string;
  description: string;
  execution_mode: BackendExecutionMode;
  status: BackendAgentStatus;
  capabilities: string[];
  config: Record<string, unknown>;
  metrics: Record<string, unknown>;
  created_at: string;
  last_activity?: string | null;
  version: string;
  is_healthy: boolean;
  is_available: boolean;
}

interface BackendAgentExecuteResponse {
  request_id: string;
  agent_id: string;
  execution_mode: BackendExecutionMode;
  response: string;
  processing_time: number;
  metadata: Record<string, unknown>;
  confidence?: number | null;
  warnings: string[];
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  } | null;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  status: 'online' | 'offline' | 'busy';
  avatar?: string;
  capabilities: string[];
  executionMode?: BackendExecutionMode;
  isHealthy?: boolean;
  isAvailable?: boolean;
}

export interface StructuredContent {
  formatting?: Record<string, unknown>;
  layout_type?: string;
  output_profile?: string;
  [key: string]: unknown;
}

export interface SuggestedAction {
  type: string;
  params?: Record<string, string | number | boolean | null | undefined>;
  confidence?: number;
  description?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: number;
  structured_content?: StructuredContent;
  actions?: SuggestedAction[];
  metadata?: Record<string, unknown>;
}

export interface AgentResponse {
  answer: string;
  structured_content: StructuredContent;
  actions: SuggestedAction[];
  metadata: Record<string, unknown>;
  correlation_id: string;
}

function mapBackendStatus(status: BackendAgentStatus, isAvailable: boolean): Agent['status'] {
  if (status === 'processing' || status === 'streaming') {
    return 'busy';
  }
  if (status === 'idle' && isAvailable) {
    return 'online';
  }
  return 'offline';
}

function toAgent(info: BackendAgentInfo): Agent {
  return {
    id: info.agent_id,
    name: info.name,
    description: info.description || `${info.execution_mode} agent`,
    status: mapBackendStatus(info.status, info.is_available),
    capabilities: info.capabilities || [],
    executionMode: info.execution_mode,
    isHealthy: info.is_healthy,
    isAvailable: info.is_available,
  };
}

export class AgentUIService {
  async getAgents(): Promise<Agent[]> {
    const agents = await apiClient.get<BackendAgentInfo[]>('/api/agents/');
    return (agents || []).map(toAgent);
  }

  async sendMessage(
    agentId: string,
    message: string,
    sessionId?: string,
    context?: Record<string, unknown>,
    executionMode: BackendExecutionMode = 'native'
  ): Promise<AgentResponse> {
    const response = await apiClient.post<BackendAgentExecuteResponse>('/api/agents/execute', {
      message,
      execution_mode: executionMode,
      agent_id: agentId,
      session_id: sessionId,
      context: context || {},
      conversation_history: [],
      capabilities_required: [],
      enable_streaming: false,
    });

    if (response.error?.message) {
      throw new Error(response.error.message);
    }

    const normalized = normalizeBackendChatResponse(
      {
        answer: response.response,
        structured_content: {},
        actions: [],
        metadata: response.metadata,
        correlation_id: response.request_id,
        processing_time: response.processing_time,
      },
    );

    return {
      answer: normalized.answer,
      structured_content: normalized.structuredContent,
      actions: normalized.actions.map((action) => ({
        type: action.type,
        params: action.params || {},
        confidence: action.confidence ?? 0.9,
        description: action.description,
      })),
      metadata: {
        ...normalized.metadata,
        execution_mode: response.execution_mode,
        processing_time: response.processing_time,
      },
      correlation_id: normalized.correlationId,
    };
  }
}

export const agentService = new AgentUIService();
export default agentService;
