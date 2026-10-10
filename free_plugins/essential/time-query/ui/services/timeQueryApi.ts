import { ExtensionAPI } from '@/lib/extensions/hooks/usePluginExtension';

export class TimeQueryApi {
  private api: ExtensionAPI;

  constructor(api: ExtensionAPI) {
    this.api = api;
  }

  async getCurrentTime(mode: string = 'datetime') {
    return this.api.execute({ mode });
  }

  async getWorldTime(query: string, timezone?: string) {
    return this.api.execute({ mode: 'world_time', query, timezone });
  }

  async getMultiClocks(clocks?: string[]) {
    if (clocks) {
      return this.api.execute({ mode: 'multi_clock', action: 'resolve', clocks });
    }
    return this.listMultiClocks();
  }

  async listMultiClocks() {
    return this.api.execute({ mode: 'multi_clock', action: 'list' });
  }

  async addMultiClock(timezone: string) {
    return this.api.execute({ mode: 'multi_clock', action: 'add', timezone });
  }

  async removeMultiClock(clock_id: string) {
    return this.api.execute({ mode: 'multi_clock', action: 'remove', clock_id });
  }

  async setStopwatchAction(action: string, stopwatch_id: string = 'default') {
    return this.api.execute({ mode: 'stopwatch', action, stopwatch_id });
  }

  async getAlarms() {
    return this.api.execute({ mode: 'alarm', action: 'list' });
  }

  async createAlarm(data: any) {
    return this.api.execute({ mode: 'alarm', action: 'create', ...data });
  }

  async updateAlarm(alarm_id: string, data: any) {
    return this.api.execute({ mode: 'alarm', action: 'update', alarm_id, ...data });
  }

  async deleteAlarm(alarm_id: string) {
    return this.api.execute({ mode: 'alarm', action: 'delete', alarm_id });
  }
  
  async setAlarmStatus(alarm_id: string, enabled: boolean) {
    return this.api.execute({ mode: 'alarm', action: enabled ? 'enable' : 'disable', alarm_id });
  }

  async convertTimezone(datetime: string, from_timezone: string, to_timezone: string) {
    return this.api.execute({ mode: 'convert_timezone', datetime, from_timezone, to_timezone });
  }
}
