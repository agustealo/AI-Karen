"use client";

import type { ChatMessage, ConversationResponse, AgentStepEvent, Citation } from '@/lib/types';
import type { SuggestedAction } from '@/lib/agent-ui/service';
import { useState, useRef, useEffect, FormEvent, useCallback, useMemo, createContext, useContext, ReactNode } from 'react';
import { useToast } from "@/hooks/use-toast";
import { ApiError, apiClient } from '@/lib/api';
import { useAuth } from '@/lib/useAuth';
import { authService } from '@/lib/auth';
import {
  normalizeBackendChatResponse,
  normalizeConversationMessage,
} from '@/lib/chat-response';
import {
  normalizeRuntimeProviderCatalogResponse,
  type RuntimeProviderCatalogResponse,
  type NormalizedRuntimeInventory,
} from '@/lib/model-runtime-inventory';
import { useMessageInjection } from '@/providers/MessageInjectionProvider';
// Constants and utilities
import { getStreamingStatus } from './const/getStreamingStatus';
import { getDegradedResponseMessage } from './const/getDegradedResponseMessage';
import {
  DEFAULT_PROCESSING_MESSAGE,
  normalizeProcessingStatusKey,
  resolveProcessingStatus,
  resolveProcessingStatusMessage,
} from './const/processing';
import { getDegradationReasonLabel } from './const/constants';
import { useGreetingSystem } from './const/greetingSystem';
import { useModelSettings } from './const/modelSettings';
import { useRequestHandlers } from './const/requestHandlers';
import { useScrollManagement } from './const/scrollManagement';
import { useUserPreferences } from './const/userPreferences';

// Import interface components
import { StatusIndicators, MessagesArea, ChatInput } from './interface';
import AgentActivityPanel from './AgentActivityPanel';
import ConversationContextRail from './ConversationContextRail';
import DegradedModeBanner from './DegradedModeBanner';
import RuntimeMetadataPanel from './RuntimeMetadataPanel';
import RichResultWorkspace from './RichResultWorkspace';
import CircuitBreakerWarning from './CircuitBreakerWarning';

// Session Management Types
export interface Session {
  id: string;
  title: string;
  createdAt: Date;
  updatedAt: Date;
  messageCount: number;
  isActive: boolean;
  lastMessage?: string;
  runtimeSessionId?: string;
}

interface ChatInterfaceProps {
  isActive?: boolean;
}

interface ActionableApproval {
  approval_id: string;
  conversation_id?: string | null;
  policy_decision_id?: string | null;
  intent: string;
  risk_level: string;
  reason_codes: string[];
  status: string;
  decision_reason?: string | null;
  created_at: string;
  expires_at: string;
  decided_at?: string | null;
  consumed_at?: string | null;
}

interface ConversationApiResponse {
  conversations: Array<{
    id: string;
    title?: string;
    created_at: string;
    updated_at: string;
    message_count?: number;
    messages?: Array<{ content: string }>;
    last_message?: string;
    session_id?: string;
  }>;
  total_count: number;
  has_more: boolean;
}

interface SessionContextType {
  currentSession: Session | null;
  sessions: Session[];
  isLoadingSessions: boolean;
  error: string | null;
  createNewSession: () => Promise<void>;
  loadSession: (sessionId: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
  deleteSession: (sessionId: string) => Promise<boolean | void>;
  deleteSessions: (sessionIds: string[]) => Promise<boolean>;
  updateSessionTitle: (sessionId: string, newTitle: string) => Promise<boolean>;
}

type ModelSettingsResponse = RuntimeProviderCatalogResponse;

const SESSION_BOOTSTRAP_SUPPRESSION_WINDOW_MS = 1500;

type ConversationBootstrapCacheEntry = {
  response: ConversationResponse;
  expiresAt: number;
};

const sessionConversationBootstrapCache = new Map<string, ConversationBootstrapCacheEntry>();
const sessionConversationBootstrapRequests = new Map<string, Promise<ConversationResponse>>();
const recentSessionBootstrapRuns = new Map<string, number>();

/*
 * React Strict Mode and session restore can request the same conversation twice.
 * This short-lived cache deduplicates bootstrap calls without replacing server
 * persistence as the source of truth.
 */
const cacheConversationBootstrap = (sessionId: string, response: ConversationResponse) => {
  sessionConversationBootstrapCache.set(sessionId, {
    response,
    expiresAt: Date.now() + SESSION_BOOTSTRAP_SUPPRESSION_WINDOW_MS,
  });
};

const takeConversationBootstrap = (sessionId: string): ConversationResponse | null => {
  const cached = sessionConversationBootstrapCache.get(sessionId);
  if (!cached) {
    return null;
  }

  if (cached.expiresAt < Date.now()) {
    sessionConversationBootstrapCache.delete(sessionId);
    return null;
  }

  sessionConversationBootstrapCache.delete(sessionId);
  return cached.response;
};

const fetchConversationBootstrap = async (conversationId: string): Promise<ConversationResponse> => {
  const cached = takeConversationBootstrap(conversationId);
  if (cached) {
    return cached;
  }

  const existingRequest = sessionConversationBootstrapRequests.get(conversationId);
  if (existingRequest) {
    return existingRequest;
  }

  const request = apiClient.get<ConversationResponse>(`/api/conversations/${conversationId}`)
    .then((response) => {
      cacheConversationBootstrap(conversationId, response);
      return response;
    })
    .finally(() => {
      if (sessionConversationBootstrapRequests.get(conversationId) === request) {
        sessionConversationBootstrapRequests.delete(conversationId);
      }
    });

  sessionConversationBootstrapRequests.set(conversationId, request);
  return request;
};

const ensureConversationSession = async (sessionId: string): Promise<ConversationResponse> =>
  apiClient.post<ConversationResponse>(`/api/conversations/ensure-session/${sessionId}`);

const shouldSuppressRecentBootstrap = (key: string): boolean => {
  const now = Date.now();
  const lastRunAt = recentSessionBootstrapRuns.get(key);
  if (typeof lastRunAt === 'number' && now - lastRunAt < SESSION_BOOTSTRAP_SUPPRESSION_WINDOW_MS) {
    return true;
  }

  recentSessionBootstrapRuns.set(key, now);
  return false;
};

// Session Context
const SessionContext = createContext<SessionContextType | undefined>(undefined);
const ACTIVE_SESSION_STORAGE_KEY = 'karen.active_session_id';

// Session Management Hook
export function useSession() {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
}

// Session Provider Component
interface SessionProviderProps {
  children: ReactNode;
  initialSessionId?: string;
}

export function SessionProvider({ children, initialSessionId }: SessionProviderProps) {
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const currentSessionRef = useRef<Session | null>(currentSession);
  const sessionsRef = useRef<Session[]>(sessions);
  const sessionListRefreshInFlightRef = useRef<Promise<ConversationApiResponse> | null>(null);

  const persistActiveSessionId = useCallback((sessionId: string | null) => {
    if (typeof window === 'undefined') return;
    try {
      if (sessionId) {
        window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, sessionId);
      } else {
        window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
      }
    } catch {
      // Ignore storage failures.
    }
  }, []);

  useEffect(() => {
    currentSessionRef.current = currentSession;
  }, [currentSession]);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  const getPersistedActiveSessionId = useCallback((): string | null => {
    if (typeof window === 'undefined') return null;
    try {
      const stored = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
      return stored && stored.trim() ? stored.trim() : null;
    } catch {
      return null;
    }
  }, []);

  const getRateLimitDelayMs = useCallback((err: unknown, fallbackMs: number = 1200): number => {
    if (!(err instanceof ApiError)) return fallbackMs;

    const details = (err.details && typeof err.details === 'object')
      ? (err.details as Record<string, unknown>)
      : undefined;

    const numericRetry =
      Number(details?.retry_after_seconds) ||
      Number(details?.retry_after) ||
      Number(details?.retryAfterSeconds) ||
      Number(details?.retryAfter);

    if (Number.isFinite(numericRetry) && numericRetry > 0) {
      return Math.min(15000, Math.max(250, Math.floor(numericRetry * 1000)));
    }

    const retryMatch = /try again in\s+(\d+)\s+seconds?/i.exec(err.message || '');
    if (retryMatch) {
      return Math.min(15000, Math.max(250, parseInt(retryMatch[1], 10) * 1000));
    }

    return fallbackMs;
  }, []);

  // Generate session title from first user message
  const generateSessionTitle = (messages: ChatMessage[]): string => {
    const firstUserMessage = messages.find(msg => msg.role === 'user');
    if (firstUserMessage && firstUserMessage.content.length > 0) {
      const content = firstUserMessage.content.trim();
      return content.length > 50 ? content.substring(0, 50) + '...' : content;
    }
    return 'New Chat';
  };

