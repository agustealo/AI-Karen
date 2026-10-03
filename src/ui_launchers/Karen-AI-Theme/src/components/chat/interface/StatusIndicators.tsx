import { AlertCircle, CheckCircle, WifiOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { Session } from '../types';

interface StatusIndicatorsProps {
  isBackendOffline: boolean;
  error: string | null;
  currentSession: Session | null;
  isLoading?: boolean;
  isLocalRecoveryUnconfirmed?: boolean;
}

const reloadPage = () => {
  if (typeof window !== 'undefined') {
    window.location.reload();
  }
};

const getSafeErrorMessage = (error: string | null): string => {
  return typeof error === 'string' ? error.trim() : '';
};

export function StatusIndicators({
  isBackendOffline,
  error,
  currentSession,
  isLoading = false,
  isLocalRecoveryUnconfirmed = false,
}: StatusIndicatorsProps) {
  const errorMessage = getSafeErrorMessage(error);
  const shouldShowError = Boolean(errorMessage) && !isBackendOffline;
  const shouldShowEmptySession =
    Boolean(currentSession) &&
    currentSession?.messageCount === 0 &&
    !isLoading &&
    !isBackendOffline &&
    !shouldShowError;

  return (
    <>
      {isBackendOffline && (
        <div
          role="alert"
          aria-live="assertive"
          className="sticky top-0 z-10 flex items-center justify-between border-b border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive shadow-sm ring-1 ring-destructive/20 backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-300"
        >
          <div className="flex items-center gap-3">
            <WifiOff className="h-5 w-5 shrink-0 animate-pulse" aria-hidden="true" />

            <div className="flex flex-col gap-1">
              <span className="font-medium">Backend Connection Lost</span>
              <span className="text-xs opacity-90">
                Operating in offline mode with limited functionality.
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={reloadPage}
            className="rounded-md bg-destructive/20 px-3 py-1 text-xs transition-colors hover:bg-destructive/30"
            aria-label="Retry backend connection"
          >
            Retry
          </button>
        </div>
      )}

      {shouldShowError && (
        <div
          role="alert"
          aria-live="assertive"
          className="sticky top-0 z-10 flex items-center justify-between border-b border-destructive/20 bg-destructive/10 p-3 text-sm text-destructive shadow-sm ring-1 ring-destructive/20 backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-300"
        >
          <div className="flex items-center gap-3">
            <AlertCircle
              className="h-5 w-5 shrink-0 animate-bounce"
              aria-hidden="true"
            />

            <div className="flex flex-col gap-1">
              <span className="font-medium">Error Occurred</span>
              <span className="text-xs opacity-90">{errorMessage}</span>
            </div>
          </div>

          <button
            type="button"
            onClick={reloadPage}
            className="rounded-md bg-destructive/20 px-3 py-1 text-xs transition-colors hover:bg-destructive/30"
            aria-label="Reload page to recover from error"
          >
            Reload
          </button>
        </div>
      )}


      {isLocalRecoveryUnconfirmed && !isBackendOffline && !shouldShowError && (
        <div
          role="status"
          aria-live="polite"
          data-testid="local-recovery-unconfirmed"
          className="sticky top-0 z-10 flex items-center gap-3 border-b border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-700 shadow-sm ring-1 ring-amber-500/20 backdrop-blur-sm dark:text-amber-300"
        >
          <AlertCircle className="h-5 w-5 shrink-0" aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-medium">Local recovery only</span>
            <span className="text-xs opacity-90">
              Restored messages from this device are visible, but the server has not
              confirmed them in durable conversation history yet.
            </span>
          </div>
        </div>
      )}

      {shouldShowEmptySession && currentSession && (
        <div
          /*
           * This is a calm empty-session hint, not a runtime health signal.
           * Keep it hidden while loading, offline, or showing errors so it does
           * not visually compete with real system status.
           */
          className="sticky top-0 z-10 flex items-center justify-center gap-3 border-b border-border bg-muted/50 p-3 text-sm backdrop-blur-sm"
          aria-live="polite"
        >
          <CheckCircle
            className="h-5 w-5 shrink-0 text-green-500"
            aria-hidden="true"
          />

          <div className="flex flex-col items-center gap-1">
            <span className="font-medium">
              {currentSession.title || 'New Conversation'}
            </span>

            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                {currentSession.messageCount} messages
              </Badge>

              <span className="text-xs opacity-70">Start chatting with Karen</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}