import { useCallback } from 'react';

const REQUEST_CANCELLED_MESSAGE = 'Request cancelled by user.';

/**
 * UI cancellation only. The owning chat request's finally block is responsible
 * for releasing the submit lock, controller reference, and loading state.
 * Releasing them here would let a previous aborted request race with a new one.
 */
export function useRequestHandlers(
  submitInFlightRef: React.MutableRefObject<boolean>,
  activeRequestControllerRef: React.MutableRefObject<AbortController | null>,
  setProcessingStatus: React.Dispatch<React.SetStateAction<string>>,
) {
  const stopActiveRequest = useCallback(() => {
    if (!submitInFlightRef.current) {
      return;
    }

    const controller = activeRequestControllerRef.current;
    if (controller && !controller.signal.aborted) {
      controller.abort();
    }

    // No timer: status cleanup belongs to the same request that owns the lock.
    setProcessingStatus(REQUEST_CANCELLED_MESSAGE);
  }, [submitInFlightRef, activeRequestControllerRef, setProcessingStatus]);

  return { stopActiveRequest };
}
