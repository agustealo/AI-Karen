"use client";

import { useState, useRef, useEffect, useCallback, createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { ChatMessage, ConversationResponse } from "@/lib/types";
import type { SuggestedAction } from "@/lib/agent-ui/service";
import { ApiError, apiClient } from "@/lib/api";

const createSessionId = (): string => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  throw new Error("Secure conversation ID generation is unavailable");
};

const removeSessionState = (sessionId: string): void => {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(`karen.chat.session_state.${sessionId}`);
  } catch {
    // Server-side conversation deletion remains authoritative.
  }
};

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
  workspaceRunId: string | null;
  setWorkspaceRunId: (runId: string | null) => void;
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

export const fetchConversationBootstrap = async (conversationId: string): Promise<ConversationResponse> => {
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

const fetchConversationByLegacySession = async (sessionId: string): Promise<ConversationResponse> =>
  apiClient.get<ConversationResponse>(`/api/conversations/by-session/${sessionId}`);

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
  /** Fail closed instead of recovering to another conversation on an explicitly scoped acceptance URL. */
  strictInitialSession?: boolean;
}

export function SessionProvider({ children, initialSessionId, strictInitialSession = false }: SessionProviderProps) {
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [workspaceRunId, setWorkspaceRunId] = useState<string | null>(null);
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
    setWorkspaceRunId(null);
    const sessionId = createSessionId();
    setIsLoadingSessions(true);
    if (!strictInitialSession) setError(null);

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
    if (currentSessionRef.current?.id !== sessionId) setWorkspaceRunId(null);
    setIsLoadingSessions(true);
    setError(null);

    const preserveRequestedSession = (message: string) => {
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
        return exists
          ? prev.map((session) => ({
              ...session,
              isActive: session.id === sessionId,
            }))
          : [preservedSession, ...prev.map((session) => ({ ...session, isActive: false }))];
      });
      persistActiveSessionId(sessionId);
      setError(message);
    };

    try {
      const MAX_ATTEMPTS = 3;
      let conversationResponse: ConversationResponse | null = null;
      let lastError: unknown = null;

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
        try {
          conversationResponse = await fetchConversationBootstrap(sessionId);
          break;
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            try {
              conversationResponse = await fetchConversationByLegacySession(sessionId);
              break;
            } catch (legacyErr) {
              if (!(legacyErr instanceof ApiError && legacyErr.status === 404)) {
                throw legacyErr;
              }
            }
          }

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
      if (strictInitialSession && conversationId !== sessionId) {
        throw new Error('Strict conversation identity mismatch');
      }
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
      if (strictInitialSession) {
        // An acceptance URL must never create a different conversation or
        // project an unverified ID into a locally fabricated chat session.
        setCurrentSession(null);
        setError('The requested conversation could not be verified. No replacement conversation was created.');
        return;
      }
      if (err instanceof ApiError && err.status === 429) {
        preserveRequestedSession(
          'Session service is temporarily rate limited. Keeping your current chat available.',
        );
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

      console.warn('Session load failed transiently; preserving the requested conversation.', err);
      preserveRequestedSession(
        'Session service is temporarily unavailable. Keeping your current chat available.',
      );
      return;
    } finally {
      setIsLoadingSessions(false);
    }
  }, [
    createNewSession,
    getRateLimitDelayMs,
    persistActiveSessionId,
    strictInitialSession,
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
        if (!strictInitialSession) setError('Session list is temporarily rate limited. Your current chat remains available.');
        console.warn('Session list refresh was rate-limited; preserving existing session state.');
      } else {
        console.error('Failed to load sessions:', err);
        if (!strictInitialSession) setError('Failed to load sessions list. Some features may be limited.');
      }
    } finally {
      sessionListRefreshInFlightRef.current = null;
      setIsLoadingSessions(false);
    }
  }, [getRateLimitDelayMs, strictInitialSession]);

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
    const activeRuntimeSessionId = currentSession?.runtimeSessionId;
    if (!activeRuntimeSessionId) {
      return;
    }

    const RENEWAL_INTERVAL = 5 * 60 * 1000; // 5 minutes

    const renewSession = async () => {
      try {
        await apiClient.post(`/api/conversations/update-session-activity/${activeRuntimeSessionId}`);
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
  }, [currentSession?.runtimeSessionId]);

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
      workspaceRunId,
      setWorkspaceRunId,
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

