import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import AdminSettingsPage from '@/components/admin/AdminSettingsPage';
import { apiClient } from '@/lib/api';

vi.mock('@/lib/api', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

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