  // Create a new durable session. The UI does not present a conversation
  // as created until the server has acknowledged the canonical session id.
  const createNewSession = useCallback(async () => {
    const sessionId = createSessionId();
    setIsLoadingSessions(true);
    setError(null);

    try {
      const conversationResponse = await ensureConversationSession(sessionId);
      const conversationId = conversationResponse.id;
      const createdAt = new Date(conversationResponse.created_at || Date.now());
      const updatedAt = new Date(conversationResponse.updated_at || Date.now());
      const newSession: Session = {
        id: conversationId,
        title: conversationResponse.title || 'New Chat',
        createdAt,
        updatedAt,
        messageCount: conversationResponse.messages?.length || 0,
        isActive: true,
        lastMessage:
          conversationResponse.messages?.[conversationResponse.messages.length - 1]?.content,
        runtimeSessionId: conversationResponse.session_id || sessionId,
      };

      setCurrentSession(newSession);
      setSessions((prev) => [
        newSession,
        ...prev
          .filter((session) => session.id !== conversationId)
          .map((session) => ({ ...session, isActive: false })),
      ]);
      persistActiveSessionId(conversationId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        console.warn('New conversation creation was rate-limited; no local-only session was created.');
      } else {
        console.warn('Failed to create durable conversation:', err);
      }
      setError('Unable to create a new chat. No local-only conversation was created.');
      throw err;
    } finally {
      setIsLoadingSessions(false);
    }
  }, [persistActiveSessionId]);

  // Load a specific session
  const loadSession = useCallback(async (sessionId: string) => {
    setIsLoadingSessions(true);
    setError(null);

    try {
      const MAX_ATTEMPTS = 3;
      let conversationResponse: ConversationResponse | null = null;
      let lastError: unknown = null;

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
        try {
          conversationResponse = await fetchConversationBootstrap(sessionId);
          break;
        } catch (err) {
          lastError = err;
          const retryableRateLimit =
            err instanceof ApiError &&
            err.status === 429 &&
            attempt < MAX_ATTEMPTS;

          if (!retryableRateLimit) {
            throw err;
          }

          await new Promise((resolve) =>
            window.setTimeout(resolve, getRateLimitDelayMs(err, 1200)),
          );
        }
      }

      if (!conversationResponse) {
        throw (lastError ?? new Error('Failed to load session'));
      }

      const conversationId = conversationResponse.id;
      const session: Session = {
        id: conversationId,
        title: conversationResponse.title || generateSessionTitle(conversationResponse.messages?.map(m => ({
          ...m,
          role: m.role as 'user' | 'assistant',
          timestamp: new Date(m.timestamp),
          actions: m.actions?.map(a => a as SuggestedAction)
        })) || []),
        createdAt: new Date(conversationResponse.created_at || Date.now()),
        updatedAt: new Date(conversationResponse.updated_at || Date.now()),
        messageCount: conversationResponse.messages?.length || 0,
        isActive: true,
        lastMessage: conversationResponse.messages?.[conversationResponse.messages.length - 1]?.content,
        runtimeSessionId: conversationResponse.session_id || sessionId,
      };

      setCurrentSession(session);
      persistActiveSessionId(conversationId);

      setSessions(prev => prev.map(s => ({
        ...s,
        isActive: s.id === conversationId
      })));
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const existingSession =
          currentSessionRef.current?.id === sessionId
            ? currentSessionRef.current
            : sessionsRef.current.find((session) => session.id === sessionId);

        const preservedSession: Session = existingSession
          ? { ...existingSession, isActive: true }
          : {
              id: sessionId,
              title: 'Current Chat',
              createdAt: new Date(),
              updatedAt: new Date(),
              messageCount: 0,
              isActive: true,
            };

        setCurrentSession(preservedSession);
        setSessions((prev) => {
          const exists = prev.some((session) => session.id === sessionId);
          const next = exists
            ? prev.map((session) => ({
                ...session,
                isActive: session.id === sessionId,
              }))
            : [preservedSession, ...prev.map((session) => ({ ...session, isActive: false }))];
          return next;
        });
        persistActiveSessionId(sessionId);
        setError('Session service is temporarily rate limited. Keeping your current chat available.');
        console.warn('Session load was rate-limited; preserving the requested conversation.');
        return;
      }

      if (err instanceof ApiError && err.status === 404) {
        console.warn('Session was not found on server, starting fresh.');
        setError('Saved session was not found. Starting a fresh chat.');
        try {
          await createNewSession();
        } catch {
          // createNewSession already exposes truthful failure state.
        }
        return;
      }

      console.error('Failed to load session:', err);
      setError('Failed to load session. Starting fresh chat.');
      try {
        await createNewSession();
      } catch {
        // createNewSession already exposes truthful failure state.
      }
    } finally {
      setIsLoadingSessions(false);
    }
  }, [
    createNewSession,
    getRateLimitDelayMs,
    persistActiveSessionId,
  ]);

  // Refresh sessions list
  const refreshSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    setError(null);

    try {
      let request = sessionListRefreshInFlightRef.current;

      if (!request) {
        request = (async (): Promise<ConversationApiResponse> => {
          const MAX_ATTEMPTS = 3;
          let lastError: unknown = null;

          for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
            try {
              return await apiClient.get<ConversationApiResponse>('/api/conversations');
            } catch (err) {
              lastError = err;
              const retryableRateLimit =
                err instanceof ApiError &&
                err.status === 429 &&
                attempt < MAX_ATTEMPTS;

              if (!retryableRateLimit) {
                throw err;
              }

              await new Promise((resolve) =>
                window.setTimeout(resolve, getRateLimitDelayMs(err, 1200)),
              );
            }
          }

          throw (lastError ?? new Error('Failed to fetch sessions'));
        })();

        sessionListRefreshInFlightRef.current = request;
      }

      const response = await request;
      const sessionsData: Session[] = response.conversations?.map((session) => ({
        id: session.id,
        title: session.title || 'Untitled Chat',
        createdAt: new Date(session.created_at),
        updatedAt: new Date(session.updated_at),
        messageCount: session.message_count || 0,
        isActive: currentSessionRef.current?.id === session.id,
        lastMessage: session.messages && session.messages.length > 0
          ? session.messages[session.messages.length - 1].content
          : session.last_message,
        runtimeSessionId: session.session_id || session.id,
      })) || [];

      setSessions(sessionsData);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Session list is temporarily rate limited. Your current chat remains available.');
        console.warn('Session list refresh was rate-limited; preserving existing session state.');
      } else {
        console.error('Failed to load sessions:', err);
        setError('Failed to load sessions list. Some features may be limited.');
      }
    } finally {
      sessionListRefreshInFlightRef.current = null;
      setIsLoadingSessions(false);
    }
  }, [getRateLimitDelayMs]);

  // Sync isActive state whenever currentSession ID changes
  useEffect(() => {
    setSessions(prev => prev.map(s => ({
      ...s,
      isActive: s.id === currentSession?.id
    })));
    // Do not clear persisted session id when currentSession is temporarily null
    // during provider mount/unmount cycles (menu switches, refresh bootstrapping).
    if (currentSession?.id) {
      persistActiveSessionId(currentSession.id);
    }
  }, [currentSession?.id, persistActiveSessionId]);

  // Keep server-side activity fresh without rotating durable conversations.
  // Conversation lifetime/retention is owned by the backend policy layer, not the UI.
  useEffect(() => {
    const activeSessionId = currentSession?.id;
    if (!activeSessionId) {
      return;
    }

    const RENEWAL_INTERVAL = 5 * 60 * 1000; // 5 minutes

    const renewSession = async () => {
      try {
        await apiClient.post(`/api/conversations/update-session-activity/${activeSessionId}`);
      } catch (err) {
        // Heartbeat failures are transient during backend startup or brief outages.
        // Keep the current session intact and let the next interval retry naturally.
        console.warn('Session activity update skipped:', err);
      }
    };

    const renewalId = window.setInterval(renewSession, RENEWAL_INTERVAL);

    return () => {
      window.clearInterval(renewalId);
    };
  }, [currentSession?.id]);

  // Delete a session
  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await apiClient.delete(`/api/conversations/${sessionId}`);

      // Remove stale browser recovery only after durable server deletion succeeds.
      removeSessionState(sessionId);
      setSessions(prev => prev.filter(s => s.id !== sessionId));

      let replacementFailed = false;
      if (currentSession?.id === sessionId) {
        setCurrentSession(null);
        persistActiveSessionId(null);
        try {
          await createNewSession();
        } catch {
          replacementFailed = true;
        }
      }

      await refreshSessions();
      if (replacementFailed) {
        setError('Chat deleted, but a replacement chat could not be created yet.');
      }
      return true;
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError('Failed to delete session. Please try again.');
      return false;
    }
  }, [currentSession?.id, createNewSession, persistActiveSessionId, refreshSessions]);

  // Delete multiple sessions
  const deleteSessions = useCallback(async (sessionIds: string[]) => {
    if (sessionIds.length === 0) return true;
    
    try {
      const deletedIds = new Set<string>();
      const failedIds: string[] = [];
      const retryableStatuses = new Set([429, 502, 503, 504]);

      for (const sessionId of sessionIds) {
        let attempts = 0;

        while (attempts < 2) {
          attempts += 1;
          try {
            await apiClient.delete(`/api/conversations/${sessionId}`);
            deletedIds.add(sessionId);
            break;
          } catch (err) {
            if (err instanceof ApiError && err.status === 404) {
              deletedIds.add(sessionId);
              break;
            }

            const shouldRetry =
              err instanceof ApiError &&
              retryableStatuses.has(err.status) &&
              attempts < 2;

            if (shouldRetry) {
              const delayMs =
                err instanceof ApiError && err.status === 429
                  ? getRateLimitDelayMs(err, 900)
                  : 350;
              await new Promise((resolve) => window.setTimeout(resolve, delayMs));
              continue;
            }

            failedIds.push(sessionId);
            break;
          }
        }
      }

      if (deletedIds.size > 0) {
        deletedIds.forEach((sessionId) => removeSessionState(sessionId));
        setSessions(prev => prev.filter(s => !deletedIds.has(s.id)));
      }

      let replacementFailed = false;
      if (currentSession && deletedIds.has(currentSession.id)) {
        setCurrentSession(null);
        persistActiveSessionId(null);
        try {
          await createNewSession();
        } catch {
          replacementFailed = true;
        }
      }

      if (deletedIds.size > 0) {
        await refreshSessions();
      }

      if (failedIds.length > 0) {
        setError(`Failed to delete ${failedIds.length} session${failedIds.length === 1 ? '' : 's'}. Please try again.`);
        return false;
      }

      if (replacementFailed) {
        setError('Chats were deleted, but a replacement chat could not be created yet.');
      }
      return true;
    } catch (err) {
      console.error('Failed to delete sessions:', err);
      setError('Failed to delete some sessions. Please try again.');
      return false;
    }
  }, [currentSession, createNewSession, getRateLimitDelayMs, persistActiveSessionId, refreshSessions]);

  // Update a session title
  const updateSessionTitle = useCallback(async (sessionId: string, newTitle: string) => {
    try {
      await apiClient.put(`/api/conversations/${sessionId}`, { title: newTitle });
      
      // Update sessions list
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title: newTitle } : s));
      
      // If updated session is current, update it too
      if (currentSession?.id === sessionId) {
        setCurrentSession(prev => prev ? { ...prev, title: newTitle } : null);
      }
      return true;
    } catch (err) {
      console.error('Failed to update session title:', err);
      setError('Failed to rename session. Please try again.');
      return false;
    }
  }, [currentSession?.id]);

  // Initialize sessions on mount
  useEffect(() => {
    const bootstrapKey = `initialize:${initialSessionId || '__new__'}`;
    if (shouldSuppressRecentBootstrap(bootstrapKey)) {
      return;
    }

    const initializeSessions = async () => {
      setIsLoadingSessions(true);
      try {
        const preferredSessionId = initialSessionId || getPersistedActiveSessionId();
        if (preferredSessionId) {
          await loadSession(preferredSessionId);
        } else {
          await createNewSession();
        }
        await refreshSessions();
      } catch (err) {
        console.warn('Session initialization could not establish a durable conversation:', err);
      } finally {
        setIsLoadingSessions(false);
      }
    };
    
    initializeSessions();
    // Only initialize once on mount or when initialSessionId explicitly changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSessionId, getPersistedActiveSessionId]);

  return (
    <SessionContext.Provider value={{
      currentSession,
      sessions,
      isLoadingSessions,
      error,
      createNewSession,
      loadSession,
      refreshSessions,
      deleteSession,
      deleteSessions,
      updateSessionTitle,
    }}>
      {children}
    </SessionContext.Provider>
  );
}

interface SpeechRecognitionConstructor {
  new(): SpeechRecognition;
  prototype: SpeechRecognition;
}

interface SpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: (event: SpeechRecognitionEvent) => void;
  onerror: (event: SpeechRecognitionErrorEvent) => void;
  onend: () => void;
  start(): void;
  stop(): void;
}

