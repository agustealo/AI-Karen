export interface TimezoneResolutionMeta {
  query: string;
  resolvedTimezone: string;
  label?: string;
  isAmbiguousDefault: boolean;
  resolutionType: string;
}

export interface ExternalSync {
  checked: boolean;
  available: boolean;
  provider: string | null;
  offset_ms: number | null;
}

export interface SourceDetail {
  clock: string;
  timezone_source: string;
  external_sync_checked?: boolean;
  storage: string;
}

export interface TimePayload {
  status: string;
  mode: string;
  source: string;
  provider: string;
  provider_status: string;
  external_sync: ExternalSync;
  source_detail: SourceDetail;
  timestamp: string;
  timestamp_unix: number;
  timestamp_utc: string;
  iso: string;
  formatted: string;
  date: string;
  time: string;
  weekday: string;
  month: string;
  year: number;
  timezone: string;
  utc_offset: string;
  value?: string | number;
  resolution_meta?: TimezoneResolutionMeta;
  metadata?: Record<string, unknown>;
}

export interface ClockItem extends TimePayload {
  label: string;
  clock_id?: string;
}

export interface StopwatchState {
  stopwatch_id: string;
  label?: string | null;
  created_at: string;
  started_at: string | null;
  elapsed_ms: number;
  running: boolean;
  paused: boolean;
  last_updated_at: string | null;
}

export interface AlarmItem {
  alarm_id: string;
  title: string;
  alarm_datetime: string;
  timezone: string;
  enabled: boolean;
  recurrence?: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface TimezoneConversionResult {
  status: string;
  mode: string;
  error?: string;
  source_datetime: {
    datetime: string;
    timezone: string;
    utc_offset: string;
    date: string;
    time: string;
    resolution_meta?: TimezoneResolutionMeta;
  };
  converted_datetime: {
    datetime: string;
    timezone: string;
    utc_offset: string;
    date: string;
    time: string;
    resolution_meta?: TimezoneResolutionMeta;
  };
  value: string;
  metadata?: Record<string, unknown>;
}

export interface AlarmCreateParams {
  title: string;
  alarm_datetime: string;
  timezone: string;
  enabled: boolean;
  recurrence?: string | null;
}

export interface AlarmUpdateParams {
  title?: string;
  alarm_datetime?: string;
  timezone?: string;
  enabled?: boolean;
  recurrence?: string | null;
}

export interface TimeQueryState {
  loading: boolean;
  error: string | null;
  currentTime: TimePayload | null;
  worldTime: TimePayload | null;
  clocks: ClockItem[];
  stopwatch: StopwatchState | null;
  alarms: AlarmItem[];
  conversion: TimezoneConversionResult | null;
  diagnostics: Record<string, unknown> | null;
}
