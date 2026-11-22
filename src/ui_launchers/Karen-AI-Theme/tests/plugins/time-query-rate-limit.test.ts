import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { ApiError, apiClient } from '../../src/lib/api';
import type { ExtensionAPI } from '../../src/lib/extensions/hooks/usePluginExtension';
import { TimeQueryApi } from '../../src/plugin_repo/time-query/services/timeQueryApi';
import { useAlarms } from '../../src/plugin_repo/time-query/hooks/useAlarms';
import { useWorldClocks } from '../../src/plugin_repo/time-query/hooks/useWorldClocks';

function extension(execute: ExtensionAPI['execute']): ExtensionAPI {
  return { execute, getStatus: async () => ({ isReady: true }) };
}

describe('Time Query HTTP 429 recovery and non-replay contract', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('preserves backend Retry-After on ApiError and never retries a generic plugin POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ message: 'Too many requests. Try again in 4 seconds.' }),
      { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '4' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    await expect(apiClient.post('/api/plugins/time-query/execute', {
      plugin_name: 'time-query',
      parameters: { mode: 'alarm', action: 'list' },
    })).rejects.toMatchObject({ status: 429, retryAfterSeconds: 4 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('deduplicates simultaneous reads and serializes distinct startup reads', async () => {
    let releaseFirst: ((value: unknown) => void) | undefined;
    const first = new Promise<unknown>((resolve) => { releaseFirst = resolve; });
    const execute = vi.fn().mockReturnValueOnce(first).mockResolvedValue({ status: 'success', alarms: [] });
    const api = new TimeQueryApi(extension(execute));
    const current = api.getCurrentTime();
    const alarms = api.getAlarms();
    const sameAlarms = api.getAlarms();
    await Promise.resolve();
    expect(execute).toHaveBeenCalledTimes(1);
    expect(execute).toHaveBeenCalledWith({ mode: 'datetime' });
    releaseFirst!({ status: 'success' });
    await Promise.all([current, alarms, sameAlarms]);
    expect(execute).toHaveBeenCalledTimes(2);
    expect(execute).toHaveBeenNthCalledWith(2, { mode: 'alarm', action: 'list' });
  });

  it('retries only a read once after server cooldown, not before', async () => {
    vi.useFakeTimers();
    const execute = vi.fn()
      .mockRejectedValueOnce(new ApiError(429, 'Throttled', {}, 4))
      .mockResolvedValueOnce({ status: 'success', alarms: [] });
    const api = new TimeQueryApi(extension(execute));
    const read = api.getAlarms();
    await vi.advanceTimersByTimeAsync(3999);
    expect(execute).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(read).resolves.toMatchObject({ status: 'success', alarms: [] });
    expect(execute).toHaveBeenCalledTimes(2);
  });

  it('does not replay alarm creation and preserves the original 429 error', async () => {
    const error = new ApiError(429, 'Throttled', {}, 4);
    const execute = vi.fn().mockRejectedValue(error);
    const api = new TimeQueryApi(extension(execute));
    await expect(api.createAlarm({} as Parameters<typeof api.createAlarm>[0])).rejects.toBe(error);
    expect(execute).toHaveBeenCalledTimes(1);
  });

  it('surfaces rate-limited alarms without logging an unrelated exception', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const api = new TimeQueryApi(extension(vi.fn().mockRejectedValue(new ApiError(429, 'Try again in 4 seconds'))));
    const { result } = renderHook(() => useAlarms(api));
    await waitFor(() => expect(result.current.error).toContain('Try again in 4 seconds'));
    expect(spy).not.toHaveBeenCalled();
  });

  it('surfaces rate-limited world clocks without logging an unrelated exception', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const api = new TimeQueryApi(extension(vi.fn().mockRejectedValue(new ApiError(429, 'Try again in 4 seconds'))));
    const { result } = renderHook(() => useWorldClocks(api));
    await waitFor(() => expect(result.current.error).toContain('Try again in 4 seconds'));
    expect(spy).not.toHaveBeenCalled();
  });
});
