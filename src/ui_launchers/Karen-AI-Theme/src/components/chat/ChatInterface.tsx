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
// import AgentActivityPanel from './AgentActivityPanel';
import DegradedModeBanner from './DegradedModeBanner';
import RuntimeMetadataPanel from './RuntimeMetadataPanel';
import RuntimeReceipt from './RuntimeReceipt';
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
}

interface ChatInterfaceProps {
  isActive?: boolean;
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

const fetchConversationBootstrap = async (sessionId: string): Promise<ConversationResponse> => {
  const cached = takeConversationBootstrap(sessionId);
  if (cached) {
    return cached;
  }

  const existingRequest = sessionConversationBootstrapRequests.get(sessionId);
  if (existingRequest) {
    return existingRequest;
  }

  const request = apiClient.post<ConversationResponse>(`/api/conversations/ensure-session/${sessionId}`)
    .then((response) => {
      cacheConversationBootstrap(sessionId, response);
      return response;
    })
    .finally(() => {
      if (sessionConversationBootstrapRequests.get(sessionId) === request) {
        sessionConversationBootstrapRequests.delete(sessionId);
      }
    });

  sessionConversationBootstrapRequests.set(sessionId, request);
  return request;
};

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

  // Create a new session
  const createNewSession = useCallback(async () => {
    const sessionId = createSessionId();
    const newSession: Session = {
      id: sessionId,
      title: 'New Chat',
      createdAt: new Date(),
      updatedAt: new Date(),
      messageCount: 0,
      isActive: true,
    };
    
    setCurrentSession(newSession);
    setSessions(prev => [newSession, ...prev]);
    setError(null);
    persistActiveSessionId(sessionId);
  }, [persistActiveSessionId]);

