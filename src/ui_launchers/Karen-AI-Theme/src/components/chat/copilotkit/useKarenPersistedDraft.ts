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
  const [version, setVersion] = useState(0);
  const textRef = useRef("");
  const revisionRef = useRef<number | null>(null);
  const dirtyRef = useRef(false);
  const busyRef = useRef(false);
  const activeRef = useRef(false);
  const generationRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

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
    try {
      const response: unknown = await apiClient.get<DraftRecord>(endpoint);
      if (!activeRef.current || generationRef.current !== generation) return;
      if (!validDraft(response)) throw new Error("Invalid server draft receipt");
      if (dirtyRef.current && !force) return;
      const saved = response as DraftRecord;
      revisionRef.current = saved.revision;
      textRef.current = saved.text;
      dirtyRef.current = false;
      setDraft(saved.text);
      setSynced(true);
      setStatus("ready");
    } catch {
      if (!activeRef.current || generationRef.current !== generation) return;
      // Never pass off a local draft as saved after an API failure.
      setStatus("unavailable");
      setSynced(false);
    }
  }, [endpoint]);

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    revisionRef.current = null;
    textRef.current = "";
    dirtyRef.current = false;
    busyRef.current = false;
    setDraft("");
    setSynced(false);
    setStatus("loading");
    void refresh(true);
    const onFocus = () => {
      if (!document.hidden && !dirtyRef.current) void refresh(false);
    };
    window.addEventListener("focus", onFocus);
    const interval = window.setInterval(onFocus, REFRESH_DELAY);
    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      abortRef.current?.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", onFocus);
      // Clear private transient input on unmount/logout, never mirror in storage.
      textRef.current = "";
      revisionRef.current = null;
      dirtyRef.current = false;
    };
  }, [conversationId, refresh]);

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
      const response: unknown = await apiClient.put<DraftRecord>(
        endpoint, { text: sentText, expected_revision: expectedRevision },
        { signal: controller.signal },
      );
      if (!activeRef.current || generationRef.current !== generation) return;
      if (!validDraft(response) ||
          (response as DraftRecord).text !== sentText ||
          (response as DraftRecord).revision !== expectedRevision + 1) {
        throw new Error("Invalid draft persistence receipt");
      }
      revisionRef.current = (response as DraftRecord).revision;
      if (textRef.current === sentText) {
        dirtyRef.current = false;
        setSynced(true);
      } else {
        // A new edit arrived while the previous write was pending.
        // Keep it unsynced, then drain it with the new revision.
        setVersion(v => v + 1);
      }
      setStatus("ready");
    } catch (error) {
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return;
      setSynced(false);
      setStatus(error instanceof ApiError && error.status === 409 ?
        "conflict" : "unavailable");
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      busyRef.current = false;
    }
  }, [endpoint]);

  useEffect(() => {
    if (status !== "ready" || !dirtyRef.current) return;
    const timeout = window.setTimeout(() => void save(), SAVE_DELAY);
    return () => window.clearTimeout(timeout);
  }, [draft, version, save, status]);

  const clearBeforeSubmit = useCallback(async (submittedText: string): Promise<boolean> => {
    if (!activeRef.current || busyRef.current || dirtyRef.current ||
        revisionRef.current === null ||
        textRef.current.trim() !== submittedText.trim()) {
      return false;
    }
    busyRef.current = true;
    const generation = generationRef.current;
    const expectedRevision = revisionRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response: unknown = await apiClient.put<DraftRecord>(
        endpoint, { text: "", expected_revision: expectedRevision },
        { signal: controller.signal },
      );
      if (!activeRef.current || generationRef.current !== generation ||
          controller.signal.aborted) return false;
      if (!validDraft(response) || (response as DraftRecord).text !== "" ||
          (response as DraftRecord).revision !== expectedRevision + 1) {
        throw new Error("Invalid draft-clear receipt");
      }
      revisionRef.current = (response as DraftRecord).revision;
      if (textRef.current.trim() === submittedText.trim()) {
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
      return true;
    } catch (error) {
      if (activeRef.current && generationRef.current === generation &&
          !controller.signal.aborted) {
        setSynced(false);
        setStatus(error instanceof ApiError && error.status === 409 ?
          "conflict" : "unavailable");
      }
      return false;
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      busyRef.current = false;
    }
  }, [endpoint]);

  const retry = useCallback(() => {
    if (status !== "unavailable" || revisionRef.current === null) {
      return;
    }
    setStatus("ready");
    setVersion(v => v + 1);
  }, [status]);

  // Conflict refresh explicitly replaces the local draft. Never do this
  // automatically while unsent edits may still be present.
  const discardAndReload = useCallback(() => {
    if (status !== "conflict" && status !== "unavailable") return;
    dirtyRef.current = false;
    setStatus("loading");
    void refresh(true);
  }, [refresh, status]);

  return {
    draft, setText, readText, status, synced,
    clearBeforeSubmit, retry, discardAndReload,
  };
}
