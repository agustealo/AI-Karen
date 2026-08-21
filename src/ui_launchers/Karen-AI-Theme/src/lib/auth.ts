"use client";

/**
 * Authentication Service for Karen AI Theme
 * 
 * This service handles all authentication-related operations including
 * login, logout, token management, and user session handling.
 */

export interface LoginCredentials {
  email?: string;
  username?: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    user_id: string;
    email: string;
    full_name: string;
    roles: string[];
    is_active: boolean;
    tenant_id: string;
    preferences: Record<string, unknown>;
    last_login?: string | null;
    permissions?: string[];
  };
  permissions: string[];
}

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  roles: string[];
  is_active: boolean;
  tenant_id: string;
  preferences: Record<string, unknown>;
  created_at?: string;
  last_login?: string | null;
  permissions?: string[];
}

// Legacy interfaces for backward compatibility
export interface User {
  id: string;
  username: string;
  email?: string;
  role?: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
}

export interface AuthResponse {
  user: User;
  tokens: AuthTokens;
}

class AuthService {
  private readonly SAME_ORIGIN_API_BASE_URL = '';
  private readonly DIRECT_BROWSER_BACKEND_PORT = '8010';
  private readonly SESSION_COOKIE_NAME = 'kari_session';
  private readonly LEGACY_ACCESS_COOKIE_NAME = 'access_token';
  private readonly LEGACY_REFRESH_COOKIE_NAME = 'refresh_token';
  private readonly SESSION_MARKER_KEY = 'kari_session_expected';
  private readonly LOGIN_SUCCESS_AT_KEY = 'kari_login_success_at';
  private readonly REQUEST_TIMEOUT_MS = 30000;
  private readonly SESSION_VALIDATION_TIMEOUT_MS = 10000;
  private readonly REFRESH_RETRY_COOLDOWN_MS = 60000;
  private readonly LOGIN_VALIDATION_GRACE_MS = 30000;
  private refreshInFlight: Promise<string> | null = null;
  private sessionValidationInFlight: Promise<boolean> | null = null;
  private refreshBlockedUntil = 0;

