import React from 'react';
import { StopwatchState } from '../types';
import { formatMsToStopwatch } from '../utils/timeFormatters';

interface StopwatchPanelProps {
  state: StopwatchState | null;
  onAction: (action: string) => void;
}

export const StopwatchPanel: React.FC<StopwatchPanelProps> = ({ state, onAction }) => {
  // We use local client ticking if the stopwatch is active to avoid hammering backend
  const [localDisplay, setLocalDisplay] = React.useState<number>(0);

  React.useEffect(() => {
    if (!state) return;

    let interval: NodeJS.Timeout | null = null;
    if (state.running && !state.paused && state.last_updated_at) {
      // It's actively running, tick locally based on last known state
      interval = setInterval(() => {
        const nowMs = Date.now();
        const lastUpdatedMs = new Date(state.last_updated_at!).getTime();
        setLocalDisplay(state.elapsed_ms + (nowMs - lastUpdatedMs));
      }, 50); // fast UI tick
    } else {
      setLocalDisplay(state.elapsed_ms || 0);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [state]);

  const displayMs = state ? localDisplay : 0;
  const isRunning = state?.running && !state.paused;
  const isPaused = state?.running && state.paused;

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden shadow-xl shadow-black/20">
      <div className="p-6 flex flex-col items-center">
        <div className="text-muted-foreground text-sm uppercase tracking-[0.2em] mb-4">Stopwatch</div>
        <div className="text-6xl font-extralight text-foreground font-mono tabular-nums tracking-tighter mb-8">
          {formatMsToStopwatch(displayMs)}
        </div>

        <div className="flex justify-center gap-4">
          {!state?.running ? (
             <ActionButton onClick={() => onAction('start')} primary color="bg-emerald-600 hover:bg-emerald-500 text-white">Start</ActionButton>
          ) : (
            <>
              {isRunning && (
                <ActionButton onClick={() => onAction('pause')} color="bg-amber-600 hover:bg-amber-500 text-white">Pause</ActionButton>
              )}
              {isPaused && (
                <ActionButton onClick={() => onAction('resume')} color="bg-emerald-600 hover:bg-emerald-500 text-white">Resume</ActionButton>
              )}

              <ActionButton onClick={() => onAction('stop')} color="bg-red-600 hover:bg-red-500 text-white">Stop</ActionButton>
            </>
          )}

          <ActionButton onClick={() => onAction('reset')} color="bg-secondary hover:bg-secondary/80 text-secondary-foreground">Reset</ActionButton>
        </div>
      </div>
    </div>
  );
};

const ActionButton: React.FC<{ onClick: () => void; children: React.ReactNode; color: string; primary?: boolean }> = ({ onClick, children, color, primary }) => (
  <button
    onClick={onClick}
    className={`px-6 py-2 rounded-full font-medium transition-all transform active:scale-95 ${color} ${primary ? 'w-24 border border-white/10' : 'w-24'}`}
  >
    {children}
  </button>
);