interface SpeechRecognitionEvent {
  resultIndex: number;
  results: SpeechRecognitionResultList;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionAlternative {
  transcript: string;
}

interface SpeechRecognitionErrorEvent {
  error: string;
  message: string;
}

declare global {
  interface Window {
    SpeechRecognition: SpeechRecognitionConstructor | undefined;
    webkitSpeechRecognition: SpeechRecognitionConstructor | undefined;
  }
}

const createSessionId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  const randomHex = (length: number) =>
    Array.from({ length }, () => Math.floor(Math.random() * 16).toString(16)).join('');

  return [
    randomHex(8),
    randomHex(4),
    `4${randomHex(3)}`,
    `${(8 + Math.floor(Math.random() * 4)).toString(16)}${randomHex(3)}`,
    randomHex(12),
  ].join('-');
};

const approvalActions = (
  approvalId: string,
  status: string,
): SuggestedAction[] =>
  status === 'approved'
    ? [
        {
          type: 'approval.resume',
          description: 'Resume',
          params: { approval_id: approvalId },
        },
      ]
    : [
        {
          type: 'approval.approve',
          description: 'Approve',
          params: { approval_id: approvalId },
        },
        {
          type: 'approval.reject',
          description: 'Reject',
          params: { approval_id: approvalId },
        },
      ];

const approvalMessageContent = (status: string): string =>
  status === 'approved'
    ? 'Approval granted. KAREN is ready to resume this action.'
    : 'Approval required before KAREN can continue this action.';

const actionableApprovalToMessage = (approval: ActionableApproval): ChatMessage => ({
  id: `approval-${approval.approval_id}`,
  role: 'assistant',
  content: approvalMessageContent(approval.status),
  timestamp: new Date(approval.created_at),
  status: 'completed',
  actions: approvalActions(approval.approval_id, approval.status),
  metadata: {
    mode: 'approval_required',
    status: 'gate',
    approval_projection: true,
    approval_id: approval.approval_id,
    approval_status: approval.status,
    conversation_id: approval.conversation_id || undefined,
    policy_decision_id: approval.policy_decision_id || undefined,
    intent: approval.intent,
    risk_level: approval.risk_level,
    reason_codes: approval.reason_codes,
    expires_at: approval.expires_at,
  },
});

const reconcileActionableApprovalMessages = (
  currentMessages: ChatMessage[],
  actionableApprovals: ActionableApproval[],
): ChatMessage[] => {
  const actionableById = new Map(
    actionableApprovals.map((approval) => [approval.approval_id, approval]),
  );

  const reconciled = currentMessages
    .filter((message) => {
      const metadata = message.metadata || {};
      const approvalId = String(metadata.approval_id || '').trim();
      const isProjection = metadata.approval_projection === true;
      return !isProjection || (approvalId && actionableById.has(approvalId));
    })
    .map((message) => {
      const metadata = message.metadata || {};
      const approvalId = String(metadata.approval_id || '').trim();
      const actionable = approvalId ? actionableById.get(approvalId) : undefined;

      if (!approvalId || !actionable) {
        if (approvalId && message.actions?.some((action) => action.type.startsWith('approval.'))) {
          return {
            ...message,
            actions: [],
          };
        }
        return message;
      }

      return {
        ...message,
        content:
          actionable.status === 'approved'
            ? approvalMessageContent(actionable.status)
            : message.content,
        actions: approvalActions(approvalId, actionable.status),
        metadata: {
          ...metadata,
          approval_status: actionable.status,
          risk_level: actionable.risk_level,
          reason_codes: actionable.reason_codes,
          expires_at: actionable.expires_at,
        },
      };
    });

  const represented = new Set(
    reconciled
      .map((message) => String(message.metadata?.approval_id || '').trim())
      .filter(Boolean),
  );

  const missingApprovals = actionableApprovals
    .filter((approval) => !represented.has(approval.approval_id))
    .sort(
      (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
    );

  for (const approval of missingApprovals) {
    reconciled.push(actionableApprovalToMessage(approval));
  }

  return reconciled;
};

const CHAT_SESSION_STATE_PREFIX = 'karen.chat.session_state.';
const CHAT_STATE_VERSION = 1;

type PersistedChatMessage = Omit<ChatMessage, 'timestamp'> & { timestamp: string };
type PersistedChatSessionState = {
  version: number;
  sessionId: string;
  messages: PersistedChatMessage[];
  input: string;
  isLoading: boolean;
  processingStatus: string;
  streamedContent: string;
  inFlight: boolean;
  updatedAt: number;
};

const toPersistedMessage = (message: ChatMessage): PersistedChatMessage => ({
  ...message,
  timestamp: message.timestamp instanceof Date
    ? message.timestamp.toISOString()
    : new Date(message.timestamp).toISOString(),
});

const fromPersistedMessage = (message: PersistedChatMessage): ChatMessage => ({
  ...message,
  timestamp: new Date(message.timestamp),
});

const getSessionStateStorageKey = (sessionId: string): string =>
  `${CHAT_SESSION_STATE_PREFIX}${sessionId}`;

const persistSessionState = (sessionId: string, state: PersistedChatSessionState): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(getSessionStateStorageKey(sessionId), JSON.stringify(state));
  } catch {
    // Ignore storage failures.
  }
};