  private async fetchWithTimeout(
    input: RequestInfo | URL,
    init?: RequestInit,
    timeoutMs: number = this.REQUEST_TIMEOUT_MS,
  ): Promise<Response> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await fetch(input, {
        ...init,
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error(`Request timed out after ${timeoutMs}ms`);
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  private forceBrowserRelativeApiUrl(url: string): string {
    if (typeof window === 'undefined') {
      return url;
    }

    if (url.startsWith('/')) {
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

  private getConfiguredBackendUrl(): string | null {
    const isBrowser = typeof window !== 'undefined' && typeof document !== 'undefined';
    if (isBrowser) {
      const env = (process as unknown as { env?: Record<string, string> }).env || {};
      const configuredBaseUrl = (env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '');
      if (configuredBaseUrl) {
        return configuredBaseUrl;
      }

      const { protocol, hostname, port } = window.location;
      // If we are already on the backend port (unlikely for UI), return empty for same-origin
      if (!hostname || port === this.DIRECT_BROWSER_BACKEND_PORT) {
        return '';
      }

      // Default to trying the expected backend port on the current host as a secondary option
      return `${protocol}//${hostname}:${this.DIRECT_BROWSER_BACKEND_PORT}`;
    }

    const env = (process as unknown as { env?: Record<string, string> }).env || {};
    return (env.KAREN_BACKEND_URL || env.NEXT_PUBLIC_API_BASE_URL || '').replace(/\/$/, '') || null;
  }

  private getPreferredBaseUrl(): string {
    if (typeof window !== 'undefined' && typeof document !== 'undefined') {
      // In the browser, we MUST always prefer same-origin for /api requests to satisfy CORS
      // and handle Docker networking correctly via the Next.js proxy.
      return window.location.origin;
    }
    return this.getConfiguredBackendUrl() || '';
  }

  private getFallbackBaseUrl(preferredBaseUrl: string): string | null {
    if (typeof window !== 'undefined' && typeof document !== 'undefined') {
      return null;
    }

    const configuredBackendUrl = this.getConfiguredBackendUrl();
    if (preferredBaseUrl === this.SAME_ORIGIN_API_BASE_URL) {
      return configuredBackendUrl;
    }
    
    return this.SAME_ORIGIN_API_BASE_URL || null;
  }

  private buildUrl(baseUrl: string | null, endpoint: string): string {
    const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

    // Strip absolute URLs pointing to internal Docker infrastructure in a browser context.
    // This ensures requests go through the local proxy and avoids ERR_NAME_NOT_RESOLVED.
    const dockerHostPattern = /https?:\/\/(api|api-copilot|172\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|localhost:80[01]0|host\.docker\.internal)(:\d+)?/gi;
    
    let finalUrl = baseUrl ? `${baseUrl}${normalizedEndpoint}` : normalizedEndpoint;
    if (typeof window !== 'undefined' && dockerHostPattern.test(finalUrl)) {
      finalUrl = finalUrl.replace(dockerHostPattern, '');
      if (!finalUrl.startsWith('/')) finalUrl = '/' + finalUrl;
    }
    
    if (typeof window !== 'undefined') {
      return finalUrl;
    }

    if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
      return endpoint;
    }

    return `${baseUrl || ''}${normalizedEndpoint}`;
  }

  private shouldRetryWithSameOrigin(error: unknown): boolean {
    return (
      typeof window !== 'undefined' &&
      (
        error instanceof TypeError ||
        (error instanceof Error && /timed out/i.test(error.message))
      )
    );
  }

  private shouldRetryWithDirectBackend(response: Response, fallbackBaseUrl: string | null): boolean {
    return (
      typeof window !== 'undefined' &&
      Boolean(fallbackBaseUrl) &&
      response.status >= 500
    );
  }

  private clearBrowserCookie(name: string): void {
    if (typeof document === 'undefined') {
      return;
    }

    document.cookie = `${name}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax`;
  }

  private clearClientCookies(): void {
    this.clearBrowserCookie(this.SESSION_COOKIE_NAME);
    this.clearBrowserCookie(this.LEGACY_ACCESS_COOKIE_NAME);
    this.clearBrowserCookie(this.LEGACY_REFRESH_COOKIE_NAME);
  }

  private hasSessionMarker(): boolean {
    try {
      return localStorage.getItem(this.SESSION_MARKER_KEY) === 'true';
    } catch {
      return false;
    }
  }

  private setSessionMarker(): void {
    try {
      localStorage.setItem(this.SESSION_MARKER_KEY, 'true');
    } catch {
      // Ignore storage issues and continue.
    }
  }

  private clearSessionMarker(): void {
    try {
      localStorage.removeItem(this.SESSION_MARKER_KEY);
    } catch {
      // Ignore storage issues and continue.
    }
  }

  private markLoginSuccess(): void {
    try {
      localStorage.setItem(this.LOGIN_SUCCESS_AT_KEY, String(Date.now()));
    } catch {
      // Ignore storage issues and continue.
    }
  }

  private clearLoginSuccessMarker(): void {
    try {
      localStorage.removeItem(this.LOGIN_SUCCESS_AT_KEY);
    } catch {
      // Ignore storage issues and continue.
    }
  }

  /**
   * Returns true if a login recently succeeded (within grace period).
   */
  hasFreshLoginMarker(): boolean {
    try {
      const raw = localStorage.getItem(this.LOGIN_SUCCESS_AT_KEY);
      if (!raw) {
        return false;
      }

      const timestamp = Number(raw);
      return Number.isFinite(timestamp) && Date.now() - timestamp <= this.LOGIN_VALIDATION_GRACE_MS;
    } catch {
      return false;
    }
  }

  private shouldPreserveFreshLoginSession(): boolean {
    if (!this.hasFreshLoginMarker()) {
      return false;
    }
    // Always preserve session during grace period after login success,
    // regardless of token presence to prevent immediate redirect loop
    return true;
  }

  private isTransientAuthError(error: unknown): boolean {
    if (!(error instanceof Error)) return false;
    const message = error.message.toLowerCase();
    return (
      message.includes('502') ||
      message.includes('503') ||
      message.includes('504') ||
      message.includes('fetch') ||
      message.includes('timeout') ||
      message.includes('database unavailable') ||
      message.includes('session not found in memory')
    );
  }

  private async getErrorMessage(response: Response, fallback: string): Promise<string> {
    try {
      const errorData = await response.json();

      if (typeof errorData?.detail === 'string' && errorData.detail.trim()) {
        return errorData.detail;
      }

      if (Array.isArray(errorData?.detail) && errorData.detail.length > 0) {
        return errorData.detail
          .map((issue: Record<string, unknown>) => {
            if (typeof issue?.msg === 'string' && issue.msg.trim()) {
              return issue.msg;
            }
            return null;
          })
          .filter((message: string | null): message is string => Boolean(message))
          .join(', ') || fallback;
      }

      if (typeof errorData?.message === 'string' && errorData.message.trim()) {
        return errorData.message;
      }
    } catch {
      // Fall back to the provided default message when the response is not JSON.
    }

    return fallback;
  }

  /**
   * Login user with credentials
   */
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    try {
      const sendLogin = async (): Promise<Response> =>
        this.fetchWithTimeout('/api/auth/login', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify(credentials),
        });

      const response = await sendLogin();

      if (!response.ok) {
        throw new Error(await this.getErrorMessage(response, 'Login failed'));
      }

       const data: LoginResponse = await response.json();
       const resolvedUser =
         data?.user && typeof data.user === 'object' ? data.user : null;

       // Store both tokens in localStorage for proper session management.
       // The access_token is used for session validation and fallback auth.
       // The kari_session cookie is the primary auth mechanism.
       localStorage.setItem('access_token', data.access_token);
       localStorage.setItem('refresh_token', data.refresh_token);
       if (resolvedUser) {
         localStorage.setItem('user_data', JSON.stringify(resolvedUser));
       } else {
         // Preserve prior behavior (logged-in marker + tokens), but allow
         // validateSession() to recover canonical user data from backend.
         localStorage.removeItem('user_data');
       }
       this.setSessionMarker();
       this.markLoginSuccess();

       // Drop any stale session validation promise started before login.
       this.sessionValidationInFlight = null;
       this.refreshBlockedUntil = 0;

       console.log('[AuthService] Login successful, tokens stored:', {
         hasAccessToken: !!data.access_token,
         hasRefreshToken: !!data.refresh_token,
         hasUser: !!resolvedUser,
         hasSessionMarker: this.hasSessionMarker(),
       });

       // The backend owns the production session cookie, but to avoid Next.js middleware
       // race conditions on the immediate client-side redirect, we also sync it locally.
       if (typeof document !== 'undefined') {
         document.cookie = `${this.SESSION_COOKIE_NAME}=${data.access_token}; path=/; max-age=${data.expires_in}; SameSite=Lax`;
       }
      this.clearBrowserCookie(this.LEGACY_ACCESS_COOKIE_NAME);
      this.clearBrowserCookie(this.LEGACY_REFRESH_COOKIE_NAME);
      
      return data;
    } catch (error) {
      console.error('Login error:', error);
      throw error;
    }
  }

  /**
   * Logout user
   */
  async logout(): Promise<void> {
    try {
      const refreshToken = localStorage.getItem('refresh_token');
      const accessToken = localStorage.getItem('access_token');
      if (refreshToken) {
        // Use a shorter timeout for logout to prevent UI hangs
        await this.fetchWithTimeout('/api/auth/logout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          },
          credentials: 'include',
          body: JSON.stringify({ refresh_token: refreshToken }),
        }, 5000);
      }
    } catch (error) {
      console.error('Logout error:', error);
      // Continue with cleanup even if API call fails
    } finally {
      // Clear all auth data
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user_data');
      this.clearSessionMarker();
      this.clearLoginSuccessMarker();

      this.clearClientCookies();
    }
  }

