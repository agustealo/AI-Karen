import { ApiError } from '@/lib/api';
import type { ExtensionAPI } from '@/lib/extensions/hooks/usePluginExtension';
import type {
  AlarmCreateParams,
  AlarmUpdateParams,
  TimePayload,
  ClockItem,
  StopwatchState,
  AlarmItem,
  TimezoneConversionResult,
} from '../types';

interface BaseResponse {
  status: string;
  mode: string;
  error?: string;
}

interface CurrentTimeResponse extends BaseResponse, TimePayload {}
interface WorldTimeResponse extends BaseResponse, TimePayload {}
interface MultiClockListResponse extends BaseResponse { clocks: ClockItem[] }
interface MultiClockResolveResponse extends BaseResponse { clocks: ClockItem[] }
interface StopwatchResponse extends BaseResponse { stopwatch: StopwatchState }
interface AlarmListResponse extends BaseResponse { alarms: AlarmItem[] }
interface AlarmResponse extends BaseResponse { alarm: AlarmItem }
interface ConversionResponse extends BaseResponse, TimezoneConversionResult {}

/** Retry only known read-only commands, never create/update/delete actions. */
const MAX_READ_RETRY_AFTER_SECONDS = 30;

export class TimeQueryApi {
  private readonly api: ExtensionAPI;
  private readonly readsInFlight = new Map<string, Promise<unknown>>();
  private readTail: Promise<void> = Promise.resolve();
  private readNotBefore = 0;

  constructor(api: ExtensionAPI) {
    this.api = api;
  }

  private async readWithRateLimit<T>(command: Record<string, unknown>): Promise<T> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const delayMs = Math.max(0, this.readNotBefore - Date.now());
      if (delayMs > 0) {
        await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
      }

      try {
        return await this.api.execute(command) as T;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 429) {
          throw error;
        }

        const retryAfter = error.retryAfterSeconds;
        if (retryAfter === null || retryAfter < 0) {
          throw error;
        }

        // Honor the backend's admission time for subsequent reads even if
        // this particular read has exhausted its bounded retry allowance.
        const seconds = Math.max(1, retryAfter);
        this.readNotBefore = Math.max(this.readNotBefore, Date.now() + seconds * 1000);
        if (attempt > 0 || seconds > MAX_READ_RETRY_AFTER_SECONDS) {
          throw error;
        }
      }
    }
    throw new Error('Read-only time query retry exhausted');
  }

  private executeRead<T>(key: string, command: Record<string, unknown>): Promise<T> {
    const existing = this.readsInFlight.get(key);
    if (existing) return existing as Promise<T>;

    // Serialize read-only plugin POSTs to avoid competing startup bursts.
    // Mutation calls bypass this queue and are never replayed.
    const read = this.readTail.then(() => this.readWithRateLimit<T>(command));
    this.readsInFlight.set(key, read);
    this.readTail = read.then(() => undefined, () => undefined);
    void read.then(
      () => { if (this.readsInFlight.get(key) === read) this.readsInFlight.delete(key); },
      () => { if (this.readsInFlight.get(key) === read) this.readsInFlight.delete(key); },
    );
    return read;
  }

  getCurrentTime(mode: string = 'datetime'): Promise<CurrentTimeResponse> {
    return this.executeRead('time:' + mode, { mode });
  }

  getWorldTime(query: string, timezone?: string): Promise<WorldTimeResponse> {
    return this.executeRead(JSON.stringify(['world_time', query, timezone]), { mode: 'world_time', query, timezone });
  }

  resolveMultiClocks(clocks: string[]): Promise<MultiClockResolveResponse> {
    return this.executeRead(JSON.stringify(['resolve', clocks]), { mode: 'multi_clock', action: 'resolve', clocks });
  }

  listMultiClocks(): Promise<MultiClockListResponse> {
    return this.executeRead('clocks:list', { mode: 'multi_clock', action: 'list' });
  }

  addMultiClock(timezone: string): Promise<BaseResponse> {
    return this.api.execute({ mode: 'multi_clock', action: 'add', timezone }) as Promise<BaseResponse>;
  }

  removeMultiClock(clock_id: string): Promise<BaseResponse> {
    return this.api.execute({ mode: 'multi_clock', action: 'remove', clock_id }) as Promise<BaseResponse>;
  }

  setStopwatchAction(action: string, stopwatch_id: string = 'default'): Promise<StopwatchResponse> {
    const command = { mode: 'stopwatch', action, stopwatch_id };
    return action === 'status'
      ? this.executeRead('stopwatch:' + stopwatch_id, command)
      : this.api.execute(command) as Promise<StopwatchResponse>;
  }

  getAlarms(): Promise<AlarmListResponse> {
    return this.executeRead('alarms:list', { mode: 'alarm', action: 'list' });
  }

  createAlarm(data: AlarmCreateParams): Promise<AlarmResponse> {
    return this.api.execute({ mode: 'alarm', action: 'create', ...data }) as Promise<AlarmResponse>;
  }

  updateAlarm(alarm_id: string, data: AlarmUpdateParams): Promise<AlarmResponse> {
    return this.api.execute({ mode: 'alarm', action: 'update', alarm_id, ...data }) as Promise<AlarmResponse>;
  }

  deleteAlarm(alarm_id: string): Promise<BaseResponse> {
    return this.api.execute({ mode: 'alarm', action: 'delete', alarm_id }) as Promise<BaseResponse>;
  }

  setAlarmStatus(alarm_id: string, enabled: boolean): Promise<AlarmResponse> {
    return this.api.execute({ mode: 'alarm', action: enabled ? 'enable' : 'disable', alarm_id }) as Promise<AlarmResponse>;
  }

  convertTimezone(datetime: string, from_timezone: string, to_timezone: string): Promise<ConversionResponse> {
    return this.executeRead(
      JSON.stringify(['convert', datetime, from_timezone, to_timezone]),
      { mode: 'convert_timezone', datetime, from_timezone, to_timezone },
    );
  }
}