const loadSessionState = (sessionId: string): PersistedChatSessionState | null => {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(getSessionStateStorageKey(sessionId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedChatSessionState;
    if (!parsed || parsed.version !== CHAT_STATE_VERSION || parsed.sessionId !== sessionId) {
      return null;
    }
    if (!Array.isArray(parsed.messages)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
};

const removeSessionState = (sessionId: string): void => {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(getSessionStateStorageKey(sessionId));
  } catch {
    // Ignore storage failures. Durable server deletion remains authoritative.
  }
};

export default function ChatInterface({ isActive = true }: ChatInterfaceProps) {
  const { 
    currentSession, 
    sessions, 
    isLoadingSessions, 
    error, 
    createNewSession, 
    loadSession, 
    refreshSessions, 
    deleteSession, 
    deleteSessions, 
    updateSessionTitle 
  } = useSession();
  const sessionIdRef = useRef(currentSession?.id || createSessionId());
  const submitInFlightRef = useRef(false);
  const restoredSessionNoticeRef = useRef<string | null>(null);
  const { user, isAuthenticated, isLoading: isAuthLoading } = useAuth();
  const { pendingMessages, popMessage } = useMessageInjection();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const currentSessionRef = useRef<Session | null>(currentSession);
  const sessionsRef = useRef<Session[]>(sessions);
  const { toast } = useToast();

  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const [speechRecognitionSupported, setSpeechRecognitionSupported] = useState(true);
  const [shouldSubmitVoiceInput, setShouldSubmitVoiceInput] = useState(false);
  const [isSuggestingStarter, setIsSuggestingStarter] = useState(false);
  const [modelSettings, setModelSettings] = useState<NormalizedRuntimeInventory | null>(null);
  const [selectedProvider, setSelectedProvider] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [isUpdatingModelSelection, setIsUpdatingModelSelection] = useState(false);

  const [processingStatus, setProcessingStatus] = useState('');
  const [streamedContent, setStreamedContent] = useState('');
  const [isEditingDuringProcessing, setIsEditingDuringProcessing] = useState(false);
  const activeRequestControllerRef = useRef<AbortController | null>(null);
  const processingStatusVariantRef = useRef<Record<string, number>>({});
  const [isBackendOffline, setIsBackendOffline] = useState(false);
  const [streamingMetrics, setStreamingMetrics] = useState<{
    chunksReceived: number;
    totalBytes: number;
    connectionHealth: 'excellent' | 'good' | 'poor' | 'critical';
    lastChunkTime: number;
  } | null>(null);
  const [agentSteps, setAgentSteps] = useState<AgentStepEvent[]>([]);
  const [actionableApprovals, setActionableApprovals] = useState<ActionableApproval[]>([]);
  const [actionableApprovalsLoadState, setActionableApprovalsLoadState] = useState<
    'idle' | 'loading' | 'ready' | 'unavailable'
  >('idle');
  const [isLocalRecoveryUnconfirmed, setIsLocalRecoveryUnconfirmed] = useState(false);
  const [degradedMode, setDegradedMode] = useState<{
    active: boolean;
    reason?: string;
    fallbackPath?: string;
  }>({ active: false });

  const loadModelSettings = useCallback(async () => {
    try {
      const response = await apiClient.get<ModelSettingsResponse>('/api/runtime/providers');
      const normalized = normalizeRuntimeProviderCatalogResponse(response);
      setModelSettings(normalized);

      // Check if selected provider is still available and configured
      const selectableProviders = normalized.selectableProviders;
      const selectedProviderId = normalized.selected_provider;
      const selectedProvider = selectableProviders.find(p => p.id === selectedProviderId);

      if (selectedProviderId && !selectedProvider) {
        const fallbackProvider = selectableProviders[0];
        
        toast({
          title: 'Selected provider unavailable',
          description: `The provider "${selectedProviderId}" is not configured or no longer available. Karen switched to ${fallbackProvider?.display_name || 'the default runtime'}.`,
          variant: 'destructive',
        });
        
        setSelectedProvider(fallbackProvider?.id || '');
        setSelectedModel(fallbackProvider?.selected_model || fallbackProvider?.default_model || fallbackProvider?.models?.[0]?.id || '');
      } else {
        setSelectedProvider(normalized.selected_provider);
        
        // Ensure selected model is valid for this provider
        const modelId = normalized.selected_model;
        const modelExists = selectedProvider?.models.some(m => m.id === modelId);
        
        if (selectedProvider && !modelExists) {
           setSelectedModel(
             selectedProvider.selected_model ||
             selectedProvider.default_model ||
             modelId ||
             selectedProvider.models?.[0]?.id ||
             ''
           );
        } else {
           setSelectedModel(normalized.selected_model);
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        return;
      }
      toast({
        title: 'Unable to load model settings',
        description: 'Karen could not load configured providers/models for chat.',
        variant: 'destructive',
      });
    }
  }, [toast]);

  useEffect(() => {
    if (isAuthLoading) {
      return;
    }
    
    if (isAuthenticated && isActive) {
      void loadModelSettings();
    }
  }, [isAuthLoading, isAuthenticated, loadModelSettings, isActive]);

  useEffect(() => {
    currentSessionRef.current = currentSession;
  }, [currentSession]);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  // Helper variables extracted for reuse
  const showStopButton = isLoading && submitInFlightRef.current;

  const displayedInputValue = showStopButton && !isEditingDuringProcessing
    ? processingStatus || DEFAULT_PROCESSING_MESSAGE
    : input;



  const {
    preferredAddressName,
    displayName,
    recentMessages,
  } = useUserPreferences(user, isAuthenticated, messages);

  useGreetingSystem(
    isAuthLoading || isLoading || isLoadingSessions || !currentSession?.id,
    isAuthenticated,
    user,
    messages,
    setMessages,
  );

  // Streaming status
  const streamingStatus = useMemo(
    () =>
      getStreamingStatus(
        isBackendOffline,
        isLoading,
        processingStatus,
        streamingMetrics,
      ),
    [
      isBackendOffline,
      isLoading,
      processingStatus,
      streamingMetrics,
    ],
  );

  const { stopActiveRequest } = useRequestHandlers(
    submitInFlightRef,
    activeRequestControllerRef,
    setIsLoading,
    setProcessingStatus,
  );

  const { scrollChatToBottom } = useScrollManagement(
    messages,
    isLoading,
    viewportRef,
    messagesContainerRef,
  );

  const { applyModelSelection, getSelectableProviders } = useModelSettings();


  const refreshActionableApprovals = useCallback(
    async (conversationId: string): Promise<ActionableApproval[] | null> => {
      setActionableApprovalsLoadState('loading');
      try {
        const approvals = await apiClient.get<ActionableApproval[]>(
          `/api/approvals?conversation_id=${encodeURIComponent(conversationId)}`,
        );
        const actionable = Array.isArray(approvals)
          ? approvals.filter(
              (approval) =>
                (approval.status === 'pending' || approval.status === 'approved') &&
                (!approval.conversation_id ||
                  approval.conversation_id === conversationId),
            )
          : [];

        if (sessionIdRef.current !== conversationId) {
          return actionable;
        }

        setActionableApprovals(actionable);
        setMessages((current) =>
          reconcileActionableApprovalMessages(current, actionable),
        );
        setActionableApprovalsLoadState('ready');
        return actionable;
      } catch (error) {
        if (sessionIdRef.current === conversationId) {
          setActionableApprovalsLoadState('unavailable');
        }
        if (error instanceof ApiError && error.status === 401) {
          return null;
        }
        return null;
      }
    },
    [setMessages],
  );

  const latestAssistantMetadata = useMemo(() => {
    const lastAssistant = [...messages]
      .reverse()
      .find(
        (message) =>
          message.role === 'assistant' &&
          message.metadata?.approval_projection !== true,
      );
    const metadata = (lastAssistant?.metadata && typeof lastAssistant.metadata === 'object')
      ? lastAssistant.metadata as Record<string, unknown>
      : {};

    const asText = (value: unknown): string | undefined =>
      typeof value === 'string' && value.trim() ? value.trim() : undefined;

    const degradedReason = getDegradationReasonLabel(asText(metadata.degradation_reason)) || asText(metadata.degradation_reason);
    const status = getDegradationReasonLabel(asText(metadata.status)) || asText(metadata.status);
    const responseSource = asText(metadata.response_source);
    const fallbackLevel = asText(metadata.fallback_level);

    const actualProvider = asText(metadata.actual_provider);
    const actualModel = asText(metadata.actual_model);

    return {
      requestedProvider: asText(metadata.requested_provider),
      actualProvider,
      requestedModel: asText(metadata.requested_model),
      actualModel,
      runtimeEngine: asText(metadata.runtime_engine),
      fallbackLevel,
      correlationId: asText(metadata.correlation_id),
      requestId: asText(metadata.request_id),
      status,
      responseSource,
      degradedMode: Boolean(metadata.degraded_mode),
      degradedReason,
      degradationType: asText(metadata.degradation_type),
      latencyMs:
        typeof metadata.latency_ms === 'number' && Number.isFinite(metadata.latency_ms)
          ? metadata.latency_ms
          : undefined,
      providerAttempts: Array.isArray(metadata.provider_attempts)
        ? metadata.provider_attempts as Array<{
            provider: string;
            model: string;
            status: string;
            error_type?: string;
            error_message?: string;
            latency_ms?: number;
          }>
        : [],
      showCircuitWarning: Boolean(metadata.circuit_breaker_open || metadata.dependency_degraded || degradedReason),
      rawMetadata: metadata,
    };
  }, [messages]);
  const selectableProviders = useMemo(() => {
    return modelSettings ? getSelectableProviders(modelSettings) : [];
  }, [getSelectableProviders, modelSettings]);

  const handleApplyModelSelection = useCallback(
    async (providerId: string, modelId: string) => {
      await applyModelSelection(
        providerId,
        modelId,
        modelSettings,
        setModelSettings,
        setSelectedProvider,
        setSelectedModel,
        setIsUpdatingModelSelection,
        toast,
      );
    },
    [
      applyModelSelection,
      modelSettings,
      setModelSettings,
      setSelectedProvider,
      setSelectedModel,
      setIsUpdatingModelSelection,
      toast,
    ],
  );

  /*
   * ChatInterface coordinates the browser-side request lifecycle:
   * optimistic user message, streaming transport, cancellation, and UI state.
   *
   * It does not decide provider routing or fallback truth. Backend metadata owns:
   * actual_provider, actual_model, runtime_engine, response_source, fallback_level,
   * and degraded_mode.
   */

  useEffect(() => {
    if (!currentSession?.id) return;
    sessionIdRef.current = currentSession.id;
  }, [currentSession?.id]);

  useEffect(() => {
    if (!currentSession?.id) return;

    let cancelled = false;

    const restoreSessionState = async () => {
      const sessionId = currentSession.id;
      // Always reset volatile chat UI state when switching sessions.
      // If the target session has no local/server history yet, this prevents
      // stale messages from the previous session appearing as if "new chat" failed.
      if (!cancelled) {
        setMessages([]);
        setInput('');
        setStreamedContent('');
        setProcessingStatus('');
        setIsLoading(false); // Start as false, only set to true if we have an in-flight request
        setAgentSteps([]);
        setDegradedMode({ active: false });
        setActionableApprovals([]);
        setActionableApprovalsLoadState('loading');
        setIsLocalRecoveryUnconfirmed(false);
        submitInFlightRef.current = false;
      }

      const persisted = loadSessionState(sessionId);
      const persistedMessages = (persisted?.messages || []).map(fromPersistedMessage);
      const hasRestorableState = Boolean(
        persisted &&
          (
            persistedMessages.length > 0 ||
            persisted.inFlight ||
            (persisted.input && persisted.input.trim().length > 0)
          )
      );

      if (!cancelled && persisted) {
        if (persistedMessages.length > 0) {
          setMessages(persistedMessages);
          setIsLocalRecoveryUnconfirmed(true);
        }
        setInput(persisted.input || '');
        setStreamedContent(persisted.streamedContent || '');
        setProcessingStatus(persisted.processingStatus || '');
        setIsLoading(Boolean(persisted.inFlight)); // Only set loading if there's an in-flight request
        submitInFlightRef.current = Boolean(persisted.inFlight);
      }

      if (!cancelled && hasRestorableState && restoredSessionNoticeRef.current !== sessionId) {
        restoredSessionNoticeRef.current = sessionId;
        toast({
          title: 'Recovered local session state',
          description: 'Checking the server before treating restored messages as durably saved.',
        });
      }

      const fetchConversationMessages = async (): Promise<ChatMessage[]> => {
        const conversation = await fetchConversationBootstrap(sessionId);
        return (conversation.messages || []).map(normalizeConversationMessage);
      };

      try {
        const serverMessages = await fetchConversationMessages();
        if (cancelled) return;

        const shouldApplyServerMessages =
          serverMessages.length > 0 &&
          (
            !persisted ||
            !persisted.inFlight ||
            serverMessages.length >= persistedMessages.length
          );

        if (shouldApplyServerMessages) {
          setMessages(serverMessages);
          if (serverMessages.length >= persistedMessages.length) {
            setIsLocalRecoveryUnconfirmed(false);
          }
        }

        if (persisted?.inFlight && serverMessages.length <= persistedMessages.length) {
          // Only try to restore in-flight requests if they're recent (within 5 minutes)
          const now = Date.now();
          const requestAge = now - (persisted.updatedAt || 0);
          if (requestAge > 5 * 60 * 1000) { // 5 minutes
            console.log('In-flight request too old, not restoring');
            setIsLoading(false);
            submitInFlightRef.current = false;
            setProcessingStatus('');
            setStreamedContent('');
          } else {
            for (let attempt = 0; attempt < 10; attempt += 1) {
              await new Promise((resolve) => window.setTimeout(resolve, 2000));
              if (cancelled) return;

              const polledMessages = await fetchConversationMessages();
              if (cancelled) return;
              if (polledMessages.length > persistedMessages.length) {
                setMessages(polledMessages);
                setIsLocalRecoveryUnconfirmed(false);
                setIsLoading(false);
                submitInFlightRef.current = false;
                setProcessingStatus('');
                setStreamedContent('');
                break;
              }
            }
          }
        }
      } catch {
        // Keep useful recovery state visible, but never present it as durable truth.
        if (!cancelled && persistedMessages.length > 0) {
          setIsLocalRecoveryUnconfirmed(true);
        }
      } finally {
        if (!cancelled) {
          await refreshActionableApprovals(sessionId);
        }
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void restoreSessionState();

    return () => {
      cancelled = true;
    };
  }, [
    currentSession?.id,
    setMessages,
    setInput,
    toast,
    refreshActionableApprovals,
  ]);

  /*
   * Local session snapshots protect in-progress UI state across refreshes.
   * They are not the durable source of truth; server conversation history wins
   * once it returns with a complete message set.
   */
  useEffect(() => {
    if (!currentSession?.id) return;

    persistSessionState(currentSession.id, {
      version: CHAT_STATE_VERSION,
      sessionId: currentSession.id,
      messages: messages.map(toPersistedMessage),
      input,
      isLoading,
      processingStatus,
      streamedContent,
      inFlight: submitInFlightRef.current,
      updatedAt: typeof window !== 'undefined' ? Date.now() : 0,
    });
  }, [currentSession?.id, messages, input, isLoading, processingStatus, streamedContent]);

  // Save preferred address name
  const savePreferredAddressName = useCallback(async (preferredName: string) => {
    if (!user) {
      return false;
    }

    const nextPreferences = {
      ...(user.preferences || {}),
      preferred_address_name: preferredName,
    };

    await apiClient.put('/api/auth/me', {
      preferences: nextPreferences,
    });

    authService.updateCurrentUser({
      preferences: nextPreferences,
    });

    await apiClient.post('/api/memory/commit', {
      user_id: user.user_id,
      text: `The user prefers to be addressed as ${preferredName}.`,
      tags: ['personal_fact', 'preferred_name', 'user_preference'],
      importance: 9,
      decay: 'pinned',
    }).catch(() => undefined);

    return true;
  }, [user]);






  // Submit handler
  const handleSubmit = useCallback(async (
    manualInput?: string,
    approvalResume?: { approvalId: string; suppressUserMessage?: boolean },
  ) => {
    const rawInput = manualInput || input;
    const isApprovalResume = Boolean(approvalResume?.approvalId);
    if (
      (!rawInput.trim() && !isApprovalResume) ||
      isAuthLoading ||
      submitInFlightRef.current
    ) return;

    const trimmedInput = rawInput.trim();
    const lastAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant');
    const addressOptions = Array.isArray(lastAssistantMessage?.metadata?.addressOptions)
      ? (lastAssistantMessage.metadata.addressOptions as string[])
      : [];
    const matchedAddressOption = addressOptions.find(
      (option) => option.trim().toLowerCase() === trimmedInput.toLowerCase()
    );

    if (
      !isApprovalResume &&
      lastAssistantMessage?.metadata?.addressPreferencePrompt &&
      matchedAddressOption
    ) {
      try {
        await savePreferredAddressName(matchedAddressOption);
      } catch {
        toast({
          title: 'Preference update failed',
          description: 'Karen could not save your preferred form of address.',
          variant: 'destructive',
        });
        return;
      }
    }

    const userMessage: ChatMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      content: trimmedInput,
      timestamp: new Date(),
      status: 'pending',
    };
    if (!approvalResume?.suppressUserMessage) {
      setMessages((prev) => [...prev, userMessage]);
    }
    setInput('');
    submitInFlightRef.current = true;
    setIsLoading(true);
    setIsEditingDuringProcessing(false);
    processingStatusVariantRef.current = {};
    setProcessingStatus(resolveProcessingStatusMessage('initializing', DEFAULT_PROCESSING_MESSAGE));
    setStreamedContent('');
    setAgentSteps([]);
    setDegradedMode({ active: false });

    const preferredProvider = selectedProvider;
    const preferredModel = selectedModel;
    const streamStartedAt = Date.now();

    let collectedContent = '';
    let completedMetadata: Record<string, unknown> | undefined;
    let streamFailed = false;
    let streamFailureMessage = '';
    const MAX_RETRIES = 2;

    const enrichStreamMetadata = (
      rawMetadata?: Record<string, unknown>,
    ): Record<string, unknown> => {
      const metadata = { ...(rawMetadata || {}) } as Record<string, unknown>;
      const rawLlm =
        metadata.llm && typeof metadata.llm === 'object' && !Array.isArray(metadata.llm)
          ? (metadata.llm as Record<string, unknown>)
          : {};
      const llm = { ...rawLlm };

      if (typeof llm.duration !== 'number') {
        if (typeof metadata.total_ms === 'number') {
          llm.duration = metadata.total_ms / 1000;
        } else {
          llm.duration = (Date.now() - streamStartedAt) / 1000;
        }
      }

      if (typeof llm.tokens_per_second !== 'number') {
        const tokensPerSecond =
          typeof metadata.tokens_per_second === 'number'
            ? metadata.tokens_per_second
            : undefined;
        if (typeof tokensPerSecond === 'number') {
          llm.tokens_per_second = tokensPerSecond;
        }
      }

      metadata.llm = llm;
      metadata.status = metadata.status || 'completed';
      metadata.execution_path = metadata.execution_path || 'stream';
      return metadata;
    };

    const attemptStream = async (attempt: number): Promise<void> => {
      try {
        streamFailureMessage = '';
        let completionContent = '';
        const controller = new AbortController();
        activeRequestControllerRef.current = controller;
        const collectedAgentSteps: AgentStepEvent[] = [];
        let collectedCitations: Citation[] = [];
        let degradedModeSnapshot = {
          active: false,
          reason: '',
          fallbackPath: '',
        };
        const approvalState: {
          event: {
            message: string;
            metadata: Record<string, unknown>;
          } | null;
        } = { event: null };

        const streamRequestPayload = {
          message: userMessage.content,
          session_id: currentSessionRef.current?.runtimeSessionId || sessionIdRef.current,
          conversation_id: sessionIdRef.current,
          preferred_llm_provider: preferredProvider,
          preferred_model: preferredModel,
          temperature: 0.7,
          max_tokens: undefined,
          stream: true,
        };

      await apiClient.postStream(
        isApprovalResume
          ? `/api/chat/approvals/${approvalResume?.approvalId}/resume`
          : '/api/chat/stream',
        isApprovalResume ? undefined : streamRequestPayload,
        {
          onStatus: (message, metadata) => {
            const statusKey =
              normalizeProcessingStatusKey(metadata?.status) ||
              normalizeProcessingStatusKey(message) ||
              'processing';
            const variantIndex = processingStatusVariantRef.current[statusKey] || 0;
            processingStatusVariantRef.current[statusKey] = variantIndex + 1;
            const resolved = resolveProcessingStatus(
              statusKey,
              message,
              {
                ...(metadata || {}),
                status: (metadata?.status as string | undefined) || statusKey,
                stage: (metadata?.stage as string | undefined) || statusKey,
                node: metadata?.node as string | undefined,
                started_at: metadata?.started_at as string | number | undefined,
                elapsed_ms: metadata?.elapsed_ms as number | string | undefined,
              },
            );
            const statusMessage = resolved.elapsedLabel
              ? `${resolved.message} (${resolved.elapsedLabel})`
              : resolved.message;
            setProcessingStatus(statusMessage);
          },
          onContent: (token) => {
            collectedContent += token;
            setStreamedContent(collectedContent);
          },
          onError: (message) => {
            streamFailed = true;
            streamFailureMessage = message || 'Streaming endpoint reported an error';
            setProcessingStatus(streamFailureMessage);
          },
          onComplete: (metadata, content) => {
            completedMetadata = enrichStreamMetadata(metadata);
            completionContent = String(
              content ||
              (completedMetadata?.formatted_content as string) ||
              '',
            );
          },
          onMetrics: (metrics) => {
            setStreamingMetrics({
              chunksReceived: metrics.chunksReceived,
              totalBytes: metrics.totalBytes,
              connectionHealth: metrics.connectionHealth,
              lastChunkTime: metrics.lastChunkTime,
            });
          },
          onAgentStep: (event) => {
            collectedAgentSteps.push(event);
            setAgentSteps((prevSteps) => [...prevSteps, event]);
            // Handle degraded mode events
            if (event.type === 'degraded_mode_entered') {
              degradedModeSnapshot = {
                active: true,
                reason: String(event.metadata?.reason || ''),
                fallbackPath: String(event.metadata?.fallback_path || ''),
              };
              setDegradedMode({
                active: true,
                reason: degradedModeSnapshot.reason,
                fallbackPath: degradedModeSnapshot.fallbackPath,
              });
            }
          },
          onCitationBundle: (nextCitations) => {
            collectedCitations = nextCitations;
          },
          onApproval: (message, metadata) => {
            approvalState.event = { message, metadata };
            setProcessingStatus(message || 'Approval required');
          },
        },
        controller.signal,
      );

         if (streamFailed) {
           const errorMessage = streamFailureMessage || processingStatus || 'Streaming endpoint reported an error';
           throw new Error(errorMessage);
         }

        setIsBackendOffline(false);

        const approvalEvent = approvalState.event;
        if (approvalEvent) {
          const approvalMetadata = approvalEvent.metadata;
          const approvalId = String(approvalMetadata.approval_id || '').trim();
          const approvalStatus = String(
            approvalMetadata.approval_status || approvalMetadata.status || 'pending',
          );
          const approvalMessage: ChatMessage = {
            id: `approval-${approvalId || Date.now()}`,
            role: 'assistant',
            content:
              approvalEvent.message ||
              'Approval required before KAREN can continue.',
            timestamp: new Date(),
            status: 'completed',
            actions:
              approvalId
                ? approvalActions(approvalId, approvalStatus)
                : [],
            metadata: {
              ...approvalMetadata,
              status: 'gate',
              approval_status: approvalStatus,
            },
          };

          setMessages((prev) => {
            const next = prev.map((message) =>
              message.id === userMessage.id
                ? { ...message, status: 'completed' as const }
                : message,
            );
            return next.concat(approvalMessage);
          });
          scrollChatToBottom('smooth');
          void refreshActionableApprovals(sessionIdRef.current);
          return;
        }

        const fullContent = (completionContent || collectedContent).trim();

        if (!fullContent) {
          throw new Error('Empty response from streaming endpoint');
        }

        // Validate backend metadata completeness
        const finalMetadata = completedMetadata || enrichStreamMetadata();
        const llmMetadata = typeof finalMetadata.llm === 'object' && finalMetadata.llm !== null && !Array.isArray(finalMetadata.llm)
          ? finalMetadata.llm as Record<string, unknown>
          : {};

        if (preferredProvider && !finalMetadata.requested_provider) {
          console.warn(
            `[ChatInterface] Backend did not provide requested_provider. ` +
              `Sent: ${preferredProvider}, Expected in metadata.requested_provider. ` +
              `This may indicate provider routing bypassed or unavailable.`
          );
        }

        const streamResponse = {
          answer: fullContent,
          correlationId: completedMetadata?.correlation_id as string || undefined,
          actions: (completedMetadata?.actions as SuggestedAction[]) || [],
          metadata: finalMetadata,
        };

        if (approvalResume?.approvalId) {
          setMessages((prev) =>
            prev.map((message) =>
              String(message.metadata?.approval_id || '') === approvalResume.approvalId
                ? {
                    ...message,
                    actions: [],
                    metadata: {
                      ...(message.metadata || {}),
                      approval_status: 'consumed',
                    },
                  }
                : message,
            ),
          );
          void refreshActionableApprovals(sessionIdRef.current);
        }

        const richStructuredContent =
          completedMetadata?.structured_content &&
          typeof completedMetadata.structured_content === 'object' &&
          !Array.isArray(completedMetadata.structured_content)
            ? completedMetadata.structured_content as Record<string, unknown>
            : {};
        const richSources = Array.isArray(completedMetadata?.sources)
          ? completedMetadata.sources as Citation[]
          : [];
        const richAttachments = Array.isArray(completedMetadata?.attachments)
          ? completedMetadata.attachments as ChatMessage['attachments']
          : [];
        const richArtifacts = Array.isArray(completedMetadata?.artifacts)
          ? completedMetadata.artifacts as ChatMessage['artifacts']
          : [];
        const richCitations = collectedCitations.length > 0
          ? collectedCitations
          : Array.isArray(completedMetadata?.citations)
            ? completedMetadata.citations as Citation[]
            : [];

        const streamAssistantMessage: ChatMessage = {
          id: streamResponse.correlationId || 'assistant-' + Date.now(),
          role: 'assistant',
          content: streamResponse.answer,
          timestamp: new Date(),
          status: 'completed',
          structuredContent: richStructuredContent,
          actions: streamResponse.actions,
          metadata: {
            ...streamResponse.metadata,
            citations: richCitations,
            sources: richSources,
            attachments: richAttachments,
            artifacts: richArtifacts,
            agentSteps: collectedAgentSteps,
            degradedMode: degradedModeSnapshot.active,
          },
          citations: richCitations,
          sources: richSources,
          attachments: richAttachments,
          artifacts: richArtifacts,
        };

        setMessages((prev) => {
          return prev.map(m => m.id === userMessage.id ? { ...m, status: 'completed' as const } : m)
            .concat(streamAssistantMessage);
        });
        scrollChatToBottom('smooth');
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return;
        }

        // Retry on specific errors
        const isApiRetryable =
          error instanceof ApiError &&
          (
            error.status >= 500 ||
            error.status === 502 ||
            error.status === 503 ||
            error.status === 504 ||
            error.message.includes('timeout') ||
            error.message.includes('connection')
          );
        const isGenericTimeout =
          error instanceof Error &&
          !(error instanceof ApiError) &&
          (
            error.message.toLowerCase().includes('timeout') ||
            error.message.toLowerCase().includes('stalled')
          );
        const shouldRetry = attempt < MAX_RETRIES && (isApiRetryable || isGenericTimeout);

        if (shouldRetry) {
          const delay = Math.pow(2, attempt) * 1000; // Exponential backoff
          console.log(`Retrying stream attempt ${attempt + 1}/${MAX_RETRIES} after ${delay}ms...`);
          await new Promise(resolve => setTimeout(resolve, delay));
          return attemptStream(attempt + 1);
        }

        throw error; // Re-throw if no more retries or not retryable error
      }
    };

    try {
      await attemptStream(0);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        return;
      }

      if (approvalResume?.approvalId) {
        void refreshActionableApprovals(sessionIdRef.current);
      }

      if (error instanceof TypeError) {
        setIsBackendOffline(true);
      } else if (
        error instanceof ApiError &&
        error.status >= 500 &&
        typeof (error.details as Record<string, unknown> | undefined)?.mode !== 'string'
      ) {
        setIsBackendOffline(true);
      }

      const runtimePayload =
        error instanceof ApiError &&
        error.details &&
        typeof error.details === 'object' &&
        typeof (error.details as Record<string, unknown>).mode === 'string'
          ? (error.details as Record<string, unknown>)
          : null;

      const fallbackErrorResponse = runtimePayload
        ? normalizeBackendChatResponse(runtimePayload)
        : null;

      const errorAssistantMessage: ChatMessage | null = fallbackErrorResponse ? {
        id: fallbackErrorResponse.correlationId || 'assistant-error-' + Date.now(),
        role: 'assistant',
        content: fallbackErrorResponse.answer,
        timestamp: new Date(),
        status: 'completed',
        structuredContent: fallbackErrorResponse.structuredContent,
        actions: fallbackErrorResponse.actions,
        citations: fallbackErrorResponse.citations,
        sources: fallbackErrorResponse.sources,
        attachments: fallbackErrorResponse.attachments,
        artifacts: fallbackErrorResponse.artifacts,
        metadata: fallbackErrorResponse.metadata,
      } : null;

      setMessages((prev) => {
        const next = prev.map(m => m.id === userMessage.id ? {
          ...m,
          status: fallbackErrorResponse ? 'completed' as const : 'failed' as const,
        } : m);
        
        return errorAssistantMessage ? next.concat(errorAssistantMessage) : next;
      });

      toast(
        fallbackErrorResponse
          ? {
              title:
                (fallbackErrorResponse.metadata as Record<string, unknown>)?.mode === 'maintenance'
                  ? 'Maintenance mode active'
                  : (fallbackErrorResponse.metadata as Record<string, unknown>)?.mode === 'emergency_fallback'
                    ? 'Emergency fallback active'
                    : 'Limited chat mode',
              description: fallbackErrorResponse.answer,
          }
          : {
              title: 'Chat request failed',
              description: getDegradedResponseMessage(error),
          }
      );
      console.error('Chat request failed:', error);
    } finally {
      submitInFlightRef.current = false;
      activeRequestControllerRef.current = null;
      setIsLoading(false);
      setIsEditingDuringProcessing(false);
      setProcessingStatus('');
      setStreamedContent('');
      setStreamingMetrics(null);
    }

  }, [input, isAuthLoading, messages, displayName, preferredAddressName, recentMessages, selectedProvider, selectedModel, toast, user, setInput, setMessages, setIsLoading, setIsEditingDuringProcessing, setProcessingStatus, setStreamedContent, setStreamingMetrics, activeRequestControllerRef, sessionIdRef, isAuthenticated, processingStatus, savePreferredAddressName, scrollChatToBottom, refreshActionableApprovals]);

  // Process injected messages from other parts of the app
  useEffect(() => {
    if (pendingMessages.length > 0 && !isAuthLoading && !isLoading) {
      const nextMessage = pendingMessages[0];

      if (nextMessage.autoSubmit) {
        void handleSubmit(nextMessage.content);
      } else {
        setInput(nextMessage.content);
      }

      popMessage(nextMessage.id);
    }
  }, [pendingMessages, isAuthLoading, isLoading, handleSubmit, setInput, popMessage]);

  // Handle functions
  const handleActionClick = useCallback(async (action: SuggestedAction) => {
    if (
      action.type === 'approval.approve' ||
      action.type === 'approval.reject' ||
      action.type === 'approval.resume'
    ) {
      const approvalId = String(action.params?.approval_id || '').trim();
      if (!approvalId) {
        toast({
          title: 'Approval unavailable',
          description: 'The approval receipt is missing.',
          variant: 'destructive',
        });
        return;
      }

      if (action.type === 'approval.resume') {
        await handleSubmit(undefined, {
          approvalId,
          suppressUserMessage: true,
        });
        return;
      }

      const decision =
        action.type === 'approval.approve' ? 'approved' : 'rejected';

      try {
        await apiClient.post(`/api/approvals/${approvalId}/decision`, {
          decision,
        });
        await refreshActionableApprovals(sessionIdRef.current);

        if (decision === 'approved') {
          await handleSubmit(undefined, {
            approvalId,
            suppressUserMessage: true,
          });
          return;
        }

        setMessages((prev) =>
          prev.map((message) =>
            String(message.metadata?.approval_id || '') === approvalId
              ? {
                  ...message,
                  actions: [],
                  metadata: {
                    ...(message.metadata || {}),
                    approval_status: 'rejected',
                  },
                }
              : message,
          ),
        );
        toast({
          title: 'Action rejected',
          description: 'Nothing was executed.',
        });
        return;
      } catch (error) {
        toast({
          title: 'Approval update failed',
          description:
            error instanceof Error
              ? error.message
              : 'KAREN could not update that approval.',
          variant: 'destructive',
        });
        return;
      }
    }

    const messageText = action.description || action.type;
    if (!messageText) return;
    setInput(messageText);
    void handleSubmit(messageText);
  }, [
    setInput,
    handleSubmit,
    setMessages,
    toast,
    refreshActionableApprovals,
  ]);

  const handleFormSubmit = useCallback((e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    handleSubmit();
  }, [handleSubmit]);

  const handleSuggestStarter = useCallback(() => {
    setIsSuggestingStarter(true);
    try {
      setInput('Tell me a fun fact about space.');
    } finally {
      setIsSuggestingStarter(false);
    }
  }, [setIsSuggestingStarter, setInput]);

  const handleExportCurrentChat = useCallback(async () => {
    if (!currentSession) {
      toast({
        title: 'No active chat',
        description: 'Select or start a chat before exporting.',
        variant: 'destructive',
      });
      return;
    }

    const safeTitle = (currentSession.title || 'chat-export').trim() || 'chat-export';
    const slug = safeTitle
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'chat-export';

    const lines: string[] = [
      `# ${safeTitle}`,
      '',
      `Session ID: ${currentSession.id}`,
      `Exported: ${new Date().toISOString()}`,
      '',
    ];

    for (const message of messages) {
      const roleLabel = message.role === 'assistant' ? 'Karen' : message.role === 'user' ? 'User' : 'System';
      const when = message.timestamp instanceof Date
        ? message.timestamp.toISOString()
        : new Date(message.timestamp).toISOString();
      lines.push(`## ${roleLabel} (${when})`);
      lines.push('');
      lines.push(message.content || '');
      lines.push('');
    }

    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `${slug}.md`;
    if (typeof document !== 'undefined') {
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    }
    window.URL.revokeObjectURL(url);

    toast({
      title: 'Chat exported',
      description: `Saved ${slug}.md`,
    });
  }, [currentSession, messages, toast]);

  const handleCopyChat = useCallback(async () => {
    if (!currentSession) {
      toast({
        title: 'No active chat',
        description: 'Select or start a chat before copying.',
        variant: 'destructive',
      });
      return;
    }

    const lines: string[] = [
      `${currentSession.title || 'Chat Conversation'}`,
      '',
      `Session ID: ${currentSession.id}`,
      `Copied: ${new Date().toISOString()}`,
      '',
    ];

    for (const message of messages) {
      const roleLabel = message.role === 'assistant' ? 'Karen' : message.role === 'user' ? 'User' : 'System';
      const when = message.timestamp instanceof Date
        ? message.timestamp.toLocaleString()
        : new Date(message.timestamp).toLocaleString();
      lines.push(`${roleLabel} (${when}):`);
      lines.push(message.content || '');
      lines.push('');
    }

    const text = lines.join('\n');
    try {
      await navigator.clipboard.writeText(text);
      toast({
        title: 'Chat copied',
        description: 'Conversation copied to clipboard.',
      });
    } catch {
      // Fallback for browsers that don't support clipboard API
      const textArea = document.createElement('textarea');
      textArea.value = text;
      document.body.appendChild(textArea);
      textArea.select();
      try {
        document.execCommand('copy');
        toast({
          title: 'Chat copied',
          description: 'Conversation copied to clipboard.',
        });
      } catch {
        toast({
          title: 'Copy failed',
          description: 'Unable to copy chat to clipboard.',
          variant: 'destructive',
        });
      }
      document.body.removeChild(textArea);
    }
  }, [currentSession, messages, toast]);

  // Handle external message injection (e.g. from plugins)
  useEffect(() => {
    const handleInjectMessage = (event: Event) => {
      const customEvent = event as CustomEvent;
      const { content, autoSubmit = false } = customEvent.detail;

      if (content) {
        if (autoSubmit) {
          void handleSubmit(content);
        } else {
          setInput(content);
        }
      }
    };

    window.addEventListener('karen:inject-message', handleInjectMessage);
    return () => window.removeEventListener('karen:inject-message', handleInjectMessage);
  }, [handleSubmit, setInput]);

  // Handle mic click
  const handleMicClick = useCallback(async () => {
    if (!speechRecognitionSupported) return;
    if (!recognitionRef.current) return;

    if (isRecording) {
      recognitionRef.current.stop();
    } else {
      try {
        setInput('');
        recognitionRef.current.start();
        setIsRecording(true);
      } catch (err) {
        console.error('Error starting mic:', err);
      }
    }
  }, [speechRecognitionSupported, isRecording, setInput, setIsRecording]);

  // Speech recognition setup
  useEffect(() => {
    if (typeof window === 'undefined') return;
    
    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionAPI) {
      setSpeechRecognitionSupported(false);
      return;
    }

    const recognitionInstance = new SpeechRecognitionAPI();
    recognitionInstance.continuous = false;
    recognitionInstance.interimResults = true;
    recognitionInstance.lang = 'en-US';

    recognitionInstance.onresult = (event: SpeechRecognitionEvent) => {
      let interimTranscript = '';
      let finalTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }
      setInput(finalTranscript || interimTranscript);
    };

    recognitionInstance.onerror = () => {
      setIsRecording(false);
    };

    recognitionInstance.onend = () => {
      setIsRecording(false);
      setShouldSubmitVoiceInput(true);
    };

    recognitionRef.current = recognitionInstance;

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
    };
  }, [setInput, setIsRecording, setShouldSubmitVoiceInput]);

  useEffect(() => {
    if (!shouldSubmitVoiceInput) {
      return;
    }

    setShouldSubmitVoiceInput(false);

    const voiceInput = input.trim();
    if (voiceInput && !isLoading && !isAuthLoading) {
      void handleSubmit(voiceInput);
    }
  }, [shouldSubmitVoiceInput, input, isLoading, isAuthLoading, handleSubmit]);

  const workspaceMessage = [...messages]
    .reverse()
    .find((message) =>
      message.role === 'assistant' &&
      (
        Boolean(message.structuredContent && Object.keys(message.structuredContent).length) ||
        Boolean(message.artifacts?.length) ||
        Boolean(message.attachments?.length) ||
        Boolean(message.sources?.length) ||
        Boolean(message.citations?.length)
      ),
    );

  return (
    <div data-testid="chat-root" className="flex min-h-0 flex-1 overflow-hidden">
      <div className="flex min-w-0 flex-1 flex-col">
      <StatusIndicators
        isBackendOffline={isBackendOffline}
        error={error}
        currentSession={currentSession}
        isLoading={isLoading}
        isLocalRecoveryUnconfirmed={isLocalRecoveryUnconfirmed}
      />

      <RuntimeMetadataPanel
        requestedProvider={latestAssistantMetadata.requestedProvider}
        actualProvider={latestAssistantMetadata.actualProvider}
        requestedModel={latestAssistantMetadata.requestedModel}
        actualModel={latestAssistantMetadata.actualModel}
        runtimeEngine={latestAssistantMetadata.runtimeEngine}
        fallbackLevel={latestAssistantMetadata.fallbackLevel}
        correlationId={latestAssistantMetadata.correlationId}
        requestId={latestAssistantMetadata.requestId}
        status={latestAssistantMetadata.status}
        responseSource={latestAssistantMetadata.responseSource}
        degradedMode={latestAssistantMetadata.degradedMode}
        degradationType={latestAssistantMetadata.degradationType}
        degradationReason={latestAssistantMetadata.degradedReason}
        providerAttempts={latestAssistantMetadata.providerAttempts}
        latencyMs={latestAssistantMetadata.latencyMs}
      />

      <CircuitBreakerWarning
        show={latestAssistantMetadata.showCircuitWarning}
        reason={latestAssistantMetadata.degradedReason}
      />

      {degradedMode.active && (
        <DegradedModeBanner
          reason={degradedMode.reason || "System operating in degraded mode"}
          fallbackPath={degradedMode.fallbackPath}
          onDismiss={() => setDegradedMode({ active: false })}
        />
      )}

      <MessagesArea
        messages={messages}
        onActionClick={handleActionClick}
        viewportRef={viewportRef}
        messagesContainerRef={messagesContainerRef}
      />

      {agentSteps.length > 0 && (
        <div className="mx-4 mb-4">
          <AgentActivityPanel steps={agentSteps} />
        </div>
      )}

      <ChatInput
        onSubmit={handleFormSubmit}
        displayedInputValue={displayedInputValue}
        onInputChange={setInput}
        onKeyDown={(e) => {
          if (
            showStopButton &&
            !isEditingDuringProcessing &&
            (e.key.length === 1 || e.key === 'Backspace' || e.key === 'Delete')
          ) {
            setIsEditingDuringProcessing(true);
            setInput('');
          }
        }}
        onPaste={(e) => {
          if (showStopButton && !isEditingDuringProcessing) {
            e.preventDefault();
            const pastedText = e.clipboardData.getData('text');
            setIsEditingDuringProcessing(true);
            setInput(pastedText);
          }
        }}
        isLoading={isLoading}
        isAuthLoading={isAuthLoading}
        isRecording={isRecording}
        isSuggestingStarter={isSuggestingStarter}
        isEditingDuringProcessing={isEditingDuringProcessing}
        isBackendOffline={isBackendOffline}
        speechRecognitionSupported={speechRecognitionSupported}
        showStopButton={showStopButton}
        onMicClick={handleMicClick}
        onSuggestStarter={handleSuggestStarter}
        onStopRequest={stopActiveRequest}
        selectableProviders={selectableProviders}
        providers={modelSettings?.providers ?? []}
        selectedProvider={selectedProvider}
        selectedModel={selectedModel}
        applyModelSelection={handleApplyModelSelection}
        isUpdatingModelSelection={isUpdatingModelSelection}
        sessions={sessions}
        currentSession={currentSession}
        isLoadingSessions={isLoadingSessions}
        error={error}
        loadSession={loadSession}
        deleteSession={deleteSession}
        deleteSessions={deleteSessions}
        updateSessionTitle={updateSessionTitle}
        refreshSessions={refreshSessions}
        createNewSession={createNewSession}
        onExportChat={handleExportCurrentChat}
        onCopyChat={handleCopyChat}
        streamingStatus={streamingStatus}
      />
      </div>

      <RichResultWorkspace message={workspaceMessage} />

      <ConversationContextRail
        metadata={latestAssistantMetadata.rawMetadata}
        agentSteps={agentSteps}
        approvals={actionableApprovals}
        approvalsLoadState={actionableApprovalsLoadState}
      />
    </div>
  );
}