  /**
   * Refresh access token
   */
  async refreshToken(): Promise<string> {
    if (this.refreshInFlight) {
      return this.refreshInFlight;
    }

    const now = Date.now();
    if (now < this.refreshBlockedUntil) {
      throw new Error('Token refresh temporarily blocked after recent auth failure');
    }

    this.refreshInFlight = (async () => {
      try {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) {
          throw new Error('No refresh token available');
        }

      const response = await this.fetchWithTimeout('/api/auth/refresh', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
          credentials: 'include',
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

      if (!response.ok) {
        const errorMessage = await this.getErrorMessage(response, 'Token refresh failed');
        if (response.status === 401 || response.status === 403) {
          this.refreshBlockedUntil = Date.now() + this.REFRESH_RETRY_COOLDOWN_MS;
          console.warn('[AuthService] Refresh token rejected; clearing local auth state.');
          this.clearAuth();
          return '';
        }
        throw new Error(errorMessage);
      }

        const data = await response.json();
        localStorage.setItem('access_token', data.access_token);
        this.markLoginSuccess();
        this.refreshBlockedUntil = 0;
        
        return data.access_token;
    } catch (error) {
      if (error instanceof Error && /invalid refresh token/i.test(error.message)) {
        console.warn('[AuthService] Invalid refresh token; clearing local auth state.');
        this.clearAuth();
        return '';
      }
      console.error('Token refresh error:', error);
      
      // Don't clear auth on transient errors (like 502/503 during degraded mode)
      if (this.isTransientAuthError(error)) {
        console.warn('[AuthService] Transient error during token refresh, preserving local auth state.');
      } else {
        // Hard refresh failure should be terminal for this local session
        this.clearAuth();
      }
      
      throw error;
    } finally {
      this.refreshInFlight = null;
    }
  })();

    return this.refreshInFlight;
  }

