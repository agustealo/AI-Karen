import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
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

  it('rejects queued reads promptly when server cooldown exceeds bounded automatic wait', async () => {
    vi.useFakeTimers();
    const limited = new ApiError(429, 'Retry after 60 seconds', {}, 60);
    const execute = vi.fn().mockRejectedValueOnce(limited);
    const api = new TimeQueryApi(extension(execute));
    const alarms = api.getAlarms();
    const clocks = api.listMultiClocks();
    await expect(alarms).rejects.toBe(limited);
    await expect(clocks).rejects.toBe(limited);
    expect(execute).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('invalidates an in-flight alarm snapshot after a successful write', async () => {
    let finishOld: ((value: unknown) => void) | undefined;
    const oldRead = new Promise<unknown>((resolve) => { finishOld = resolve; });
    const execute = vi.fn()
      .mockReturnValueOnce(oldRead)
      .mockResolvedValueOnce({ status: 'success' })
      .mockResolvedValueOnce({ status: 'success', alarms: [] });
    const api = new TimeQueryApi(extension(execute));
    const stale = api.getAlarms();
    await Promise.resolve();
    await api.deleteAlarm('alarm-a');
    const refreshed = api.getAlarms();
    expect(refreshed).not.toBe(stale);
    finishOld!({ status: 'success', alarms: [{ alarm_id: 'alarm-a' }] });
    await stale;
    await expect(refreshed).resolves.toEqual({ status: 'success', alarms: [] });
    expect(execute).toHaveBeenCalledTimes(3);
    expect(execute).toHaveBeenNthCalledWith(2, {
      mode: 'alarm', action: 'delete', alarm_id: 'alarm-a',
    });
    expect(execute).toHaveBeenNthCalledWith(3, { mode: 'alarm', action: 'list' });
  });

  it('invalidates an in-flight clock snapshot after a successful write', async () => {
    let finishOld: ((value: unknown) => void) | undefined;
    const oldRead = new Promise<unknown>((resolve) => { finishOld = resolve; });
    const execute = vi.fn()
      .mockReturnValueOnce(oldRead)
      .mockResolvedValueOnce({ status: 'success' })
      .mockResolvedValueOnce({ status: 'success', clocks: [] });
    const api = new TimeQueryApi(extension(execute));
    const stale = api.listMultiClocks();
    await Promise.resolve();
    await api.removeMultiClock('clock-a');
    const refreshed = api.listMultiClocks();
    expect(refreshed).not.toBe(stale);
    finishOld!({ status: 'success', clocks: [{ clock_id: 'clock-a' }] });
    await stale;
    await expect(refreshed).resolves.toEqual({ status: 'success', clocks: [] });
    expect(execute).toHaveBeenCalledTimes(3);
    expect(execute).toHaveBeenNthCalledWith(2, {
      mode: 'multi_clock', action: 'remove', clock_id: 'clock-a',
    });
    expect(execute).toHaveBeenNthCalledWith(3, { mode: 'multi_clock', action: 'list' });
  });

  it('does not replay alarm creation and preserves the original 429 error', async () => {
    const error = new ApiError(429, 'Throttled', {}, 4);
    const execute = vi.fn().mockRejectedValue(error);
    const api = new TimeQueryApi(extension(execute));
    await expect(api.createAlarm({ title: 'Morning reminder', alarm_datetime: '2026-11-23T09:00:00', timezone: 'America/Detroit', enabled: true })).rejects.toBe(error);
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
  it('does not invalidate existing reads when a mutation fails its acknowledgement', async () => {
    let releaseOld: ((value: unknown) => void) | undefined;
    const oldRead = new Promise<unknown>((resolve) => { releaseOld = resolve; });
    const execute = vi.fn().mockReturnValueOnce(oldRead)
      .mockResolvedValueOnce({ status: 'error', error: 'Storage unavailable' });
    const api = new TimeQueryApi(extension(execute));
    const pending = api.getAlarms();
    await Promise.resolve();
    await expect(api.deleteAlarm('alarm-a')).rejects.toThrow('Storage unavailable');
    const coalesced = api.getAlarms();
    expect(coalesced).toBe(pending);
    releaseOld!({ status: 'success', alarms: [] });
    await Promise.all([pending, coalesced]);
    expect(execute).toHaveBeenCalledTimes(2);
  });

});
