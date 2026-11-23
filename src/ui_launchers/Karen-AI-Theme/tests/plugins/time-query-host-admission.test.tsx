import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { usePluginExtension } from '../../src/lib/extensions/hooks/usePluginExtension';
import TimeQueryPage from '../../src/plugin_repo/time-query/TimeQueryPage';

vi.mock('../../src/lib/extensions/hooks/usePluginExtension', () => ({
  usePluginExtension: vi.fn(),
}));

const mockExtension = vi.mocked(usePluginExtension);

describe('Time Query host readiness admission', () => {
  beforeEach(() => {
    mockExtension.mockReset();
  });

  it('does not execute any command before host readiness, then loads one startup batch', async () => {
    const execute = vi.fn(async (command: unknown) => {
      const requested = command as { mode?: string; action?: string };
      switch (requested.mode) {
        case 'datetime':
          return { status: 'error', error: 'Clock not yet available' };
        case 'alarm':
          return { status: 'success', alarms: [] };
        case 'multi_clock':
          return { status: 'success', clocks: [] };
        case 'stopwatch':
          return { status: 'success', stopwatch: {
            elapsed_ms: 0, running: false, paused: false, last_updated_at: null,
          } };
        default:
          throw new Error('Unexpected Time Query startup command');
      }
    });
    const host = {
      api: { execute, getStatus: vi.fn().mockResolvedValue({ isReady: false }) },
      isReady: false,
      error: null,
      loading: true,
    };
    mockExtension.mockImplementation(() => host);
    const view = render(<TimeQueryPage />);
    expect(screen.getByText('Initializing Time Query Plugin...')).toBeTruthy();
    expect(execute).not.toHaveBeenCalled();

    host.isReady = true;
    host.loading = false;
    view.rerender(<TimeQueryPage />);
    await waitFor(() => expect(execute).toHaveBeenCalledTimes(4));
    expect(execute.mock.calls.map(([command]) => command)).toEqual([
      { mode: 'datetime' },
      { mode: 'multi_clock', action: 'list' },
      { mode: 'stopwatch', action: 'status', stopwatch_id: 'default' },
      { mode: 'alarm', action: 'list' },
    ]);
    view.unmount();
  });

  it('shows real initialization failures and never executes plugin commands on a failed host', () => {
    const execute = vi.fn();
    mockExtension.mockReturnValue({
      api: { execute, getStatus: vi.fn() },
      isReady: false,
      loading: false,
      error: 'Plugin health unavailable',
    });
    render(<TimeQueryPage />);
    expect(screen.getByText(/Extension Host Error: Plugin health unavailable/)).toBeTruthy();
    expect(execute).not.toHaveBeenCalled();
  });
});
