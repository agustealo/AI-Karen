"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { authService, type AuthUser, type LoginCredentials } from './auth';
import { AUTH_INVALIDATED_EVENT } from './auth-events';

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
}

interface AuthContextValue extends AuthState {
  login(credentials: LoginCredentials): Promise<unknown>;
  logout(): Promise<void>;
  refreshSession(): Promise<void>;
  initializeAuth(): Promise<void>;
  clearError(): void;
  hasPermission(permission: string): boolean;
  isAdmin(): boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const unauthenticatedState: AuthState = {
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    error: null,
  });
  const initialResolutionCompleteRef = useRef(false);

  const applyCanonicalState = useCallback((isValid: boolean) => {
    const user = isValid ? authService.getCurrentUser() : null;

    if (!isValid || !user) {
      if (!isValid) {
        authService.clearAuth();
      }
      setState(unauthenticatedState);
      initialResolutionCompleteRef.current = true;
      return;
    }

    setState({
      user,
      isAuthenticated: true,
      isLoading: false,
      error: null,
    });
    initialResolutionCompleteRef.current = true;
  }, []);

  const initializeAuth = useCallback(async () => {
    const blockRendering = !initialResolutionCompleteRef.current;

    if (blockRendering) {
      setState((previous) => ({
        ...previous,
        isLoading: true,
        error: null,
      }));
    } else {
      setState((previous) => ({
        ...previous,
        error: null,
      }));
    }

    try {
      const hasFreshLogin = authService.hasFreshLoginMarker();
      const currentUser = authService.getCurrentUser();
      const hasAccessToken = Boolean(authService.getAccessToken());

      if (hasFreshLogin && currentUser && hasAccessToken) {
        applyCanonicalState(true);
        return;
      }

      const isValid = await authService.validateSession();
      applyCanonicalState(isValid);
    } catch (error) {
      const currentUser = authService.getCurrentUser();
      const canPreserveResolvedSession =
        initialResolutionCompleteRef.current &&
        state.isAuthenticated &&
        Boolean(currentUser);

      if (canPreserveResolvedSession) {
        setState((previous) => ({
          ...previous,
          user: currentUser,
          isAuthenticated: true,
          isLoading: false,
          error:
            error instanceof Error
              ? error.message
              : 'Session validation temporarily unavailable',
        }));
        return;
      }

      authService.clearAuth();
      initialResolutionCompleteRef.current = true;
      setState({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: error instanceof Error ? error.message : 'Authentication failed',
      });
    }
  }, [applyCanonicalState, state.isAuthenticated]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    setState((previous) => ({
      ...previous,
      isLoading: true,
      error: null,
    }));

    try {
      const response = await authService.login(credentials);
      const user = response.user ?? authService.getCurrentUser();

      initialResolutionCompleteRef.current = true;
      setState({
        user: user ?? null,
        isAuthenticated: Boolean(user),
        isLoading: false,
        error: null,
      });
      return response;
    } catch (error) {
      setState((previous) => ({
        ...previous,
        isLoading: false,
        error: error instanceof Error ? error.message : 'Login failed',
      }));
      throw error;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      initialResolutionCompleteRef.current = true;
      setState(unauthenticatedState);
    }
  }, []);

  const refreshSession = useCallback(async () => {
    // Background refresh must never replace the already-rendered application
    // with a blocking auth loader.
    setState((previous) => ({
      ...previous,
      error: null,
    }));

    try {
      const isValid = await authService.validateSession();
      applyCanonicalState(isValid);
    } catch (error) {
      setState((previous) => ({
        ...previous,
        isLoading: false,
        error:
          error instanceof Error ? error.message : 'Session refresh failed',
      }));
      throw error;
    }
  }, [applyCanonicalState]);

  const clearError = useCallback(() => {
    setState((previous) => ({ ...previous, error: null }));
  }, []);

  const hasPermission = useCallback(
    (permission: string) =>
      Boolean(state.user?.permissions?.includes(permission)),
    [state.user?.permissions],
  );

  const isAdmin = useCallback(
    () => Boolean(state.user?.roles?.includes('admin')),
    [state.user?.roles],
  );

  useEffect(() => {
    void initializeAuth();
  }, [initializeAuth]);

  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    const handleStorageChange = () => {
      if (timeoutId) clearTimeout(timeoutId);
      timeoutId = setTimeout(() => {
        void initializeAuth();
      }, 250);
    };

    const handleAuthInvalidated = () => {
      authService.clearAuth();
      initialResolutionCompleteRef.current = true;
      setState(unauthenticatedState);
    };

    window.addEventListener('storage', handleStorageChange);
    window.addEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      window.removeEventListener('storage', handleStorageChange);
      window.removeEventListener(AUTH_INVALIDATED_EVENT, handleAuthInvalidated);
    };
  }, [initializeAuth]);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      login,
      logout,
      refreshSession,
      initializeAuth,
      clearError,
      hasPermission,
      isAdmin,
    }),
    [
      state,
      login,
      logout,
      refreshSession,
      initializeAuth,
      clearError,
      hasPermission,
      isAdmin,
    ],
  );

  return createElement(AuthContext.Provider, { value }, children);
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export default useAuth;
