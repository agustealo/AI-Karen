import { useCallback, useEffect, useRef } from 'react';

const REQUEST_CANCELLED_MESSAGE = 'Request cancelled by user.';
const CLEAR_CANCEL_STATUS_DELAY_MS = 2000;

export function useRequestHandlers(
  submitInFlightRef: React.MutableRefObject<boolean>,
  activeRequestControllerRef: React.MutableRefObject<AbortController | null>,
  setProcessingStatus: React.Dispatch<React.SetStateAction<string>>,
) {
  const clearStatusTimerRef = useRef<number | null>(null);

  const clearPendingStatusTimer = useCallback(() => {
    if (clearStatusTimerRef.current === null || typeof window === 'undefined') {
      return;
    }

    window.clearTimeout(clearStatusTimerRef.current);
    clearStatusTimerRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      clearPendingStatusTimer();
    };
  }, [clearPendingStatusTimer]);

  const stopActiveRequest = useCallback(() => {
    /*
     * This hook owns frontend cancellation only:
     * - clear the local submit lock
     * - abort the active fetch/SSE request
     * - update transient UI status
     *
     * It must not invent provider/degraded metadata. Runtime truth still comes
     * from the backend response path when a request completes normally.
     */
    // Keep the submit lock held until the stream's finally block.
    if (!submitInFlightRef.current) return;

    const activeController = activeRequestControllerRef.current;

    if (activeController && !activeController.signal.aborted) {
      activeController.abort();
    }

    setProcessingStatus(REQUEST_CANCELLED_MESSAGE);

    clearPendingStatusTimer();

    if (typeof window !== 'undefined') {
      clearStatusTimerRef.current = window.setTimeout(() => {
        setProcessingStatus('');
        clearStatusTimerRef.current = null;
      }, CLEAR_CANCEL_STATUS_DELAY_MS);
    }
  }, [
    activeRequestControllerRef,
    clearPendingStatusTimer,
    setProcessingStatus,
    submitInFlightRef,
  ]);

  return { stopActiveRequest };
}