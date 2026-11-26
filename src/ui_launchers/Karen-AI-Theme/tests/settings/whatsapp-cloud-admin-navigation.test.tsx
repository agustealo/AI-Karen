import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import AdminPage from '@/app/admin/page';

import AdminSettingsPage from '@/components/admin/AdminSettingsPage';
import { apiClient } from '@/lib/api';

vi.mock('@/lib/api', () => {
  const apiClient = { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() };
  return {
    default: apiClient,
    apiClient,
    ApiError: class ApiError extends Error {
      status: number;
      constructor(status: number, message: string) {
        super(message);
        this.status = status;
      }
    },
  };
});

vi.mock('@/lib/useAuth', () => {
  const useAuth = () => ({ isAuthenticated: true, isLoading: false, isAdmin: true,
    user: { tenant_id: 'tenant-admin', user_id: 'user-admin', roles: ['admin'] } });
  return { default: useAuth, useAuth };
});

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Use a sentinel only to prove the canonical panel is reachable through the
// real admin tab tree. Full panel/API truth is tested by its own test suite.
vi.mock('@/components/settings/WhatsAppCloudSettings', () => ({
  default: () => <div data-testid="canonical-whatsapp-cloud-panel" />,
}));

beforeEach(() => {
  vi.mocked(apiClient.get).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('canonical admin WhatsApp Cloud navigation', () => {
  it('reaches the existing governed operator panel from /admin settings tabs', async () => {
    render(<AdminSettingsPage />);
    const tab = await screen.findByRole('tab', { name: 'WhatsApp Cloud' });
    expect(tab).toBeTruthy();
    expect(screen.queryByTestId('canonical-whatsapp-cloud-panel')).toBeNull();
    fireEvent.mouseDown(tab, { button: 0, ctrlKey: false });
    expect(await screen.findByTestId('canonical-whatsapp-cloud-panel')).toBeTruthy();
    expect(tab.getAttribute('aria-selected')).toBe('true');
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe('canonical admin Communications navigation', () => {
  it('provides personal approval context through the actual admin route and preserves it across tabs', async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === '/api/approvals/') return [{
        approval_id: 'approval-admin',
        workflow_kind: 'runtime_approval',
        intent: 'Verified admin personal request',
        risk_level: 'high',
        status: 'pending',
        reason_codes: [],
        expires_at: '2099-01-01T00:00:00Z',
      }] as never;
      return [] as never;
    });
    render(<AdminPage />);
    const communications = await screen.findByRole('tab', { name: 'Communications' });
    fireEvent.mouseDown(communications, { button: 0, ctrlKey: false });
    const root = await screen.findByTestId('comms-center');
    fireEvent.click(within(root).getByRole('button', { name: 'Review decisions' }));
    const inbox = await within(root).findByTestId('comms-decisions-inbox');
    expect(await within(inbox).findByText('Verified admin personal request')).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'WhatsApp Cloud' }), { button: 0, ctrlKey: false });
    await screen.findByTestId('canonical-whatsapp-cloud-panel');
    fireEvent.mouseDown(communications, { button: 0, ctrlKey: false });
    fireEvent.click(within(await screen.findByTestId('comms-center')).getByRole('button', { name: 'Review decisions' }));
    expect(await screen.findByText('Verified admin personal request')).toBeTruthy();
    expect(vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === '/api/approvals/')).toHaveLength(1);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