  /**
   * Get current user data
   */
  getCurrentUser(): AuthUser | null {
    try {
      const userData = localStorage.getItem('user_data');
      return userData ? JSON.parse(userData) : null;
    } catch (error) {
      console.error('Error getting user data:', error);
      return null;
    }
  }

  /**
   * Persist current user data in local storage.
   */
  setCurrentUser(user: AuthUser | (AuthUser & Record<string, unknown>)): void {
    localStorage.setItem('user_data', JSON.stringify(user));
  }

  /**
   * Merge partial current user data into local storage.
   */
  updateCurrentUser(patch: Partial<AuthUser>): void {
    const currentUser = this.getCurrentUser();
    if (!currentUser) {
      return;
    }

    const nextUser: AuthUser = {
      ...currentUser,
      ...patch,
      preferences: {
        ...(currentUser.preferences || {}),
        ...(patch.preferences || {}),
      },
    };

    this.setCurrentUser(nextUser);
  }

  /**
   * Get access token
   */
  getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  }

  /**
   * Get refresh token
   */
  getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token');
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!this.getCurrentUser() && (this.hasSessionMarker() || !!this.getAccessToken());
  }

  /**
   * Get user permissions
   */
  getUserPermissions(): string[] {
    const user = this.getCurrentUser();
    return user?.permissions || [];
  }

  /**
   * Check if user has specific permission
   */
  hasPermission(permission: string): boolean {
    const permissions = this.getUserPermissions();
    return permissions.includes(permission);
  }

  /**
   * Check if user has admin role
   */
  isAdmin(): boolean {
    const user = this.getCurrentUser();
    return user?.roles.includes('admin') || false;
  }

  /**
   * Validate current session
   */
  async validateSession(): Promise<boolean> {
    if (this.sessionValidationInFlight) {
      return this.sessionValidationInFlight;
    }

    this.sessionValidationInFlight = (async (): Promise<boolean> => {
      let accessToken: string | null = null;
      let refreshToken: string | null = null;
      let currentUser: AuthUser | null = null;
      let hasSessionMarker = false;

      try {
        accessToken = this.getAccessToken();
        refreshToken = this.getRefreshToken();
        currentUser = this.getCurrentUser();
        hasSessionMarker = this.hasSessionMarker();

        if (!accessToken && !refreshToken && !currentUser && !hasSessionMarker) {
          return false;
        }

        // If user_data is missing but we still have session artifacts, try
        // recovering canonical user state from backend before clearing auth.
        const hasRecoverableSessionArtifacts =
          !!accessToken || !!refreshToken || hasSessionMarker;
        if (!currentUser && !hasRecoverableSessionArtifacts) {
          return false;
        }

        // Stale local user cache with no viable auth artifacts.
        // Do not keep this around because it causes repeated invalid-session loops.
        if (currentUser && !accessToken && !refreshToken && !hasSessionMarker) {
          this.clearAuth();
          return false;
        }

        // Bypass backend validation immediately after login to avoid race conditions
        // with cookie propagation and prevent immediate redirect loops
        if (accessToken && currentUser && this.hasFreshLoginMarker()) {
          console.log('[AuthService] Skipping backend validation for fresh login session');
          return true;
        }

        const requestHeaders: Record<string, string> = {};
        // Always send bearer token when available; cookie session remains enabled via credentials.
        // This prevents false negatives when kari_session cookie propagation lags behind login.
        if (accessToken) {
          requestHeaders.Authorization = `Bearer ${accessToken}`;
        }

        const response = await this.fetchWithTimeout('/api/auth/validate-session', {
          method: 'GET',
          headers: requestHeaders,
          credentials: 'include',
        }, this.SESSION_VALIDATION_TIMEOUT_MS);

        console.log('[AuthService] validateSession response:', {
          status: response.status,
          ok: response.ok,
          hasAccessToken: !!accessToken,
          hasRefreshToken: !!refreshToken,
          hasCurrentUser: !!currentUser,
          hasSessionMarker,
        });

        if (!response.ok) {
          if (response.status !== 401 && response.status !== 403) {
            // Treat transient non-auth failures as non-terminal when local auth state exists.
            if (accessToken && (currentUser || hasSessionMarker)) {
              console.warn('[AuthService] validateSession transient failure, preserving local session');
              return true;
            }
          }

          // Try to refresh token if validation fails and we have a refresh token available.
          try {
            if (refreshToken) {
              await this.refreshToken();
              // Retry validation with new token
              const refreshedHeaders: Record<string, string> = {};
              const refreshedAccessToken = this.getAccessToken();
              if (refreshedAccessToken) {
                refreshedHeaders.Authorization = `Bearer ${refreshedAccessToken}`;
              }

              const newResponse = await this.fetchWithTimeout('/api/auth/validate-session', {
                method: 'GET',
                headers: refreshedHeaders,
                credentials: 'include',
              }, this.SESSION_VALIDATION_TIMEOUT_MS);

              console.log('[AuthService] validateSession retry response:', {
                status: newResponse.status,
                ok: newResponse.ok,
                hasRefreshedAccessToken: !!refreshedAccessToken,
              });

              if (!newResponse.ok) {
                if (this.shouldPreserveFreshLoginSession()) {
                  console.warn('[AuthService] preserving fresh login session despite failed validation retry');
                  return true;
                }
                this.clearAuth();
                this.clearSessionMarker();
                return false;
              }

              const refreshedSession = await newResponse.json();
              if (refreshedSession?.user && typeof refreshedSession.user === 'object') {
                localStorage.setItem('user_data', JSON.stringify(refreshedSession.user));
                this.setSessionMarker();
                this.markLoginSuccess();
                return true;
              }

              if (this.shouldPreserveFreshLoginSession()) {
                console.warn('[AuthService] preserving fresh login session despite missing user payload on retry validation');
                return true;
              }
              this.clearAuth();
              return false;
            } else {
              if (this.shouldPreserveFreshLoginSession()) {
                console.warn('[AuthService] preserving fresh login session despite missing refresh token during validation');
                return true;
              }
              this.clearAuth();
              return false;
            }
          } catch (refreshError) {
            if (this.isTransientAuthError(refreshError) && accessToken && (currentUser || hasSessionMarker)) {
              console.warn('[AuthService] transient refresh failure during validation; preserving local session');
              return true;
            }

            if (this.shouldPreserveFreshLoginSession()) {
              console.warn('[AuthService] preserving fresh login session despite refresh failure during validation');
              return true;
            }
            this.clearAuth();
            this.clearSessionMarker();
            return false;
          }
        }

        const session = await response.json();
        if (session?.user && typeof session.user === 'object') {
          localStorage.setItem('user_data', JSON.stringify(session.user));
          this.setSessionMarker();
          this.markLoginSuccess();
          return true;
        }

        // A successful response without a usable user payload is not a valid session.
        if (this.shouldPreserveFreshLoginSession()) {
          console.warn('[AuthService] preserving fresh login session despite missing user payload from validation');
          return true;
        }
        this.clearAuth();
        return false;
      } catch (error) {
        const isTimeout = error instanceof Error && /Request timed out after \d+ms/i.test(error.message);

        if (isTimeout) {
          console.warn('[AuthService] validateSession timed out, treating as transient');
        } else {
          console.error('Session validation error:', error);
        }

        // During dev/HMR, in-flight validation requests can be interrupted while local auth
        // state is still valid. Avoid hard logout on transient transport failures.
        if (accessToken && (currentUser || hasSessionMarker)) {
          console.warn('[AuthService] validateSession transport failure, preserving local session');
          return true;
        }
        return false;
      } finally {
        this.sessionValidationInFlight = null;
      }
    })();

    return this.sessionValidationInFlight;
  }

  /**
   * Clear all auth data
   */
  clearAuth(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_data');
    this.clearSessionMarker();
    this.clearLoginSuccessMarker();

    this.clearClientCookies();
  }

  // Backward compatibility methods
  clearAuthData(): void {
    this.clearAuth();
  }

  // Check if token is expired (simple implementation)
  isTokenExpired(token: string): boolean {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.exp < Date.now() / 1000;
    } catch {
      return true;
    }
  }

  // Auto-refresh token before expiration
  async ensureValidToken(): Promise<string> {
    const accessToken = this.getAccessToken();
    
    if (!accessToken) {
      const sessionStillValid = await this.validateSession();
      if (sessionStillValid) {
        return '';
      }
      throw new Error('No access token available');
    }

    if (this.isTokenExpired(accessToken)) {
      const refreshedToken = await this.refreshToken();
      if (refreshedToken) {
        return refreshedToken;
      }
      return '';
    }

    return accessToken;
  }

  // Legacy login method for backward compatibility
  async loginLegacy(credentials: { username: string; password: string }): Promise<AuthResponse> {
    const response = await this.login({
      username: credentials.username,
      password: credentials.password
    });

    // Convert to legacy format
    const legacyUser: User = {
      id: response.user.user_id,
      username: response.user.email, // Use email as username for backward compatibility
      email: response.user.email,
      role: response.user.roles[0] || 'user'
    };

    return {
      user: legacyUser,
      tokens: {
        access_token: response.access_token,
        refresh_token: response.refresh_token
      }
    };
  }
}

// Create singleton instance
export const authService = new AuthService();
