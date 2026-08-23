"use client";

import type { RuntimeProviderCatalogResponse } from '@/lib/model-runtime-inventory';

// API service for HTTP requests
const SAME_ORIGIN_API_BASE_URL = '';

export class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export interface StreamEvent {
  type: 'status' | 'content' | 'error' | 'complete' | 'agent_step' | 'tool' | 'citation' | 'warning' | 'approval';
  content: string;
  correlation_id: string;
  metadata?: Record<string, unknown>;
  event_id?: string;
  sequence?: number;
  request_id?: string;
  response_id?: string;
  conversation_id?: string;
  timestamp?: string;
}

export interface StreamingMetrics {
  startTime: number;
  chunksReceived: number;
  totalBytes: number;
  lastChunkTime: number;
  connectionHealth: 'excellent' | 'good' | 'poor' | 'critical';
}

export type AgentStepEventType =
  | 'agent_step_started'
  | 'agent_step_completed'
  | 'tool_execution_started'
  | 'tool_execution_completed'
  | 'web_search_started'
  | 'web_search_sources_found'
  | 'extension_execution_started'
  | 'extension_execution_completed'
  | 'citation_bundle_ready'
  | 'degraded_mode_entered';

export interface AgentStepEvent {
  type: AgentStepEventType;
  step_id: string;
  action_type?: string;
  correlation_id?: string;
  timestamp?: string;
  metadata?: Record<string, unknown>;
}

export interface Citation {
  id: string;
  url: string;
  title: string;
  snippet: string;
  index: number;
  metadata?: Record<string, unknown>;
}

export interface AssistStreamCallbacks {
  onStatus?: (message: string, metadata?: Record<string, unknown>) => void;
  onContent?: (token: string) => void;
  onError?: (message: string) => void;
  onComplete?: (metadata?: Record<string, unknown>, content?: string) => void;
  onDone?: () => void;
  onMetrics?: (metrics: StreamingMetrics) => void;
  onAgentStep?: (event: AgentStepEvent) => void;
  onCitationBundle?: (citations: Citation[]) => void;
}

class ApiClient {
  private readonly SESSION_MARKER_KEY = 'kari_session_expected';
  private readonly SESSION_WARNING_SHOWN_KEY = 'session_warning_shown';
  private readonly TOKEN_REFRESH_ATTEMPTED_KEY = 'token_refresh_attempted';

  private formatApiErrorMessage(payload: unknown, fallback: string): string {
    if (typeof payload === 'string') {
      const trimmed = payload.trim();
      return trimmed || fallback;
    }

    if (payload && typeof payload === 'object') {
      const record = payload as Record<string, unknown>;
      const preferredKeys = ['user_message', 'message', 'detail', 'error'];

      for (const key of preferredKeys) {
        const value = record[key];
        if (typeof value === 'string' && value.trim()) {
          return value.trim();
        }
      }

      try {
        return JSON.stringify(payload);
      } catch {
        return fallback;
      }
    }

    if (payload == null) {
      return fallback;
    }

    return String(payload);
  }

  private isTransientError(error: unknown): boolean {
    if (!(error instanceof Error)) return false;
    const msg = error.message;
    return (
      msg.includes('502') ||
      msg.includes('503') ||
      msg.includes('504') ||
      msg.includes('fetch') ||
      msg.includes('timeout') ||
      msg.includes('Database unavailable') ||
      msg.includes('Session not found in memory')
    );
  }

