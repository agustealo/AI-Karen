"use client";

/**
 * One canonical draft owner: authenticated ConversationRuntimeGateway.
 * No localStorage, SDK checkpoint, or transcript write. Server-side CAS
 * revisions protect multiple tabs/users from stale writes.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient, ApiError } from "@/lib/api";

export type DraftAttachment = { source_id: string; revision: string };
type DraftRecord = { text: string; revision: number; attachment_references: DraftAttachment[] };

function validAttachments(value: unknown): value is DraftAttachment[] {
  if (!Array.isArray(value) || value.length > 12) return false;
  const seen = new Set<string>();
  return value.every((ref: unknown) => {
    if (!ref || typeof ref !== "object" || Array.isArray(ref)) return false;
    const item = ref as Record<string, unknown>;
    if (Object.keys(item).length !== 2 ||
        typeof item.source_id !== "string" ||
        !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(item.source_id) ||
        typeof item.revision !== "string" || !/^[a-f0-9]{64}$/.test(item.revision) ||
        seen.has(item.source_id)) return false;
    seen.add(item.source_id);
    return true;
  });
}

function sameAttachments(a: DraftAttachment[], b: DraftAttachment[]): boolean {
  return a.length === b.length && a.every((ref, i) =>
    ref.source_id === b[i].source_id && ref.revision === b[i].revision);
}
export type DraftStatus = "loading" | "ready" | "conflict" | "unavailable";
const MAX_CHARS = 65536;
const MAX_BYTES = 262144;
const SAVE_DELAY = 450;
const RECOVERY_DELAY_MS = 10000;

function validDraft(value: unknown): value is DraftRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const result = value as Record<string, unknown>;
  return typeof result.text === "string" &&
    result.text.length <= MAX_CHARS &&
    new TextEncoder().encode(result.text).length <= MAX_BYTES &&
    typeof result.revision === "number" &&
    Number.isSafeInteger(result.revision) && result.revision >= 0 &&
    validAttachments(result.attachment_references);
}

export function useKarenPersistedDraft(conversationId: string) {
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<DraftAttachment[]>([]);
  const attachmentsRef = useRef<DraftAttachment[]>([]);
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
  const pendingSaveRef = useRef<Promise<boolean> | null>(null);
  // Notifications contain only a revision. Draft content stays in the
  // authenticated PostgreSQL-backed conversation repository.
  const draftChannelRef = useRef<BroadcastChannel | null>(null);

  const endpoint = "/api/conversations/" + encodeURIComponent(conversationId) + "/draft";

  const readText = useCallback(() => textRef.current, []);
  const updateAttachments = useCallback((value: DraftAttachment[]) => {
    if (!activeRef.current || !validAttachments(value) ||
        sameAttachments(value, attachmentsRef.current)) return;
    const next = value.map(ref => ({ ...ref }));
    attachmentsRef.current = next;
    dirtyRef.current = true;
    setAttachments(next);
    setSynced(false);
    setVersion(v => v + 1);
  }, []);

  const announceRevision = useCallback((revision: number) => {
    try {
      draftChannelRef.current?.postMessage({ revision });
    } catch {
      // Cross-tab notification is best-effort; the verified CAS receipt
      // remains authoritative even when this browser feature fails.
    }
  }, []);

  const setText = useCallback((value: string) => {
    if (typeof value !== "string" || value.length > MAX_CHARS ||
        new TextEncoder().encode(value).length > MAX_BYTES) {
      return;
    }
    // CopilotKit may emit an unchanged controlled value when a completed run
    // rehydrates the composer. An identical value is not a new user edit:
    // marking it dirty would schedule a redundant CAS write (including an
    // empty draft after a confirmed clear), advancing the server revision
    // before the user's next actual follow-up.
    if (value === textRef.current) return;
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
      const response: unknown = await apiClient.get<DraftRecord>(endpoint + "?include_attachments=true");
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
          !dirtyRef.current && (textRef.current !== saved.text ||
            !sameAttachments(attachmentsRef.current, saved.attachment_references))) {
        throw new Error("Canonical draft changed without a new revision");
      }
      revisionRef.current = saved.revision;
      textRef.current = saved.text;
      attachmentsRef.current = saved.attachment_references;
      setAttachments(saved.attachment_references);
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
    attachmentsRef.current = [];
    setAttachments([]);
    pendingSaveRef.current = null;
    setSynced(false);
    setStatus("loading");
    setFailureStatus(null);
    void refresh(true);
    // A healthy, unchanged composer must not generate network traffic while
    // idle. Refresh only on a real foreground transition or a peer's CAS.
    const effectGeneration = generationRef.current;
    let resumeQueued = false;
    const onResume = () => {
      if (document.hidden || dirtyRef.current || resumeQueued) return;
      resumeQueued = true;
      queueMicrotask(() => {
        resumeQueued = false;
        if (activeRef.current && generationRef.current === effectGeneration &&
            !document.hidden && !dirtyRef.current) {
          void refresh(false);
        }
      });
    };
    window.addEventListener("focus", onResume);
    document.addEventListener("visibilitychange", onResume);

    // The channel never carries draft text, user identity or credentials.
    // Every notification causes an authenticated canonical reread, not a
    // client-side overwrite or a CopilotKit model submission.
    if (typeof BroadcastChannel !== "undefined") {
      try {
        const channel = new BroadcastChannel("karen-composer-draft:" + conversationId);
        draftChannelRef.current = channel;
        channel.onmessage = (event: MessageEvent<unknown>) => {
          const payload = event.data;
          if (!payload || typeof payload !== "object" || Array.isArray(payload)) return;
          const revision = (payload as Record<string, unknown>).revision;
          if (typeof revision !== "number" || !Number.isSafeInteger(revision) ||
              revision < 0 || revisionRef.current === null ||
              revision <= revisionRef.current || document.hidden ||
              dirtyRef.current || busyRef.current) return;
          void refresh(false);
        };
      } catch {
        // No BroadcastChannel support: focus and visibility refresh still work.
        draftChannelRef.current = null;
      }
    }

    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      readSequenceRef.current += 1;
      abortRef.current?.abort();
      window.removeEventListener("focus", onResume);
      document.removeEventListener("visibilitychange", onResume);
      draftChannelRef.current?.close();
      draftChannelRef.current = null;
      // Clear private transient input on unmount/logout, never mirror in storage.
      textRef.current = "";
      attachmentsRef.current = [];
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
    intendedAttachments: DraftAttachment[],
  ): Promise<DraftRecord> => {
    try {
      const receipt: unknown = await apiClient.put<DraftRecord>(
        endpoint, { text: intendedText, expected_revision: expectedRevision,
          attachment_references: intendedAttachments },
        { signal },
      );
      if (!validDraft(receipt) || receipt.text !== intendedText ||
          receipt.revision !== expectedRevision + 1 ||
          !sameAttachments(receipt.attachment_references, intendedAttachments)) {
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
        saved = await apiClient.get<DraftRecord>(endpoint + "?include_attachments=true");
      } catch {
        throw error;
      }
      if (!validDraft(saved) || saved.text !== intendedText ||
          saved.revision !== expectedRevision + 1 ||
          !sameAttachments(saved.attachment_references, intendedAttachments)) {
        throw error;
      }
      return saved;
    }
  }, [endpoint]);

  const save = useCallback(async (): Promise<boolean> => {
    if (!activeRef.current || !dirtyRef.current ||
        busyRef.current || revisionRef.current === null) return false;
    busyRef.current = true;
    const generation = generationRef.current;
    const sentText = textRef.current;
    const sentAttachments = attachmentsRef.current;
    const expectedRevision = revisionRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await commitDraftWrite(
        sentText, expectedRevision, controller.signal, sentAttachments,
      );
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return false;
      revisionRef.current = response.revision;
      readSequenceRef.current += 1;
      announceRevision(response.revision);
      if (textRef.current === sentText && sameAttachments(attachmentsRef.current, sentAttachments)) {
        dirtyRef.current = false;
        setSynced(true);
      } else {
        // A new edit arrived while the previous write was pending.
        // Keep it unsynced, then drain it with the new revision.
        setVersion(v => v + 1);
      }
      setStatus("ready");
      setFailureStatus(null);
      return true;
    } catch (error) {
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return false;
      setSynced(false);
      setStatus(error instanceof ApiError && error.status === 409 ?
        "conflict" : "unavailable");
      setFailureStatus(error instanceof ApiError ? error.status : null);
      return false;
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (generationRef.current === generation) busyRef.current = false;
    }
  }, [commitDraftWrite, announceRevision]);

  const startSave = useCallback((): Promise<boolean> => {
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
        revisionRef.current === null || attachmentsRef.current.length > 0 || !submittedText.trim()) {
      return false;
    }
    if (textRef.current.trim() !== submittedText.trim()) {
      if (textRef.current === "") {
        textRef.current = submittedText;
      } else {
        return false;
      }
    }
    busyRef.current = true;
    const generation = generationRef.current;
    const originalText = textRef.current;
    const expectedRevision = revisionRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await commitDraftWrite(
        "", expectedRevision, controller.signal, [],
      );
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return false;
      revisionRef.current = response.revision;
      readSequenceRef.current += 1;
      announceRevision(response.revision);
      if (attachmentsRef.current.length === 0 && (textRef.current === originalText || textRef.current === "")) {
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
      if (generationRef.current === generation) busyRef.current = false;
    }
  }, [commitDraftWrite, announceRevision]);

  const flushSubmission = useCallback(async (
    submittedText: string, legacyOptimisticClear: boolean,
  ): Promise<boolean> => {
    // Enter is a real user gesture, not permission to skip persistence.
    // Flush an edited draft immediately and await a verified CAS receipt
    // before deriving an original submission identity or the legacy clear.
    if (!activeRef.current || revisionRef.current === null ||
        attachmentsRef.current.length > 0 || !submittedText.trim()) {
      return false;
    }
    const generation = generationRef.current;
    // Only the legacy path tolerates a synchronous SDK optimistic clear.
    // Governed submission must match the actual composer, never reconstruct
    // a retired or concurrently replaced draft from stale callback text.
    if (textRef.current.trim() !== submittedText.trim()) {
      if (legacyOptimisticClear && textRef.current === "") {
        textRef.current = submittedText;
        dirtyRef.current = true;
      } else {
        return false;
      }
    }
    const pending = pendingSaveRef.current;
    if (pending) {
      const ok = await pending;
      if (!ok) return false;
    }
    if (!activeRef.current || generationRef.current !== generation ||
        attachmentsRef.current.length > 0) return false;
    if (textRef.current.trim() !== submittedText.trim()) {
      if (legacyOptimisticClear && textRef.current === "") {
        textRef.current = submittedText;
        dirtyRef.current = true;
      } else {
        return false;
      }
    }
    if (dirtyRef.current) {
      const ok = await startSave();
      if (!ok) return false;
    }
    if (!activeRef.current || generationRef.current !== generation ||
        busyRef.current || attachmentsRef.current.length > 0) {
      return false;
    }
    // If startSave succeeded, but an optimistic clear arrived while startSave
    // was in flight, textRef became "" and dirtyRef remained true.
    // Reset dirtyRef since submittedText was confirmed saved.
    if (dirtyRef.current) {
      if (!legacyOptimisticClear) return false;
      if (textRef.current === "" || textRef.current.trim() === submittedText.trim()) {
        textRef.current = submittedText;
        dirtyRef.current = false;
      } else {
        return false;
      }
    }
    return textRef.current.trim() === submittedText.trim();
  }, [startSave]);

  const prepareSubmission = useCallback(async (submittedText: string): Promise<boolean> => {
    if (!await flushSubmission(submittedText, true)) return false;
    return clearBeforeSubmit(submittedText);
  }, [flushSubmission, clearBeforeSubmit]);

  // Governed admission binds the original saved revision to the run.
  // Do not clear or advance this revision in the browser: the transcript
  // transaction retires it only after the completed pair is durable.
  const prepareRevisionSubmission = useCallback(async (
    submittedText: string,
  ): Promise<string | null> => {
    const generation = generationRef.current;
    if (!await flushSubmission(submittedText, false)) return null;
    const revision = revisionRef.current;
    if (!activeRef.current || generationRef.current !== generation ||
        busyRef.current || dirtyRef.current || attachmentsRef.current.length > 0 ||
        textRef.current.trim() !== submittedText.trim() ||
        revision === null || revision < 1 || revision > Number.MAX_SAFE_INTEGER - 1) return null;
    return "draft-v1-" + revision;
  }, [flushSubmission]);

  const refreshSubmittedDraft = useCallback(async () => {
    // Preserve a newer unsent edit; the regular CAS path owns its recovery.
    await refresh(false);
  }, [refresh]);

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
            const response: unknown = await apiClient.get<DraftRecord>(endpoint + "?include_attachments=true");
            if (!activeRef.current || generationRef.current !== generation ||
                readSequenceRef.current !== sequence) return;
            if (!validDraft(response)) throw new Error("Invalid server draft receipt");
            const saved = response as DraftRecord;
            revisionRef.current = saved.revision;
            if ((saved.text !== "" && saved.text !== textRef.current) ||
                (saved.attachment_references.length > 0 &&
                  !sameAttachments(saved.attachment_references, attachmentsRef.current))) {
              setStatus("conflict");
              setSynced(false);
              return;
            }
            if (saved.text === textRef.current &&
                sameAttachments(saved.attachment_references, attachmentsRef.current)) {
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
            if (generationRef.current === generation) busyRef.current = false;
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
    }, RECOVERY_DELAY_MS);
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
    draft, setText, readText, attachments, updateAttachments, status, synced, failureStatus,
    clearBeforeSubmit, prepareSubmission, prepareRevisionSubmission, refreshSubmittedDraft,
    retry, discardAndReload,
  };
}
