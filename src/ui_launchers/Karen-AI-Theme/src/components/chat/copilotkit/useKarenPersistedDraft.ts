"use client";

/**
 * One canonical draft owner: authenticated ConversationRuntimeGateway.
 * No localStorage, SDK checkpoint, or transcript write. Server-side CAS
 * revisions protect multiple tabs/users from stale writes.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient, ApiError } from "@/lib/api";

type DraftRecord = { text: string; revision: number };
export type DraftStatus = "loading" | "ready" | "conflict" | "unavailable";
const MAX_CHARS = 65536;
const MAX_BYTES = 262144;
const SAVE_DELAY = 450;
const REFRESH_DELAY = 10000;

function validDraft(value: unknown): value is DraftRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const result = value as Record<string, unknown>;
  return typeof result.text === "string" &&
    result.text.length <= MAX_CHARS &&
    new TextEncoder().encode(result.text).length <= MAX_BYTES &&
    typeof result.revision === "number" &&
    Number.isSafeInteger(result.revision) && result.revision >= 0;
}

export function useKarenPersistedDraft(conversationId: string) {
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<DraftStatus>("loading");
  const [synced, setSynced] = useState(false);
  const [failureStatus, setFailureStatus] = useState<number | null>(null);
  const [version, setVersion] = useState(0);
  const textRef = useRef("");
  const revisionRef = useRef<number | null>(null);
  const dirtyRef = useRef(false);
  const busyRef = useRef(false);
  const activeRef = useRef(false);
  const generationRef = useRef(0);
  // Parallel focus/interval reads may complete out of order. Invalidate all
  // older reads after each new read or confirmed write.
  const readSequenceRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  // Reuse the existing CAS write when Submit races with the debounce timer.
  // Do not create a second draft store or submit before an authenticated ack.
  const pendingSaveRef = useRef<Promise<void> | null>(null);

  const endpoint = "/api/conversations/" + encodeURIComponent(conversationId) + "/draft";

  const readText = useCallback(() => textRef.current, []);

  const setText = useCallback((value: string) => {
    if (typeof value !== "string" || value.length > MAX_CHARS ||
        new TextEncoder().encode(value).length > MAX_BYTES) {
      return;
    }
    textRef.current = value;
    dirtyRef.current = true;
    setSynced(false);
    setDraft(value);
    setVersion(v => v + 1);
  }, []);

  const refresh = useCallback(async (force = false) => {
    if (!activeRef.current || busyRef.current ||
        (dirtyRef.current && !force)) return;
    const generation = generationRef.current;
    const readSequence = ++readSequenceRef.current;
    try {
      const response: unknown = await apiClient.get<DraftRecord>(endpoint);
      if (!activeRef.current || generationRef.current !== generation ||
          readSequenceRef.current !== readSequence) return;
      if (!validDraft(response)) throw new Error("Invalid server draft receipt");
      if (dirtyRef.current && !force) return;
      const saved = response as DraftRecord;
      const knownRevision = revisionRef.current;
      if (knownRevision !== null && saved.revision < knownRevision) {
        // Canonical storage must never appear to roll its revision backward.
        // Report unavailability, rather than leave an explicit reload stuck.
        throw new Error("Canonical draft revision regressed");
      }
      if (knownRevision !== null && saved.revision === knownRevision &&
          !dirtyRef.current && textRef.current !== saved.text) {
        throw new Error("Canonical draft changed without a new revision");
      }
      revisionRef.current = saved.revision;
      textRef.current = saved.text;
      dirtyRef.current = false;
      setDraft(saved.text);
      setSynced(true);
      setStatus("ready");
      setFailureStatus(null);
    } catch (error) {
      if (!activeRef.current || generationRef.current !== generation ||
          readSequenceRef.current !== readSequence) return;
      // Never pass off a local draft as saved after an API failure.
      setStatus("unavailable");
      setFailureStatus(error instanceof ApiError ? error.status : null);
      setSynced(false);
    }
  }, [endpoint]);

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    readSequenceRef.current += 1;
    revisionRef.current = null;
    textRef.current = "";
    dirtyRef.current = false;
    busyRef.current = false;
    setDraft("");
    setSynced(false);
    setStatus("loading");
    setFailureStatus(null);
    void refresh(true);
    const onFocus = () => {
      if (!document.hidden && !dirtyRef.current) void refresh(false);
    };
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(onFocus, REFRESH_DELAY);
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      readSequenceRef.current += 1;
      abortRef.current?.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      // Clear private transient input on unmount/logout, never mirror in storage.
      textRef.current = "";
      revisionRef.current = null;
      dirtyRef.current = false;
    };
  }, [conversationId, refresh]);

  // A proxy 502 or network rejection does not prove a write failed:
  // PostgreSQL may have committed the CAS before its HTTP receipt was lost.
  // Never replay that mutation. An authenticated readback is the only safe
  // way to acknowledge its exact intended text and next revision.
  const commitDraftWrite = useCallback(async (
    intendedText: string, expectedRevision: number, signal: AbortSignal,
  ): Promise<DraftRecord> => {
    try {
      const receipt: unknown = await apiClient.put<DraftRecord>(
        endpoint, { text: intendedText, expected_revision: expectedRevision },
        { signal },
      );
      if (!validDraft(receipt) || receipt.text !== intendedText ||
          receipt.revision !== expectedRevision + 1) {
        throw new Error("Invalid draft CAS receipt");
      }
      return receipt;
    } catch (error) {
      if (signal.aborted ||
          !(error instanceof TypeError ||
            (error instanceof ApiError && [502, 503, 504].includes(error.status)))) {
        throw error;
      }
      // A stale/foreign/different-revision result is NOT an acknowledgement.
      // Fail closed if the read is unavailable or cannot prove this write.
      let saved: unknown;
      try {
        saved = await apiClient.get<DraftRecord>(endpoint);
      } catch {
        throw error;
      }
      if (!validDraft(saved) || saved.text !== intendedText ||
          saved.revision !== expectedRevision + 1) {
        throw error;
      }
      return saved;
    }
  }, [endpoint]);

  const save = useCallback(async () => {
    if (!activeRef.current || !dirtyRef.current ||
        busyRef.current || revisionRef.current === null) return;
    busyRef.current = true;
    const generation = generationRef.current;
    const sentText = textRef.current;
    const expectedRevision = revisionRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await commitDraftWrite(
        sentText, expectedRevision, controller.signal,
      );
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return;
      revisionRef.current = response.revision;
      readSequenceRef.current += 1;
      if (textRef.current === sentText) {
        dirtyRef.current = false;
        setSynced(true);
      } else {
        // A new edit arrived while the previous write was pending.
        // Keep it unsynced, then drain it with the new revision.
        setVersion(v => v + 1);
      }
      setStatus("ready");
      setFailureStatus(null);
    } catch (error) {
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return;
      setSynced(false);
      setStatus(error instanceof ApiError && error.status === 409 ?
        "conflict" : "unavailable");
      setFailureStatus(error instanceof ApiError ? error.status : null);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      busyRef.current = false;
    }
  }, [commitDraftWrite]);

  const startSave = useCallback((): Promise<void> => {
    if (pendingSaveRef.current) return pendingSaveRef.current;
    const pending = save();
    pendingSaveRef.current = pending;
    void pending.finally(() => {
      if (pendingSaveRef.current === pending) pendingSaveRef.current = null;
    });
    return pending;
  }, [save]);

  useEffect(() => {
    if (status !== "ready" || !dirtyRef.current) return;
    const timeout = window.setTimeout(() => void startSave(), SAVE_DELAY);
    return () => window.clearTimeout(timeout);
  }, [draft, version, startSave, status]);

  const clearBeforeSubmit = useCallback(async (submittedText: string): Promise<boolean> => {
    if (!activeRef.current || busyRef.current || dirtyRef.current ||
        revisionRef.current === null ||
        textRef.current.trim() !== submittedText.trim()) {
      return false;
    }
    busyRef.current = true;
    const generation = generationRef.current;
    const originalText = textRef.current;
    const expectedRevision = revisionRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await commitDraftWrite(
        "", expectedRevision, controller.signal,
      );
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return false;
      revisionRef.current = response.revision;
      readSequenceRef.current += 1;
      if (textRef.current === originalText) {
        textRef.current = "";
        dirtyRef.current = false;
        setDraft("");
        setSynced(true);
      } else {
        // Concurrent editing during the durable clear remains unsent and
        // will be saved under the new revision after the clear completes.
        setVersion(v => v + 1);
      }
      setStatus("ready");
      setFailureStatus(null);
      return true;
    } catch (error) {
      if (activeRef.current && generationRef.current === generation &&
          !controller.signal.aborted) {
        setSynced(false);
        setStatus(error instanceof ApiError && error.status === 409 ?
          "conflict" : "unavailable");
        setFailureStatus(error instanceof ApiError ? error.status : null);
      }
      return false;
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      busyRef.current = false;
    }
  }, [commitDraftWrite]);

  const prepareSubmission = useCallback(async (submittedText: string): Promise<boolean> => {
    // Enter is a real user gesture, not permission to skip persistence.
    // Flush an edited draft immediately and await a verified CAS receipt
    // before the existing revision-fenced clear and one SDK model run.
    if (!activeRef.current || revisionRef.current === null ||
        !submittedText.trim() || textRef.current.trim() !== submittedText.trim()) {
      return false;
    }
    const pending = pendingSaveRef.current;
    if (pending) await pending;
    if (!activeRef.current || textRef.current.trim() !== submittedText.trim()) {
      return false;
    }
    if (dirtyRef.current) await startSave();
    if (!activeRef.current || dirtyRef.current || busyRef.current ||
        textRef.current.trim() !== submittedText.trim()) {
      return false;
    }
    return clearBeforeSubmit(submittedText);
  }, [startSave, clearBeforeSubmit]);

  const retry = useCallback(() => {
    if (!activeRef.current || status !== "unavailable" || busyRef.current) return;

    if (dirtyRef.current) {
      // Keep unsent edits intact and retry the existing revision-fenced write.
      // After an initial read outage, recover the canonical CAS baseline
      // without overwriting text composed during the outage.
      if (revisionRef.current === null) {
        busyRef.current = true;
        const generation = generationRef.current;
        const sequence = ++readSequenceRef.current;
        void (async () => {
          try {
            const response: unknown = await apiClient.get<DraftRecord>(endpoint);
            if (!activeRef.current || generationRef.current !== generation ||
                readSequenceRef.current !== sequence) return;
            if (!validDraft(response)) throw new Error("Invalid server draft receipt");
            const saved = response as DraftRecord;
            revisionRef.current = saved.revision;
            if (saved.text !== "" && saved.text !== textRef.current) {
              setStatus("conflict");
              setSynced(false);
              return;
            }
            if (saved.text === textRef.current) {
              dirtyRef.current = false;
              setSynced(true);
            } else {
              // Local input is still dirty. Its first save must use the
              // retrieved server revision, never a fabricated zero.
              setSynced(false);
              setVersion(v => v + 1);
            }
            setFailureStatus(null);
            setStatus("ready");
          } catch (error) {
            if (activeRef.current && generationRef.current === generation &&
                readSequenceRef.current === sequence) {
              setStatus("unavailable");
              setFailureStatus(error instanceof ApiError ? error.status : null);
              setSynced(false);
            }
          } finally {
            busyRef.current = false;
          }
        })();
        return;
      }
      setStatus("ready");
      setVersion(v => v + 1);
      return;
    }

    // An initial read failure has no revision. A later clean refresh failure
    // also needs an authenticated reread, never a pretend "saved" receipt.
    setStatus("loading");
    void refresh(false);
  }, [refresh, status]);

  // Only retry temporary service outages. Never auto-resolve authorization
  // failures or CAS conflicts, and never replace unsaved local input.
  useEffect(() => {
    if (status !== "unavailable" || failureStatus !== 503) return;
    // The same unavailable state can persist after a failed retry. An interval
    // keeps recovery armed even when a retry fails or the document is hidden.
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") retry();
    }, REFRESH_DELAY);
    return () => window.clearInterval(timer);
  }, [status, failureStatus, retry, version]);

  // Conflict refresh explicitly replaces the local draft. Never do this
  // automatically while unsent edits may still be present.
  const discardAndReload = useCallback(() => {
    if (status !== "conflict" && status !== "unavailable") return;
    dirtyRef.current = false;
    setStatus("loading");
    void refresh(true);
  }, [refresh, status]);

  return {
    draft, setText, readText, status, synced, failureStatus,
    clearBeforeSubmit, prepareSubmission, retry, discardAndReload,
  };
}
