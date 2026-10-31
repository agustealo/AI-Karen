"use client";

/**
 * CopilotKit v2 headless controller over its own native chat view.
 *
 * The high-level CopilotChat runs an agent automatically on first mount.
 * A durable saved conversation must never trigger inference by opening it.
 * Here only an explicit composer submit calls the CopilotKit orchestrator.
 * Karen's authenticated runtime still owns policy, model selection and
 * persistence; there are no frontend tools or client-owned checkpoints.
 */
import { CopilotChatView, useCopilotKit } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useRef, useState } from "react";
import { KarenLocalDictationCapture } from "../KarenLocalDictationCapture";
import { KarenBrowserDictationCapture } from "../KarenBrowserDictationCapture";
import type { KarenVoiceDraftPort } from "../KarenVoiceDraftPort";
import { apiClient } from "@/lib/api";

import { useKarenScopedAgent } from "./KarenCopilotHistoryGate";
import { KarenCopilotAssistantSlot } from "./KarenCopilotVerifiedHistory";
import { useKarenPersistedDraft } from "./useKarenPersistedDraft";

const MAX_INPUT_CHARS = 65536;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;
type StopReceipt = {
  status: "cancelling" | "cancelled";
  cancel_requested: true;
  cancellation_confirmed: boolean;
};
type RunStatus = {
  status: "running" | "cancelling" | "cancelled" |
    "completed" | "failed" | "orphaned" | "interrupted";
  cancel_requested: boolean;
  cancellation_confirmed: boolean;
};
function validRunStatus(value: unknown): value is RunStatus {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const info = value as Record<string, unknown>;
  return ["running", "cancelling", "cancelled", "completed",
    "failed", "orphaned", "interrupted"].includes(String(info.status)) &&
    typeof info.cancel_requested === "boolean" &&
    typeof info.cancellation_confirmed === "boolean" &&
    (!info.cancellation_confirmed ||
      (info.status === "cancelled" && info.cancel_requested === true));
}

function validStopReceipt(value: unknown): value is StopReceipt {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  return receipt.cancel_requested === true &&
    ((receipt.status === "cancelling" && receipt.cancellation_confirmed === false) ||
     (receipt.status === "cancelled" && receipt.cancellation_confirmed === true));
}