  private async sleep(ms: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms));
  }

  private async retryWithExponentialBackoff<T>(
    operation: () => Promise<T>,
    maxRetries: number = 3,
    baseDelay: number = 1000,
    shouldRetry: (error: unknown) => boolean
  ): Promise<T> {
    let lastError: unknown;
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        return await operation();
      } catch (error) {
        lastError = error;
        if (attempt < maxRetries && shouldRetry(error)) {
          const delay = baseDelay * Math.pow(2, attempt);
          console.log(`[ApiClient] Retrying after ${delay}ms (attempt ${attempt + 1}/${maxRetries + 1})`);
          await this.sleep(delay);
        } else {
          throw error;
        }
      }
    }
    throw lastError;
  }

  private isBrowser(): boolean {
    return typeof window !== 'undefined' && (!!window.document || !!window.navigator);
  }

  private forceBrowserRelativeApiUrl(url: string): string {
    if (!this.isBrowser()) {
      return url;
    }

    if (url.startsWith('/')) {
      return url;
    }

    // Handle protocol-relative URLs (//api:8000/api/auth/me)
    if (url.startsWith('//')) {
      const apiIndex = url.indexOf('/api/');
      if (apiIndex >= 0) {
        return url.slice(apiIndex);
      }
      return url;
    }

    try {
      const parsed = new URL(url, window.location.origin);
      return `${parsed.pathname}${parsed.search}${parsed.hash}`;
    } catch {
      const apiIndex = url.indexOf('/api/');
      if (apiIndex >= 0) {
        return url.slice(apiIndex);
      }
      return url;
    }
  }

  /**
   * Determine the preferred base URL.
   * In a browser context, we return an empty string to force relative paths
   * which are then handled by the Next.js local proxy.
   */
  private getPreferredBaseUrl(): string {
    if (this.isBrowser()) {
      const env = (process as unknown as { env?: Record<string, string> }).env || {};
      // If NEXT_PUBLIC_API_BASE_URL is explicitly set, use it for direct API calls
      if (env.NEXT_PUBLIC_API_BASE_URL) {
        console.log('[ApiClient] Browser context, using configured API URL:', env.NEXT_PUBLIC_API_BASE_URL);
        return env.NEXT_PUBLIC_API_BASE_URL.replace(/\/$/, '');
      }
      console.log('[ApiClient] Browser context, forcing relative URLs');
      return '';
    }

    // Server-side only
    const env = (process as unknown as { env?: Record<string, string> }).env || {};
    if (env.KAREN_DOCKER === 'true' || env.KARI_DOCKER === 'true' || 
        env.HOSTNAME?.includes('api') || env.HOSTNAME?.includes('web')) {
      return 'http://api:8000';
    }
    
    return (env.KAREN_BACKEND_URL || env.NEXT_PUBLIC_API_BASE_URL || env.API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
  }

  private getFallbackBaseUrl(preferredBaseUrl: string): string | null {
    if (this.isBrowser()) {
      return null;
    }

    const env = (process as unknown as { env?: Record<string, string> }).env || {};
    const configuredBackendUrl = (env.KAREN_BACKEND_URL || env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '');
    
    if (preferredBaseUrl === SAME_ORIGIN_API_BASE_URL) {
      return configuredBackendUrl || null;
    }
    
    return SAME_ORIGIN_API_BASE_URL || null;
  }

  private hasFallbackBaseUrl(baseUrl: string | null): baseUrl is string {
    return baseUrl !== null && baseUrl !== '';
  }

  /**
   * Build the final URL, ensuring that Docker-internal hostnames are stripped
   * when running in a browser context to avoid ERR_NAME_NOT_RESOLVED.
   */
  private buildUrl(baseUrl: string | null, endpoint: string): string {
    const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    
    // Aggressive browser-side URL hardening
    if (this.isBrowser()) {
      const dockerHostPattern = /https?:\/\/(api|api-copilot|172\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|host\.docker\.internal)(:\d+)?/gi;
      
      let finalUrl = baseUrl ? `${baseUrl}${normalizedEndpoint}` : normalizedEndpoint;
      console.log(`[ApiClient] buildUrl - Base: ${baseUrl}, Endpoint: ${endpoint}, Initial: ${finalUrl}`);
      
      // If it's an absolute URL pointing to internal Docker hosts, strip it
      if (finalUrl.startsWith('http')) {
        finalUrl = finalUrl.replace(dockerHostPattern, '');
        console.log(`[ApiClient] buildUrl - After stripping Docker hosts: ${finalUrl}`);
      }
      
      // If we are in the browser and the URL is still absolute to 'api', force it to relative
      if (finalUrl.includes('://api')) {
         finalUrl = finalUrl.substring(finalUrl.indexOf('/api/'));
         console.log(`[ApiClient] buildUrl - After forcing relative API path: ${finalUrl}`);
      }

      // Ensure it starts with /api if it's a relative path to our backend
      if (!finalUrl.startsWith('http') && !finalUrl.startsWith('/')) {
        finalUrl = '/' + finalUrl;
        console.log(`[ApiClient] buildUrl - After ensuring leading slash: ${finalUrl}`);
      }
      
      return finalUrl;
    }

    // Server-side logic
    if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
      return endpoint;
    }

    return `${baseUrl || ''}${normalizedEndpoint}`;
  }

  private shouldRetryWithSameOrigin(error: unknown): boolean {
    return this.isBrowser() && error instanceof TypeError;
  }

  private shouldRetryWithDirectBackend(response: Response, fallbackBaseUrl: string | null): boolean {
    return (
      this.isBrowser() &&
      this.hasFallbackBaseUrl(fallbackBaseUrl) &&
      response.status >= 500
    );
  }

  private shouldRetryMissingApiRoute(endpoint: string, response: Response, fallbackBaseUrl: string | null): boolean {
    return (
      this.isBrowser() &&
      this.hasFallbackBaseUrl(fallbackBaseUrl) &&
      endpoint.startsWith('/api/') &&
      response.status === 404
    );
  }

  private shouldRetryAssistServerError(endpoint: string, response: Response): boolean {
    return (
      this.isBrowser() &&
      endpoint === '/api/copilot/assist' &&
      response.status >= 500
    );
  }

  private hasSessionMarker(): boolean {
    if (typeof window === 'undefined') return false;
    try {
      return localStorage.getItem(this.SESSION_MARKER_KEY) === 'true';
    } catch {
      return false;
    }
  }

  private shouldPreferCookieSession(): boolean {
    return this.isBrowser() && this.hasSessionMarker();
  }

  private getTimeUntilTokenExpiry(token: string): number | null {
    try {
      const expTime = this.getTokenExpirationTime(token);
      if (!expTime) return null;
      return expTime - (Date.now() / 1000);
    } catch {
      return null;
    }
  }

  private shouldShowSessionWarning(token: string): boolean {
    const timeUntilExpiry = this.getTimeUntilTokenExpiry(token);
    if (!timeUntilExpiry) return false;

    // Show warning if expires within 30 minutes
    const warningThreshold = 30 * 60; // 30 minutes in seconds
    return timeUntilExpiry <= warningThreshold && timeUntilExpiry > 0;
  }

  private hasShownSessionWarning(): boolean {
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(this.SESSION_WARNING_SHOWN_KEY) === 'true';
  }

  private markSessionWarningShown(): void {
    if (typeof window !== 'undefined') {
      localStorage.setItem(this.SESSION_WARNING_SHOWN_KEY, 'true');
    }
  }

  private clearSessionWarningFlag(): void {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(this.SESSION_WARNING_SHOWN_KEY);
    }
  }

  public async checkSessionStatus(): Promise<{
    isValid: boolean;
    timeUntilExpiry: number | null;
    shouldShowWarning: boolean;
    isExpired: boolean;
  }> {
    try {
      const accessToken = localStorage.getItem('access_token');
      if (!accessToken) {
        return { isValid: false, timeUntilExpiry: null, shouldShowWarning: false, isExpired: true };
      }

      const timeUntilExpiry = this.getTimeUntilTokenExpiry(accessToken);
      const isExpired = this.isTokenExpired(accessToken);
      const shouldShowWarning = !isExpired && this.shouldShowSessionWarning(accessToken);

      return {
        isValid: !isExpired,
        timeUntilExpiry,
        shouldShowWarning,
        isExpired
      };
    } catch {
      return { isValid: false, timeUntilExpiry: null, shouldShowWarning: false, isExpired: true };
    }
  }

  private async getAuthHeaders(): Promise<Record<string, string>> {
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      };

      const accessToken = localStorage.getItem('access_token');
      console.log('[ApiClient] getAuthHeaders called; token present:', !!accessToken);

      if (accessToken) {
        const expTime = this.getTokenExpirationTime(accessToken);
        const now = Date.now() / 1000;
        const timeUntilExpiry = expTime ? expTime - now : 0;

        // Check for session warning
        if (timeUntilExpiry > 0 && timeUntilExpiry <= 1800 && !this.hasShownSessionWarning()) { // 30 minutes
          console.log('[ApiClient] Session expires soon, should show warning');
          // Dispatch custom event for UI to show session warning
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('sessionWarning', {
              detail: { timeUntilExpiry }
            }));
            this.markSessionWarningShown();
          }
        }

        // Refresh proactively if token expires within 10 minutes
        if (timeUntilExpiry > 0 && timeUntilExpiry <= 600) { // 10 minutes
          console.log('[ApiClient] Token expires soon, refreshing proactively');
          try {
            await this.refreshAccessToken();
            const newToken = localStorage.getItem('access_token');
            if (newToken) {
              headers['Authorization'] = `Bearer ${newToken}`;
              // Clear warning flag on successful refresh
              this.clearSessionWarningFlag();
            }
          } catch (error) {
            console.warn('[ApiClient] Proactive token refresh failed:', error);
            // Continue with current token, let backend handle expiry
            headers['Authorization'] = `Bearer ${accessToken}`;
          }
        } else if (this.isTokenExpired(accessToken)) {
          console.log('[ApiClient] Access token expired, attempting refresh');
          try {
            await this.refreshAccessToken();
            const newToken = localStorage.getItem('access_token');
            if (newToken) {
              headers['Authorization'] = `Bearer ${newToken}`;
            }
          } catch (error) {
            console.warn('[ApiClient] Token refresh failed during expiry check:', error);
            
            if (this.isTransientError(error)) {
              console.warn('[ApiClient] Transient failure during token refresh. Preserving local auth state.');
              headers['Authorization'] = `Bearer ${accessToken}`; // Try with current token anyway
            } else {
              // Terminal failure - Clear auth state
              localStorage.removeItem('access_token');
              localStorage.removeItem('refresh_token');
              localStorage.removeItem('user_data');
              if (typeof window !== 'undefined') {
                window.location.href = '/login';
              }
            }
            return headers;
          }
        } else {
          console.log('[ApiClient] Using access token for Authorization header');
          headers['Authorization'] = `Bearer ${accessToken}`;
        }
      } else {
        console.log('[ApiClient] No access token available; relying on cookie session if present');
      }
      return headers;
    } catch {
      return { 'Content-Type': 'application/json' };
    }
  }

  private isTokenExpired(token: string): boolean {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      // Consider token expired if it expires within the next 5 minutes
      const bufferTime = 5 * 60; // 5 minutes in seconds
      return (payload.exp - bufferTime) < Date.now() / 1000;
    } catch {
      return true;
    }
  }

  private getTokenExpirationTime(token: string): number | null {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp;
    } catch {
      return null;
    }
  }

  private async refreshAccessToken(): Promise<void> {
    try {
      const refreshToken = localStorage.getItem('refresh_token');
      if (!refreshToken) throw new Error('No refresh token available');

      const sendRefresh = async (baseUrl: string | null): Promise<Response> =>
        fetch(this.buildUrl(baseUrl, '/api/auth/refresh'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

      const preferredBaseUrl = this.getPreferredBaseUrl();
      const fallbackBaseUrl = this.getFallbackBaseUrl(preferredBaseUrl);

      let response: Response;
      try {
        response = await sendRefresh(preferredBaseUrl);
      } catch (error) {
        if (!this.shouldRetryWithSameOrigin(error) || !fallbackBaseUrl) throw error;
        response = await sendRefresh(fallbackBaseUrl);
      }

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Token refresh failed');
        throw new Error(`Token refresh failed: ${response.status} ${errorText}`);
      }

      const data = await response.json();
      if (!data.access_token) {
        throw new Error('Invalid refresh response: missing access_token');
      }

      localStorage.setItem('access_token', data.access_token);
      // Clear any refresh attempt flags on success
      localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);
      this.clearSessionWarningFlag();
    } catch (error) {
      if (this.isTransientError(error)) {
        console.warn('[ApiClient] Token refresh temporarily unavailable:', error);
      } else {
        console.error('[ApiClient] Token refresh failed:', error);
      }
      // Do not clear auth state here; callers decide how to handle 401.
      // This prevents accidental hard logout during transient refresh issues.
      throw error;
    }
  }

  private async request<T>(endpoint: string, init: RequestInit = {}, skipAuth: boolean = false): Promise<T> {
    const send = async (baseUrl: string | null): Promise<Response> => {
      const authHeaders = skipAuth ? {} : await this.getAuthHeaders();
      const requestHeaders = {
        ...authHeaders,
        ...((init.headers as Record<string, string> | undefined) || {}),
      };

      const url = this.forceBrowserRelativeApiUrl(this.buildUrl(baseUrl, endpoint));
      console.log(`[ApiClient] Request: ${url} (Base: ${baseUrl}, Endpoint: ${endpoint})`);
      
      try {
        return await fetch(url, {
          ...init,
          headers: requestHeaders,
          credentials: 'include',
        });
      } catch (err) {
        console.error(`[ApiClient] Network error for ${url}:`, err);
        throw err;
      }
    };

    const preferredBaseUrl = this.getPreferredBaseUrl();
    const fallbackBaseUrl: string | null = this.getFallbackBaseUrl(preferredBaseUrl) || null;

    let response: Response;
    try {
      response = await send(preferredBaseUrl);
    } catch (error) {
      if (!this.shouldRetryWithSameOrigin(error) || !this.hasFallbackBaseUrl(fallbackBaseUrl)) throw error;
      response = await send(fallbackBaseUrl);
    }

    // Logic for retries (500s or 404s on API routes)
    if (this.shouldRetryWithDirectBackend(response, fallbackBaseUrl) ||
        this.shouldRetryMissingApiRoute(endpoint, response, fallbackBaseUrl)) {
      response = await send(fallbackBaseUrl);
    }

    // 401 Handling - Only redirect to login as last resort
    if (response.status === 401) {
      const hasTriedRefresh = localStorage.getItem(this.TOKEN_REFRESH_ATTEMPTED_KEY) === 'true';

      if (!hasTriedRefresh) {
        console.log('[ApiClient] 401 received, attempting token refresh');
        localStorage.setItem(this.TOKEN_REFRESH_ATTEMPTED_KEY, 'true');

        try {
          await this.refreshAccessToken();
          // Retry the original request with new token
          response = await send(preferredBaseUrl);
          if (this.shouldRetryWithDirectBackend(response, fallbackBaseUrl) ||
              this.shouldRetryMissingApiRoute(endpoint, response, fallbackBaseUrl)) {
            response = await send(fallbackBaseUrl);
          }

          // Clear the refresh attempt flag on success
          if (response.ok) {
            localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);
          }
        } catch (refreshError) {
          if (this.isTransientError(refreshError)) {
            console.warn('[ApiClient] Token refresh failed due to transient/degraded state. Preserving auth state.');
            // Let it fall through to the normal error handling below, don't clear auth
            localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);
          } else {
            console.warn('[ApiClient] Token refresh failed for 401, redirecting to login:', refreshError);
            localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);

            // Only redirect to login after refresh failure
            if (typeof window !== 'undefined') {
              // Clear auth data
              localStorage.removeItem('access_token');
              localStorage.removeItem('refresh_token');
              localStorage.removeItem('user_data');
              this.clearSessionWarningFlag();
              window.location.href = '/login';
            }
            return undefined as T; // Don't throw, let redirect happen
          }
        }
      } else {
        // Already tried refresh, this is a genuine auth failure
        console.warn('[ApiClient] 401 after refresh attempt, redirecting to login');
        localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);

        if (typeof window !== 'undefined') {
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          localStorage.removeItem('user_data');
          this.clearSessionWarningFlag();
          window.location.href = '/login';
        }
        return undefined as T; // Don't throw, let redirect happen
      }
    } else {
      // Clear refresh attempt flag on non-401 responses
      localStorage.removeItem(this.TOKEN_REFRESH_ATTEMPTED_KEY);
    }

    // 500 Retry for Copilot Assist
    if (!response.ok && this.shouldRetryAssistServerError(endpoint, response)) {
      await this.sleep(250);
      response = await send(preferredBaseUrl);
    }

    // 502 Retry with backoff for startup timing issues
    if (response.status === 502) {
      console.log('[ApiClient] 502 Bad Gateway detected, retrying with backoff for startup timing');
      await this.sleep(2000); // Wait 2s before retry
      try {
        response = await send(preferredBaseUrl);
        if (this.shouldRetryWithDirectBackend(response, fallbackBaseUrl) ||
            this.shouldRetryMissingApiRoute(endpoint, response, fallbackBaseUrl)) {
          response = await send(fallbackBaseUrl);
        }
      } catch (retryError) {
        console.warn('[ApiClient] Retry after 502 failed:', retryError);
        // Continue with original 502 response for error handling
      }
    }

    if (!response.ok) {
      const rawText = await response.text().catch(() => '');
      let errorData: Record<string, unknown> = {};
      try {
        errorData = JSON.parse(rawText);
      } catch {
        errorData = { detail: rawText.trim() };
      }
      const fallbackMessage = `HTTP ${response.status}: ${response.statusText}`;
      const errorPayload = errorData.detail ?? errorData.message ?? errorData.error ?? rawText;

      const isDegradedMode = 
        errorData.degraded_mode === true ||
        (errorData.metadata && (errorData.metadata as Record<string, unknown>).degraded_mode === true) ||
        response.headers.get('x-degraded-mode') === 'true';

      // Handle 401 errors by redirecting to login
      if (response.status === 401 && typeof window !== 'undefined') {
        if (!isDegradedMode) {
          console.warn('[ApiClient] Authentication failed, redirecting to login');
          // Clear any remaining auth data
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          localStorage.removeItem('user_data');
          // Redirect to login page
          window.location.href = '/login';
          // Don't throw error, let the redirect happen
          return undefined as T;
        } else {
          // If it's a 401 but in degraded mode, we just throw the ApiError instead of redirecting
          throw new ApiError(
            response.status,
            this.formatApiErrorMessage(errorData, fallbackMessage),
            errorData,
          );
        }
      }

      // Provide user-friendly message for 502 Bad Gateway (startup timing)
      const errorMessage = response.status === 502
        ? 'The backend service is starting up. Please wait a moment and try again.'
        : this.formatApiErrorMessage(errorPayload, fallbackMessage);

      throw new ApiError(
        response.status,
        errorMessage,
        errorData,
      );
    }

    if (response.status === 204) return undefined as T;
    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  /**
   * Get the unified provider catalog from the backend.
   * This is the single source of truth for all provider/model selection UI.
   */
  async getRuntimeProviderCatalog(): Promise<RuntimeProviderCatalogResponse> {
    return this.get('/api/runtime/providers');
  }

  async get<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint);
  }

  async getUnauthenticated<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, {}, true);
  }

  async post<T>(endpoint: string, data?: unknown, init: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, {
      ...init,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  async put<T>(endpoint: string, data?: unknown, init: RequestInit = {}): Promise<T> {
    return this.request<T>(endpoint, {
      ...init,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined
    });
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'DELETE',
    });
  }

  async postStream(
    endpoint: string,
    data?: unknown,
    callbacks?: AssistStreamCallbacks,
    signal?: AbortSignal,
  ): Promise<void> {
    const preferredBaseUrl = this.getPreferredBaseUrl();
    const url = this.forceBrowserRelativeApiUrl(this.buildUrl(preferredBaseUrl, endpoint));

    // Streaming configuration
    // Local runtimes (ollama/local GGUF) can take a while to emit first tokens.
    const STREAMING_TIMEOUT = 300000; // 5 minutes total
    const FIRST_CONTENT_TIMEOUT = 360000; // 6 minutes for model warmup/status-only phases
    const CHUNK_TIMEOUT = 120000; // 120 seconds between content chunks once content starts
    let timeoutId: NodeJS.Timeout;
    let heartbeatId: NodeJS.Timeout;
    let lastChunkTime = Date.now();
    let lastContentChunkTime = Date.now();
    let collectedContent = '';
    let chunksReceived = 0;
    let contentChunksReceived = 0;
    let statusEventsReceived = 0;
    let lastStatusEventTime = Date.now();
    let totalBytes = 0;
    let streamAbortReason: string | null = null;
    const streamController = new AbortController();
    let externalAbortListener: (() => void) | null = null;

    if (signal) {
      if (signal.aborted) {
        streamController.abort();
      } else {
        externalAbortListener = () => streamController.abort();
        signal.addEventListener('abort', externalAbortListener, { once: true });
      }
    }

    const abortStreamWithReason = (reason: string) => {
      if (!streamAbortReason) {
        streamAbortReason = reason;
        callbacks?.onError?.(reason);
      }
      if (!streamController.signal.aborted) {
        streamController.abort();
      }
    };

    // Initialize metrics
    const startTime = Date.now();
    const metrics: StreamingMetrics = {
      startTime,
      chunksReceived: 0,
      totalBytes: 0,
      lastChunkTime: startTime,
      connectionHealth: 'excellent',
    };

    const updateMetrics = () => {
      const now = Date.now();
      const timeSinceLastChunk = now - lastChunkTime;
      
      // Update connection health based on chunk reception
      if (timeSinceLastChunk > CHUNK_TIMEOUT * 2) {
        metrics.connectionHealth = 'critical';
      } else if (timeSinceLastChunk > CHUNK_TIMEOUT) {
        metrics.connectionHealth = 'poor';
      } else if (timeSinceLastChunk > CHUNK_TIMEOUT / 2) {
        metrics.connectionHealth = 'good';
      } else {
        metrics.connectionHealth = 'excellent';
      }
      
      metrics.lastChunkTime = now;
      callbacks?.onMetrics?.(metrics);
    };

    const setupTimeouts = () => {
      timeoutId = setTimeout(() => {
        cleanup();
        abortStreamWithReason('Stream timeout - total session exceeded limit');
      }, STREAMING_TIMEOUT);

      heartbeatId = setInterval(() => {
        const now = Date.now();

        // Warmup guard:
        // 1) If there are no status or content events for too long, abort.
        // 2) If status events are arriving, allow longer warmup and only abort on silence.
        if (contentChunksReceived === 0) {
          const warmupExceeded = now - startTime > FIRST_CONTENT_TIMEOUT;
          if (warmupExceeded && statusEventsReceived === 0) {
            cleanup();
            abortStreamWithReason('Stream warmup timeout - no stream progress received');
            return;
          }

          if (statusEventsReceived > 0 && now - lastStatusEventTime > CHUNK_TIMEOUT) {
            cleanup();
            abortStreamWithReason('Stream stalled during warmup - no status updates received');
            return;
          }
        }

        // Stall guard: once content starts, enforce no-content-chunk timeout.
        if (contentChunksReceived > 0 && now - lastContentChunkTime > CHUNK_TIMEOUT) {
          cleanup();
          abortStreamWithReason('Stream stalled - no content chunks received');
        }
      }, 1000);
    };

    const cleanup = () => {
      clearTimeout(timeoutId);
      clearInterval(heartbeatId);
      if (signal && externalAbortListener) {
        signal.removeEventListener('abort', externalAbortListener);
        externalAbortListener = null;
      }
    };

    const sendStreamRequest = async (): Promise<Response> => {
      const authHeaders = await this.getAuthHeaders();
      return fetch(url, {
        method: 'POST',
        headers: {
          ...authHeaders,
          'Accept': 'text/event-stream',
          'Cache-Control': 'no-cache',
        },
        credentials: 'include',
        body: data ? JSON.stringify(data) : undefined,
        signal: streamController.signal,
      });
    };

    let response = await sendStreamRequest();
    if (response.status === 401) {
      try {
        await this.refreshAccessToken();
        response = await sendStreamRequest();
      } catch {
        // Keep original 401 response path below.
      }
    }

    if (!response.ok) {
      cleanup();
      const rawText = await response.text().catch(() => '');
      let errorData: Record<string, unknown> = {};
      try {
        errorData = JSON.parse(rawText);
      } catch {
        errorData = { detail: rawText.trim() };
      }
      throw new ApiError(
        response.status,
        this.formatApiErrorMessage(errorData, `HTTP ${response.status}: ${response.statusText}`),
        errorData,
      );
    }

    const reader = response.body?.getReader();
    if (!reader) {
      cleanup();
      throw new ApiError(0, 'No readable stream available');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    setupTimeouts();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        lastChunkTime = Date.now();
        chunksReceived++;
        totalBytes += value?.length || 0;
        
        // Update metrics
        metrics.chunksReceived = chunksReceived;
        metrics.totalBytes = totalBytes;
        updateMetrics();

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith('data: ')) continue;

          const payload = trimmed.slice(6);
          if (payload === '[DONE]') {
            cleanup();
            callbacks?.onDone?.();
            return;
          }

          let parsed: StreamEvent;
          try {
            parsed = JSON.parse(payload);
          } catch {
            continue;
          }

          switch (parsed.type) {
            case 'status':
              statusEventsReceived++;
              lastStatusEventTime = Date.now();
              callbacks?.onStatus?.(parsed.content, parsed.metadata);
              break;
            case 'content':
              collectedContent += parsed.content;
              lastContentChunkTime = Date.now();
              contentChunksReceived++;
              if (collectedContent.length > 100000) {
                collectedContent = collectedContent.slice(-50000);
              }
              callbacks?.onContent?.(parsed.content);
              break;
            case 'error':
              cleanup();
              callbacks?.onError?.(parsed.content);
              return;
            case 'warning':
              callbacks?.onStatus?.(parsed.content, parsed.metadata);
              break;
            case 'complete':
              cleanup();
              callbacks?.onComplete?.(parsed.metadata, parsed.content);
              return;
          }
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError' && streamAbortReason) {
        // Timeout/stall aborts are surfaced via onError callback above.
        return;
      }
      throw error;
    } finally {
      cleanup();
      reader.releaseLock();
    }
  }

  /**
   * Check if the backend is healthy and ready to accept requests.
   * Useful for handling startup timing issues.
   */
  async healthCheck(): Promise<boolean> {
    try {
      await this.getUnauthenticated('/api/health');
      return true;
    } catch {
      return false;
    }
  }
}

export const apiClient = new ApiClient();
export default apiClient;
