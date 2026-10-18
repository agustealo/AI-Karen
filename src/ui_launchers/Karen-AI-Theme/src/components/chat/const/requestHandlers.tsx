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
  setIsLoading: React.Dispatch<React.SetStateAction<boolean>>,
) {
  const stopActiveRequest = useCallback(() => {
    if (!submitInFlightRef.current) {
      return;
    }

    const controller = activeRequestControllerRef.current;
    if (!controller) {
      // Restored local in-flight snapshots have no fetch to abort and no
      // request finally block to release the lock. Unlock that orphan only.
      submitInFlightRef.current = false;
      setIsLoading(false);
      setProcessingStatus('');
      return;
    }

    if (!controller.signal.aborted) {
      controller.abort();
    }

    // A live request still owns its eventual finally cleanup.
    setProcessingStatus(REQUEST_CANCELLED_MESSAGE);
  }, [submitInFlightRef, activeRequestControllerRef, setProcessingStatus, setIsLoading]);

  return { stopActiveRequest };
}
