import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authMocks = vi.hoisted(() => ({
  validateSession: vi.fn(),
  getCurrentUser: vi.fn(),
  getAccessToken: vi.fn(),
  hasFreshLoginMarker: vi.fn(),
  clearAuth: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  isAuthenticated: vi.fn(),
}));

vi.mock('@/lib/auth', () => ({
  authService: authMocks,
}));

const {
  validateSession,
  getCurrentUser,
  getAccessToken,
  hasFreshLoginMarker,
  clearAuth,
  login,
  logout,
  isAuthenticated,
} = authMocks;

import { AuthProvider, useAuth } from '@/lib/useAuth';
import { AUTH_USER_UPDATED_EVENT } from '@/lib/auth-events';

const user = {
  user_id: 'user-1',
  email: 'user@example.com',
  full_name: 'User',
  roles: ['user'],
  is_active: true,
  tenant_id: 'tenant-1',
  preferences: {},
  permissions: ['chat.use'],
};

function Consumer({ label }: { label: string }) {
  const auth = useAuth();
  return (
    <div data-testid={label}>
      {auth.isLoading ? 'loading' : auth.isAuthenticated ? 'ready' : 'signed-out'}
    </div>
  );
}

function UserNameConsumer() {
  const auth = useAuth();
  return <span data-testid="user-name">{auth.user?.full_name || 'none'}</span>;
}

function AuthRaceConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="race-user">{auth.user?.email ?? "signed-out"}</span>
      <button type="button" onClick={() => void auth.refreshSession()}>race-refresh</button>
      <button type="button" onClick={() => void auth.login({ email: "new@example.test", password: "test" })}>race-login</button>
      <button type="button" onClick={() => void auth.logout()}>race-logout</button>
    </div>
  );
}

function RefreshConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="refresh-state">
        {auth.isLoading ? 'loading' : auth.isAuthenticated ? 'ready' : 'signed-out'}
      </span>
      <button type="button" onClick={() => void auth.refreshSession()}>
        refresh
      </button>
    </div>
  );
}

describe('AuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    validateSession.mockResolvedValue(true);
    getCurrentUser.mockReturnValue(user);
    getAccessToken.mockReturnValue('token');
    hasFreshLoginMarker.mockReturnValue(false);
    isAuthenticated.mockReturnValue(true);
  });

  it('shares one validation lifecycle across multiple consumers', async () => {
    render(
      <AuthProvider>
        <Consumer label="one" />
        <Consumer label="two" />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('one').textContent).toBe('ready');
      expect(screen.getByTestId('two').textContent).toBe('ready');
    });

    expect(validateSession).toHaveBeenCalledTimes(1);
  });

  it('does not return authenticated UI to a blocking loading state during refresh', async () => {
    let resolveRefresh: ((value: boolean) => void) | null = null;
    validateSession
      .mockResolvedValueOnce(true)
      .mockImplementationOnce(
        () =>
          new Promise<boolean>((resolve) => {
            resolveRefresh = resolve;
          }),
      );

    render(
      <AuthProvider>
        <RefreshConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('refresh-state').textContent).toBe('ready');
    });

    await act(async () => {
      screen.getByRole('button', { name: 'refresh' }).click();
    });

    expect(screen.getByTestId('refresh-state').textContent).toBe('ready');

    await act(async () => {
      resolveRefresh?.(true);
    });

    await waitFor(() => {
      expect(screen.getByTestId('refresh-state').textContent).toBe('ready');
    });
  });

  it('updates all consumers from same-tab canonical user changes without revalidation', async () => {
    let currentUser = user;
    getCurrentUser.mockImplementation(() => currentUser);

    render(
      <AuthProvider>
        <UserNameConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('user-name').textContent).toBe('User');
    });

    currentUser = {
      ...user,
      full_name: 'Updated User',
    };

    act(() => {
      window.dispatchEvent(new Event(AUTH_USER_UPDATED_EVENT));
    });

    await waitFor(() => {
      expect(screen.getByTestId('user-name').textContent).toBe('Updated User');
    });

    expect(validateSession).toHaveBeenCalledTimes(1);
  });

  it('ignores an older refresh after a newer login succeeds', async () => {
    let release!: (valid: boolean) => void;
    validateSession
      .mockResolvedValueOnce(true)
      .mockImplementationOnce(() => new Promise<boolean>(resolve => { release = resolve; }));
    login.mockResolvedValue({ user: { ...user, email: "new@example.test" } });

    render(<AuthProvider><AuthRaceConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('race-user').textContent).toBe(user.email));

    await act(async () => { screen.getByRole('button', { name: 'race-refresh' }).click(); });
    await act(async () => { screen.getByRole('button', { name: 'race-login' }).click(); });
    await waitFor(() => expect(screen.getByTestId('race-user').textContent).toBe('new@example.test'));

    await act(async () => { release(false); });
    expect(screen.getByTestId('race-user').textContent).toBe('new@example.test');
    expect(clearAuth).not.toHaveBeenCalled();
  });

  it('ignores delayed old logout completion after a newer login succeeds', async () => {
    let release!: () => void;
    logout.mockImplementation(() => new Promise<void>(resolve => { release = resolve; }));
    login.mockResolvedValue({ user: { ...user, email: "new@example.test" } });

    render(<AuthProvider><AuthRaceConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('race-user').textContent).toBe(user.email));
    await act(async () => { screen.getByRole('button', { name: 'race-logout' }).click(); });
    await act(async () => { screen.getByRole('button', { name: 'race-login' }).click(); });
    await waitFor(() => expect(screen.getByTestId('race-user').textContent).toBe('new@example.test'));
    await act(async () => { release(); });
    expect(screen.getByTestId('race-user').textContent).toBe('new@example.test');
  });


});