  // Load a specific session
  const loadSession = useCallback(async (sessionId: string) => {
    setIsLoadingSessions(true);
    setError(null);
    
    try {
      // Load session metadata and history.
      // We use the same endpoint for both since ConversationResponse includes all metadata.
      const conversationResponse = await fetchConversationBootstrap(sessionId);
      
      const session: Session = {
        id: sessionId,
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
      };
      
      setCurrentSession(session);
      persistActiveSessionId(sessionId);
      
      // Update sessions list to mark this as active
      setSessions(prev => prev.map(s => ({
        ...s,
        isActive: s.id === sessionId
      })));
      
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 429)) {
        console.error('Failed to load session:', err);
      }

      // If session not found (404), explicit recovery
      if (err instanceof ApiError && err.status === 404) {
        console.warn('Session was not found on server, starting fresh.');
      } else if (err instanceof ApiError && err.status === 429) {
        console.warn('Session load was rate-limited, starting fresh session.');
      }
      
      setError('Failed to load session. Starting fresh chat.');
      
      // Fallback: create new session
      await createNewSession();
    } finally {
      setIsLoadingSessions(false);
    }
  }, [createNewSession, persistActiveSessionId]);

  // Refresh sessions list
  const refreshSessions = useCallback(async () => {
    setIsLoadingSessions(true);
    setError(null);
    
    try {
      const MAX_ATTEMPTS = 3;
      let response: ConversationApiResponse | null = null;
      let lastError: unknown = null;

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
        try {
          response = await apiClient.get<ConversationApiResponse>('/api/conversations');
          break;
        } catch (err) {
          lastError = err;
          const isRetryableRateLimit =
            err instanceof ApiError &&
            err.status === 429 &&
            attempt < MAX_ATTEMPTS;

          if (!isRetryableRateLimit) {
            throw err;
          }

          const delayMs = getRateLimitDelayMs(err, 1200);
          await new Promise((resolve) => window.setTimeout(resolve, delayMs));
        }
      }

      if (!response) {
        throw (lastError ?? new Error('Failed to fetch sessions'));
      }

      const sessionsData: Session[] = response.conversations?.map((session) => ({
        id: session.id,
        title: session.title || 'Untitled Chat',
        createdAt: new Date(session.created_at),
        updatedAt: new Date(session.updated_at),
        messageCount: session.message_count || 0,
        isActive: false, // Will be synced by separate effect
        lastMessage: session.messages && session.messages.length > 0 
          ? session.messages[session.messages.length - 1].content 
          : session.last_message
      })) || [];
      
      setSessions(sessionsData);
    } catch (err) {
      console.error('Failed to load sessions:', err);
      if (err instanceof ApiError && err.status === 429) {
        const retryMs = getRateLimitDelayMs(err, 2000);
        const retrySeconds = Math.max(1, Math.ceil(retryMs / 1000));
        setError(`Rate limited while refreshing sessions. Retrying shortly (about ${retrySeconds}s).`);
      } else {
        setError('Failed to load sessions list. Some features may be limited.');
      }
    } finally {
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

  // Session timeout and renewal handling
  useEffect(() => {
    const SESSION_TIMEOUT = 30 * 60 * 1000; // 30 minutes
    const RENEWAL_INTERVAL = 5 * 60 * 1000; // 5 minutes

    let timeoutId: number | undefined;
    let renewalId: number | undefined;

    const renewSession = async () => {
      try {
        const activeSession = currentSessionRef.current;
        if (activeSession) {
          // Use the update-activity endpoint which is implemented in the service
          await apiClient.post(`/api/conversations/update-session-activity/${activeSession.id}`);
          console.log('Session activity updated successfully');
        }
      } catch (err) {
        // Heartbeat failures are transient during backend startup or brief outages.
        // Keep the current session intact and let the next interval retry naturally.
        console.warn('Session activity update skipped:', err);
      }
    };

    const checkSessionTimeout = () => {
      const lastActivity = Date.now();
      const activeSession = currentSessionRef.current;
      const timeSinceLastActivity = lastActivity - (activeSession?.updatedAt.getTime() || lastActivity);
      
      if (timeSinceLastActivity > SESSION_TIMEOUT) {
        console.log('Session timed out, creating new session');
        createNewSession();
      }
    };

    if (currentSessionRef.current) {
      // Start renewal checks
      renewalId = window.setInterval(renewSession, RENEWAL_INTERVAL);
      
      // Start timeout checks
      timeoutId = window.setInterval(checkSessionTimeout, SESSION_TIMEOUT / 2);
    }

    // Update session activity on user interaction
    // We use a ref for currentSession inside the event listener to avoid re-registering
    const updateActivity = () => {
      setCurrentSession(prev => {
        if (!prev) return null;
        // Only update if at least 1 minute has passed to throttle state updates
        const now = new Date();
        if (now.getTime() - prev.updatedAt.getTime() < 60000) return prev;
        return { ...prev, updatedAt: now };
      });
    };

    // Add event listeners for user activity
    const events = ['mousedown', 'mousemove', 'keypress', 'scroll', 'touchstart'];
    events.forEach(event => {
      document.addEventListener(event, updateActivity, { passive: true });
    });

    return () => {
      if (typeof timeoutId === 'number') {
        window.clearInterval(timeoutId);
      }
      if (typeof renewalId === 'number') {
        window.clearInterval(renewalId);
      }
      events.forEach(event => {
        document.removeEventListener(event, updateActivity);
      });
    };
  }, [createNewSession]);

  // Delete a session
  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await apiClient.delete(`/api/conversations/${sessionId}`);

      // Update sessions list optimistically, then re-sync from server to avoid stale history.
      setSessions(prev => prev.filter(s => s.id !== sessionId));

      // If deleted session was current, create new one
      if (currentSession?.id === sessionId) {
        await createNewSession();
      }

      await refreshSessions();
      return true;
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError('Failed to delete session. Please try again.');
      return false;
    }
  }, [currentSession?.id, createNewSession, refreshSessions]);

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
        setSessions(prev => prev.filter(s => !deletedIds.has(s.id)));
      }

      if (currentSession && deletedIds.has(currentSession.id)) {
        await createNewSession();
      }

      if (deletedIds.size > 0) {
        await refreshSessions();
      }

      if (failedIds.length > 0) {
        setError(`Failed to delete ${failedIds.length} session${failedIds.length === 1 ? '' : 's'}. Please try again.`);
        return false;
      }

      return true;
    } catch (err) {
      console.error('Failed to delete sessions:', err);
      setError('Failed to delete some sessions. Please try again.');
      return false;
    }
  }, [currentSession, createNewSession, getRateLimitDelayMs, refreshSessions]);

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

  // Session cleanup for old/inactive sessions
  useEffect(() => {
    const CLEANUP_INTERVAL = 24 * 60 * 60 * 1000; // 24 hours
    const INACTIVE_THRESHOLD = 7 * 24 * 60 * 60 * 1000; // 7 days

    const cleanupSessions = async () => {
      try {
        const now = typeof window !== 'undefined' ? Date.now() : 0;
        const cutoffDate = new Date(now - INACTIVE_THRESHOLD);
        const inactiveSessions = sessionsRef.current.filter(session =>
          session.createdAt < cutoffDate && !session.isActive
        );

        if (inactiveSessions.length > 0) {
          console.log(`Cleaning up ${inactiveSessions.length} inactive sessions`);
          // Use for...of to avoid parallel setSessions updates that might complicate the loop
          for (const session of inactiveSessions) {
            await deleteSession(session.id).catch(err =>
              console.warn(`Failed to cleanup session ${session.id}:`, err)
            );
          }
        }
      } catch (err) {
        console.error('Session cleanup failed:', err);
      }
    };

    const cleanupId = window.setInterval(cleanupSessions, CLEANUP_INTERVAL);

    return () => {
      window.clearInterval(cleanupId);
    };
  }, [deleteSession]);

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


  const latestAssistantMetadata = useMemo(() => {
    const lastAssistant = [...messages].reverse().find((message) => message.role === 'assistant');
    const metadata = (lastAssistant?.metadata && typeof lastAssistant.metadata === 'object')
      ? lastAssistant.metadata as Record<string, unknown>
      : {};
    const llm = (metadata.llm && typeof metadata.llm === 'object')
      ? metadata.llm as Record<string, unknown>
      : {};

    const asText = (value: unknown): string | undefined =>
      typeof value === 'string' && value.trim() ? value.trim() : undefined;

    const degradedReasonRaw = asText(metadata.reason) || asText(metadata.degraded_reason) || asText(llm.reason);
    const degradedReason = getDegradationReasonLabel(degradedReasonRaw) || degradedReasonRaw;
    const statusRaw = asText(metadata.status);
    const status = getDegradationReasonLabel(statusRaw) || statusRaw;
    const responseSource = asText(llm.response_source) || asText(metadata.response_source);
    const fallbackLevel = asText(llm.fallback_level);
    const isEmergencyStatic = responseSource === 'emergency_static' || fallbackLevel === '99';
    const actualProvider = isEmergencyStatic
      ? undefined
      : asText(llm.actual_provider) || asText(llm.provider) || asText(metadata.actual_provider);
    const actualModel = isEmergencyStatic
      ? undefined
      : asText(llm.actual_model) || asText(llm.model_id) || asText(metadata.actual_model);

    return {
      requestedProvider: asText(llm.requested_provider) || asText(metadata.requested_provider),
      actualProvider,
      requestedModel: asText(llm.requested_model) || asText(metadata.requested_model),
      actualModel,
      runtimeEngine: isEmergencyStatic ? undefined : asText(metadata.execution_path) || asText(llm.runtime_engine),
      fallbackLevel,
      correlationId: asText(metadata.correlation_id),
      requestId: asText(metadata.request_id),
      status: isEmergencyStatic ? 'emergency unavailable' : status,
      responseSource,
      usedFallback: Boolean(llm.used_fallback || llm.is_fallback || metadata.used_fallback),
      degradedReason: isEmergencyStatic
        ? degradedReason || 'No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.'
        : degradedReason,
      showCircuitWarning: Boolean(metadata.circuit_breaker_open || metadata.dependency_degraded || degradedReason || isEmergencyStatic),
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
          title: 'Restored previous session',
          description: 'Picked up where you left off.',
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
        // Keep locally restored state if server sync fails.
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void restoreSessionState();

    return () => {
      cancelled = true;
    };
  }, [currentSession?.id, setMessages, setInput, toast]);

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
  const handleSubmit = useCallback(async (manualInput?: string) => {
    const rawInput = manualInput || input;
    if (!rawInput.trim() || isAuthLoading || submitInFlightRef.current) return;

    const trimmedInput = rawInput.trim();
    const lastAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant');
    const addressOptions = Array.isArray(lastAssistantMessage?.metadata?.addressOptions)
      ? (lastAssistantMessage.metadata.addressOptions as string[])
      : [];
    const matchedAddressOption = addressOptions.find(
      (option) => option.trim().toLowerCase() === trimmedInput.toLowerCase()
    );

    if (lastAssistantMessage?.metadata?.addressPreferencePrompt && matchedAddressOption) {
      setIsLoading(true);
      try {
        await savePreferredAddressName(matchedAddressOption);

        const userMessage: ChatMessage = {
          id: 'user-' + Date.now(),
          role: 'user',
          content: trimmedInput,
          timestamp: new Date(),
          status: 'completed',
        };
        const assistantMessage: ChatMessage = {
          id: 'assistant-pref-' + Date.now(),
          role: 'assistant',
          content: `Understood. I'll address you as ${matchedAddressOption} from now on.`,
          timestamp: new Date(),
          status: 'completed',
        };

        setMessages((prev) => [...prev, userMessage, assistantMessage]);
        setInput('');
      } catch {
        toast({
          title: 'Preference update failed',
          description: 'Karen could not save your preferred form of address.',
          variant: 'destructive',
        });
      } finally {
        setIsLoading(false);
      }
      return;
    }

    const userMessage: ChatMessage = {
      id: 'user-' + Date.now(),
      role: 'user',
      content: trimmedInput,
      timestamp: new Date(),
      status: 'pending',
    };
    setMessages((prev) => [...prev, userMessage]);
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

      // Backend metadata is the source of truth. No frontend enrichment for requested_provider/model.
      // If backend doesn't provide these fields, it means the provider wasn't honored or routing bypassed them.
      // This preserves transparency about what actually happened.

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

        const streamRequestPayload = {
          user_id: user?.user_id || 'anonymous',
          message: userMessage.content,
          top_k: 6,
          context: isAuthenticated && user
            ? {
                authenticated_user: {
                  user_id: user.user_id,
                  email: user.email,
                  full_name: user.full_name,
                  tenant_id: user.tenant_id,
                  roles: user.roles,
                },
                conversation_profile: {
                  display_name: displayName,
                  preferred_address_name: preferredAddressName || undefined,
                  source: 'authenticated_profile',
                },
                recent_messages: recentMessages,
              }
            : {
                conversation_profile: {
                  display_name: displayName,
                  preferred_address_name: preferredAddressName || undefined,
                  source: displayName ? 'derived_profile' : 'unknown',
                },
                recent_messages: recentMessages,
              },
          preferred_llm_provider: preferredProvider,
          preferred_model: preferredModel,
          preferred_provider: preferredProvider,
          session_id: sessionIdRef.current,
        };

      await apiClient.postStream(
        '/api/copilot/assist/stream',
        streamRequestPayload,
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
        },
        controller.signal,
      );

         if (streamFailed) {
           const errorMessage = streamFailureMessage || processingStatus || 'Streaming endpoint reported an error';
           throw new Error(errorMessage);
         }

        setIsBackendOffline(false);

        const fullContent = (completionContent || collectedContent).trim();

        if (!fullContent) {
          throw new Error('Empty response from streaming endpoint');
        }

        // Validate backend metadata completeness
        const finalMetadata = completedMetadata || enrichStreamMetadata();
        const llmMetadata = typeof finalMetadata.llm === 'object' && finalMetadata.llm !== null && !Array.isArray(finalMetadata.llm)
          ? finalMetadata.llm as Record<string, unknown>
          : {};

        if (preferredProvider && !llmMetadata?.requested_provider) {
          console.warn(
            `[ChatInterface] Backend did not provide requested_provider. ` +
            `Sent: ${preferredProvider}, Expected in metadata.llm.requested_provider. ` +
            `This may indicate provider routing bypassed or unavailable.`
          );
        }

        const streamResponse = {
          answer: fullContent,
          correlationId: completedMetadata?.correlation_id as string || undefined,
          actions: (completedMetadata?.actions as SuggestedAction[]) || [],
          metadata: finalMetadata,
        };

        const streamAssistantMessage: ChatMessage = {
          id: streamResponse.correlationId || 'assistant-' + Date.now(),
          role: 'assistant',
          content: streamResponse.answer,
          timestamp: new Date(),
          status: 'completed',
          actions: streamResponse.actions,
          metadata: {
            ...streamResponse.metadata,
            citations: collectedCitations,
            agentSteps: collectedAgentSteps,
            degradedMode: degradedModeSnapshot.active,
          },
          citations: collectedCitations,
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

      const noActiveCloudProvidersMessage =
        'No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.';

      const errorAssistantMessage: ChatMessage | null = fallbackErrorResponse ? {
        id: fallbackErrorResponse.correlationId || 'assistant-error-' + Date.now(),
        role: 'assistant',
        content: fallbackErrorResponse.answer,
        timestamp: new Date(),
        status: 'completed',
        structuredContent: fallbackErrorResponse.structuredContent,
        actions: fallbackErrorResponse.actions,
        metadata: fallbackErrorResponse.metadata,
      } : null;

      setMessages((prev) => {
        // Update user message to failed
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
              description: (() => {
                const message = getDegradedResponseMessage(error);
                if (
                  message.includes('No active cloud providers are configured') ||
                  message.includes('Built-in runtimes may still be available')
                ) {
                  return message;
                }

                const raw = error instanceof Error ? error.message : '';
                if (
                  raw.toLowerCase().includes('no configured provider could generate a response') ||
                  raw.toLowerCase().includes('expression engine is currently inactive')
                ) {
                  return noActiveCloudProvidersMessage;
                }

                return message;
              })(),
              variant: 'destructive',
            },
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

  }, [input, isAuthLoading, messages, displayName, preferredAddressName, recentMessages, selectedProvider, selectedModel, toast, user, setInput, setMessages, setIsLoading, setIsEditingDuringProcessing, setProcessingStatus, setStreamedContent, setStreamingMetrics, activeRequestControllerRef, sessionIdRef, isAuthenticated, processingStatus, savePreferredAddressName, scrollChatToBottom]);

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
  const handleActionClick = useCallback((action: SuggestedAction) => {
    const messageText = action.description || action.type;
    if (!messageText) return;
    if (action.type === 'routing.profile.list') {
      setInput('List all available profiles');
      handleSubmit('List all available profiles');
      return;
    }
    setInput(messageText);
    handleSubmit(messageText);
  }, [setInput, handleSubmit]);

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

  const handleShareChat = useCallback(async () => {
    if (!currentSession) {
      toast({
        title: 'No active chat',
        description: 'Select or start a chat before sharing.',
        variant: 'destructive',
      });
      return;
    }

    const shareUrl = `${window.location.origin}/chat/${currentSession.id}`;
    const shareText = `Check out this conversation with Karen AI: ${currentSession.title || 'Chat'}`;

    try {
      if (navigator.share) {
        await navigator.share({
          title: currentSession.title || 'Karen AI Chat',
          text: shareText,
          url: shareUrl,
        });
      } else {
        // Fallback: copy shareable link to clipboard
        await navigator.clipboard.writeText(`${shareText}\n\n${shareUrl}`);
        toast({
          title: 'Share link copied',
          description: 'Shareable link copied to clipboard.',
        });
      }
    } catch {
      toast({
        title: 'Share failed',
        description: 'Unable to share chat. Link copied to clipboard as fallback.',
        variant: 'destructive',
      });
      try {
        await navigator.clipboard.writeText(`${shareText}\n\n${shareUrl}`);
      } catch {
        console.error('Failed to copy share link');
      }
    }
  }, [currentSession, toast]);

  const handleClearChat = useCallback(async () => {
    if (!currentSession) {
      toast({
        title: 'No active chat',
        description: 'Select or start a chat before clearing.',
        variant: 'destructive',
      });
      return;
    }

    // Clear messages but keep the session
    setMessages([]);
    setStreamedContent('');

    toast({
      title: 'Chat cleared',
      description: 'All messages have been removed from this chat.',
    });
  }, [currentSession, setMessages, setStreamedContent, toast]);

  const handleSearchInChat = useCallback(() => {
    // Focus search input if it exists, otherwise show a message
    const searchInput = document.querySelector('[data-chat-search]') as HTMLInputElement;
    if (searchInput) {
      searchInput.focus();
    } else {
      toast({
        title: 'Search not available',
        description: 'Chat search functionality is not yet implemented.',
      });
    }
  }, [toast]);

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

  return (
    <div data-testid="chat-root" className="flex flex-col flex-1">
      <StatusIndicators
        isBackendOffline={isBackendOffline}
        error={error}
        currentSession={currentSession}
        isLoading={isLoading}
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
      />

      <RuntimeReceipt
        source={latestAssistantMetadata.responseSource}
        usedFallback={latestAssistantMetadata.usedFallback}
        degradedReason={latestAssistantMetadata.degradedReason}
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

      {/* Legacy AgentActivityPanel removed to simplify UI */}
      {/* 
      {agentSteps.length > 0 && (
        <div className="mx-4 mb-4">
          <AgentActivityPanel steps={agentSteps} />
        </div>
      )}
      */}

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
        onShareChat={handleShareChat}
        onClearChat={handleClearChat}
        onSearchInChat={handleSearchInChat}
        streamingStatus={streamingStatus}
      />
    </div>
  );
}