export function KarenCopilotControlledChat({
  conversationId,
  onBusyChange,
}: {
  conversationId: string;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { agent, isReady } = useKarenScopedAgent();
  const { copilotkit } = useCopilotKit();
  const [error, setError] = useState<string | null>(null);
  const [stopStatus, setStopStatus] = useState<string | null>(null);
  const [checkableRunId, setCheckableRunId] = useState<string | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const lastStopRunId = useRef<string | null>(null);
  const checkingStatusRef = useRef(false);
  const activeRunId = useRef<string | null>(null);
  // A run may finalize while its exact-stop HTTP request is in flight.
  // Increment only when identity changes, not when the SDK stream closes.
  const runGeneration = useRef(0);
  const pendingStopId = useRef<string | null>(null);
  // Copyable only in this authenticated component, not an additional draft store.
  const [failedSubmission, setFailedSubmission] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const {
    draft, setText: setDraftText, readText: readDraftText,
    status: draftStatus, synced: draftSynced, clearBeforeSubmit,
    retry, discardAndReload,
  } = useKarenPersistedDraft(conversationId);
  const onDraftChange = useCallback((value: string) => {
    if (typeof value !== "string" || value.length > MAX_INPUT_CHARS ||
        new TextEncoder().encode(value).length > 262144) {
      setError("Draft exceeds the supported message length.");
      return;
    }
    setError(null);
    setDraftText(value);
  }, [setDraftText]);
  const draftPort: KarenVoiceDraftPort = {
    readText: readDraftText,
    writeText: onDraftChange,
  };
  // A second click before SDK state flips to running must not start a
  // concurrent run or produce duplicate user-message writes.
  const submitPending = useRef(false);
  const mounted = useRef(true);
  const reportBusy = useCallback((busy: boolean) => {
    onBusyChange?.(busy);
  }, [onBusyChange]);
  useEffect(() => {
    reportBusy(Boolean(agent.isRunning || submitPending.current));
  }, [agent.isRunning, reportBusy]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, [conversationId]);

  useEffect(() => {
    if (!isReady || typeof agent.subscribe !== "function") return;
    activeRunId.current = null;
    pendingStopId.current = null;
    const subscription = agent.subscribe({
      onRunStartedEvent: ({ event }) => {
        // Run identity is received from authenticated AG-UI lifecycle events,
        // never the composer, local state, or guessed SDK stop arguments.
        if (event.threadId !== conversationId || !RUN_ID.test(event.runId)) return;
        runGeneration.current += 1;
        activeRunId.current = event.runId;
        lastStopRunId.current = null;
        setStopStatus(null);
        setCheckableRunId(null);
      },
      onRunFinalized: () => { activeRunId.current = null; },
      onRunFailed: () => { activeRunId.current = null; },
    });
    return () => {
      runGeneration.current += 1;
      activeRunId.current = null;
      pendingStopId.current = null;
      lastStopRunId.current = null;
      subscription.unsubscribe();
    };
  }, [agent, conversationId, isReady]);

  const onSubmitMessage = useCallback((value: string) => {
    const text = typeof value === "string" ? value.trim() : "";
    if (failedSubmission !== null) {
      setError("Copy, restore or dismiss the failed unsent message before sending another.");
      return;
    }
    if (!isReady || draftStatus !== "ready" ||
        !draftSynced || submitPending.current || agent.isRunning ||
        !text || text.length > MAX_INPUT_CHARS ||
        agent.threadId !== conversationId) {
      setError("Unable to send this message in the verified conversation.");
      return;
    }
    submitPending.current = true;
    reportBusy(true);
    setError(null);
    // This is an explicit user gesture. Durable draft clearance is a
    // separate canonical CAS write and must succeed before inference starts.
    void (async () => {
      try {
        if (!await clearBeforeSubmit(text) || !mounted.current ||
            agent.threadId !== conversationId) {
          if (mounted.current) {
            setError("Draft clearance was not confirmed. No message was sent.");
          }
          return;
        }
        try {
          agent.addMessage({
            id: crypto.randomUUID(),
            role: "user",
            content: text,
          });
        } catch {
          if (mounted.current) {
            if (!readDraftText()) {
              setDraftText(text);
            } else {
              // Never clobber a newer edit while a durable clear is in flight.
              setCopyFeedback(null);
              setFailedSubmission(text);
            }
            setError("Karen could not queue the message. Your unsent draft was retained.");
          }
          return;
        }
        try {
          await copilotkit.runAgent({ agent });
        } catch {
          if (mounted.current) {
            if (!readDraftText()) setDraftText(text);
            setError("Karen could not complete the request. Check the conversation history.");
          }
        }
      } finally {
        submitPending.current = false;
        if (mounted.current) reportBusy(Boolean(agent.isRunning));
      }
    })();
  }, [
    agent, conversationId, copilotkit, isReady, clearBeforeSubmit,
    draftStatus, draftSynced, readDraftText, setDraftText, failedSubmission,
    reportBusy,
  ]);

  const onStop = useCallback(() => {
    if (!isReady || !agent.isRunning) return;
    const runId = activeRunId.current;
    if (!runId || !RUN_ID.test(runId) || agent.threadId !== conversationId) {
      setError("Karen has not verified an exact active run for cancellation. Check run status.");
      return;
    }
    if (pendingStopId.current === runId) return;
    pendingStopId.current = runId;
    const generation = runGeneration.current;
    setError(null);
    void (async () => {
      try {
        // Backend run ownership and cancellation authority live behind this
        // already-existing authenticated exact-run gateway. An SDK abort alone
        // can stop browser streaming without stopping the durable worker.
        const receipt: unknown = await apiClient.post<StopReceipt>(
          "/api/copilotkit/agent/default/stop/" + conversationId, { runId },
        );
        if (!validStopReceipt(receipt)) throw new Error("Invalid stop receipt");
        // RUN_FINISHED / RUN_ERROR may close transport before the stop
        // receipt arrives. Keep the canonical receipt if the run generation
        // is unchanged, but never apply it to a newer run.
        if (!mounted.current || runGeneration.current !== generation) return;
        lastStopRunId.current = runId;
        setCheckableRunId(receipt.cancellation_confirmed ? null : runId);
        setStopStatus(receipt.cancellation_confirmed
          ? "Karen confirmed this run was cancelled."
          : "Cancellation requested. Backend confirmation is still pending.");
        if (activeRunId.current === runId && agent.isRunning) try {
          await copilotkit.stopAgent({ agent });
        } catch {
          if (mounted.current && runGeneration.current === generation) {
            setError("Karen accepted the cancellation request, but local streaming could not stop. Check run status.");
          }
        }
      } catch {
        if (mounted.current && runGeneration.current === generation) {
          setError("Karen could not verify the cancellation request. Check run status before retrying.");
        }
      } finally {
        if (pendingStopId.current === runId) pendingStopId.current = null;
      }
    })();
  }, [agent, conversationId, copilotkit, isReady]);


  const checkCancellationStatus = useCallback(() => {
    const runId = checkableRunId;
    if (!runId || !RUN_ID.test(runId) || lastStopRunId.current !== runId ||
        checkingStatusRef.current || agent.threadId !== conversationId) return;
    checkingStatusRef.current = true;
    setCheckingStatus(true);
    setError(null);
    void (async () => {
      try {
        const result: unknown = await apiClient.get<RunStatus>(
          "/api/copilotkit/agent/default/runs/" + conversationId +
            "/" + runId + "/status",
        );
        if (!validRunStatus(result) ||
            (["running", "cancelling"].includes(result.status) &&
              !result.cancel_requested)) {
          // A prior 202 is not permission to label the run "cancelling"
          // when the canonical ledger has no matching stop marker.
          throw new Error("Inconsistent durable stop status");
        }
        if (!mounted.current || lastStopRunId.current !== runId) return;
        if (result.cancellation_confirmed) {
          setStopStatus("Karen confirmed this run was cancelled.");
          setCheckableRunId(null);
        } else if (["completed", "failed", "orphaned", "interrupted", "cancelled"]
            .includes(result.status)) {
          setStopStatus("Run ended without a confirmed stop. Review verified conversation history.");
          setCheckableRunId(null);
        } else {
          setStopStatus("Cancellation requested. Backend confirmation is still pending.");
        }
      } catch {
        if (mounted.current && lastStopRunId.current === runId) {
          // Do not leave a stale "pending cancellation" assertion on screen
          // after the supposedly authoritative status read contradicts it.
          setStopStatus("Cancellation state could not be verified. No confirmed stop is available.");
          setError("Karen could not verify the run's final status. Try checking again.");
        }
      } finally {
        checkingStatusRef.current = false;
        if (mounted.current) setCheckingStatus(false);
      }
    })();
  }, [agent, checkableRunId, conversationId]);

  const copyFailedMessage = useCallback(async () => {
    if (failedSubmission === null) return;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(failedSubmission);
      if (mounted.current) setCopyFeedback("Failed message copied.");
    } catch {
      if (mounted.current) {
        setCopyFeedback("Clipboard unavailable. Select the unsent message above to copy it.");
      }
    }
  }, [failedSubmission]);

  if (!isReady || draftStatus === "loading") {
    return <p role="status" className="text-sm text-muted-foreground">Loading verified conversation and saved draft...</p>;
  }
  if (draftStatus === "conflict" || draftStatus === "unavailable") {
    return (
      <div data-testid="karen-copilot-unsynced-draft"
        className="flex min-w-0 flex-1 flex-col gap-2 p-3">
        <p role="alert" className="text-sm text-destructive">
          {draftStatus === "conflict"
            ? "Draft changed in another window. Your local text was not overwritten."
            : "Draft storage is unavailable. Your current text is not confirmed saved."}
        </p>
        <textarea aria-label="Unsynced draft, copy before reload" readOnly
          value={draft} className="min-h-24 w-full rounded-lg border border-input p-2 text-sm" />
        <div className="flex gap-2">
          {draftStatus === "unavailable" &&
            <button type="button" onClick={retry}>Retry draft synchronization</button>}
          <button type="button" onClick={discardAndReload}>
            Reload saved draft (discard local changes)
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="karen-copilot-controlled-chat"
      className="flex min-h-0 min-w-0 flex-1 flex-col">
      {error && <p role="alert" className="border-b border-destructive/40 px-3 py-2 text-sm text-destructive">{error}</p>}
      {stopStatus && <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-3 py-2">
        <p role="status" data-testid="karen-copilot-stop-status"
          className="text-sm text-muted-foreground">{stopStatus}</p>
        {checkableRunId && <button type="button" disabled={checkingStatus}
          onClick={checkCancellationStatus}
          className="rounded-md border border-input px-2 py-1 text-xs">
          {checkingStatus ? "Checking run status…" : "Check cancellation status"}
        </button>}
      </div>}
      {failedSubmission !== null && (
        <div data-testid="karen-copilot-failed-submission"
          className="flex flex-col gap-2 border-b border-destructive/40 px-3 py-2">
          <p role="status" className="text-sm text-muted-foreground">
            The earlier message was not queued. Copy or restore it before continuing.
          </p>
          <textarea aria-label="Unsent failed message" readOnly value={failedSubmission}
            className="min-h-16 w-full rounded-lg border border-input p-2 text-sm" />
          {copyFeedback && <p data-testid="karen-copilot-copy-feedback"
            role="status" className="text-xs text-muted-foreground">{copyFeedback}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => void copyFailedMessage()}>
              Copy failed message
            </button>
            <button type="button" disabled={Boolean(draft)}
              onClick={() => {
                if (readDraftText()) return;
                setDraftText(failedSubmission);
                setFailedSubmission(null);
                setCopyFeedback(null);
              }}>
              Restore to empty composer
            </button>
            <button type="button" onClick={() => {
              setFailedSubmission(null);
              setCopyFeedback(null);
            }}>
              Dismiss failed message
            </button>
          </div>
        </div>
      )}
      {!draftSynced && <p role="status" className="px-3 text-xs text-muted-foreground">
        Saving draft to your conversation…
      </p>}
      <div data-testid="karen-copilot-sdk-chat"
        className="flex min-h-0 min-w-0 flex-1 flex-col">
        <CopilotChatView
          messages={agent.messages}
          isRunning={agent.isRunning}
          autoScroll
          messageView={{ assistantMessage: KarenCopilotAssistantSlot }}
          input={{ value: draft, onChange: onDraftChange, onSubmitMessage, onStop }}
        />
      </div>
      <div data-testid="karen-copilot-voice-controls"
        className="flex shrink-0 items-center gap-2 border-t border-border/50 px-3 py-1">
        <KarenLocalDictationCapture port={draftPort} />
        <KarenBrowserDictationCapture port={draftPort} />
      </div>
    </div>
  );
}
