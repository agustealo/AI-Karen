import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const validateSession = vi.fn();
const getCurrentUser = vi.fn();
const getAccessToken = vi.fn();
const hasFreshLoginMarker = vi.fn();
const clearAuth = vi.fn();
const login = vi.fn();
const logout = vi.fn();
const isAuthenticated = vi.fn();

vi.mock('@/lib/auth', () => ({
  authService: {
    validateSession,
    getCurrentUser,
    getAccessToken,
    hasFreshLoginMarker,
    clearAuth,
    login,
    logout,
    isAuthenticated,
  },
}));

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

});
