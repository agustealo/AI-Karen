import React, { useMemo } from 'react';
import { usePluginExtension } from '@/lib/extensions/hooks/usePluginExtension';
import { TimeQueryApi } from './services/timeQueryApi';
import { useTimeQuery } from './hooks/useTimeQuery';
import { useWorldClocks } from './hooks/useWorldClocks';
import { useStopwatch } from './hooks/useStopwatch';
import { useAlarms } from './hooks/useAlarms';
import { useTimePayload } from './hooks/useTimePayload';

import { LoadingState } from './components/LoadingState';
import { ErrorState } from './components/ErrorState';
import { TimeHeader } from './components/TimeHeader';
import { CurrentTimePanel } from './components/CurrentTimePanel';
import { WorldClockSearch } from './components/WorldClockSearch';
import { SavedClocksPanel } from './components/SavedClocksPanel';
import { StopwatchPanel } from './components/StopwatchPanel';
import { AlarmPanel } from './components/AlarmPanel';
import { TimezoneConversionPanel } from './components/TimezoneConversionPanel';
import { DiagnosticsPanel } from './components/DiagnosticsPanel';

const TimeQueryPage: React.FC = () => {
  // Integrate with host extension runtime
  const { api, isReady, error: hostError } = usePluginExtension('time-query');
  
  // API Service layer wrapping raw execute calls
  const timeApi = useMemo(() => new TimeQueryApi(api), [api]);

  // Specific Feature hooks
  const { data: timeData, error: timeError, refresh: refreshTime } = useTimeQuery(timeApi);
  const enrichedTime = useTimePayload(timeData);

  const { multiClocksData, error: clocksError, searchWorldTime, addClock, removeClock, refreshClocks } = useWorldClocks(timeApi);
  const { state: stopwatchState, performAction: performStopwatchAction } = useStopwatch(timeApi);
  const { alarms, error: alarmsError, fetchAlarms, createAlarm, deleteAlarm, toggleAlarm } = useAlarms(timeApi);

  if (!isReady) {
    return <LoadingState message="Initializing Time Query Plugin..." />;
  }

  if (hostError) {
    return <ErrorState error={`Extension Host Error: ${hostError}`} />;
  }

  // Dashboard layout
  return (
    <div className="flex flex-col w-full h-[calc(100vh-64px)] overflow-y-auto text-foreground bg-background">
      <TimeHeader time={enrichedTime} />

      <div className="p-6 max-w-7xl mx-auto space-y-6 w-full">
        {/* Top Row: Current Time Details & World Search */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <CurrentTimePanel payload={enrichedTime} />
          <WorldClockSearch onSearch={searchWorldTime} onAddClock={addClock} />
        </div>

        {/* Middle Row: Clocks grid & Stopwatch */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 shadow-2xl">
            <SavedClocksPanel
              clocksData={multiClocksData}
              onRemoveClock={removeClock}
              onRefresh={refreshClocks}
            />
          </div>
          <div className="lg:col-span-1 border border-border rounded-xl bg-card relative">
            {/* The Stopwatch */}
            <StopwatchPanel state={stopwatchState} onAction={performStopwatchAction} />
          </div>
        </div>

        {/* Third Row: Alarms & Timezone Math */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <AlarmPanel alarms={alarms} onCreate={createAlarm} onDelete={deleteAlarm} onToggle={toggleAlarm} />
          <div className="flex h-full border border-border rounded-xl bg-card flex-col">
            <TimezoneConversionPanel onConvert={(dt, from, to) => timeApi.convertTimezone(dt, from, to)} />
          </div>
        </div>

        {/* Raw Diagnostics for debugging / transparency */}
        {timeData && <DiagnosticsPanel payload={timeData} />}

        {timeError && <ErrorState error={`Sync Error: ${timeError}`} onRetry={refreshTime} />}
        {clocksError && <ErrorState error={`World Clocks: ${clocksError}`} onRetry={refreshClocks} />}
        {alarmsError && <ErrorState error={`Alarms: ${alarmsError}`} onRetry={fetchAlarms} />}
      </div>
    </div>
  );
};

export default TimeQueryPage;
