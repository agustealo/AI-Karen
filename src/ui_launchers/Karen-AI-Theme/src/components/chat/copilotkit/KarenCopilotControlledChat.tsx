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
import type { ReactNode } from "react";
import { KarenCopilotVoiceDock } from "./KarenCopilotVoiceDock";
import { KarenComposerFileExplorer } from "../KarenComposerFileExplorer";
import { KarenComposerAgentDiscovery } from "../KarenComposerAgentDiscovery";
import type { KarenVoiceDraftPort } from "../KarenVoiceDraftPort";
import { apiClient } from "@/lib/api";
import { getCopilotRunFailureMessage, isCopilotRunAdmissionConflict, isCopilotRunFinalityUnverified } from "../const/getDegradedResponseMessage";

import { useKarenScopedAgent } from "./KarenCopilotHistoryGate";
import {
  KarenCopilotAssistantSlot,
  KarenCopilotUserSlot,
} from "./KarenCopilotVerifiedHistory";
import { useKarenPersistedDraft, MAX_DRAFT_ATTACHMENTS, type DraftAttachment } from "./useKarenPersistedDraft";
import { FileText, X } from "lucide-react";

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
  return typeof info.status === "string" &&
    ["running", "cancelling", "cancelled", "completed",
    "failed", "orphaned", "interrupted"].includes(info.status) &&
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
  personaControls,
  onOpenAgents,
  fileExplorerPluginId,
}: {
  conversationId: string;
  onBusyChange?: (busy: boolean) => void;
  personaControls?: ReactNode;
  onOpenAgents?: () => void;
  fileExplorerPluginId?: string;
}) {
  const { agent, isReady, refreshVerifiedHistory, recoveryRun, revisionBoundSubmission } = useKarenScopedAgent();
  const { copilotkit } = useCopilotKit();
  const [error, setError] = useState<string | null>(null);
  const [draftRecoveryFeedback, setDraftRecoveryFeedback] = useState<string | null>(null);
  const [stopStatus, setStopStatus] = useState<string | null>(null);
  const [checkableRunId, setCheckableRunId] = useState<string | null>(null);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const lastStopRunId = useRef<string | null>(null);
  const checkingStatusRef = useRef(false);
  const activeRunId = useRef<string | null>(null);
  // Presentation-only hold: no inference or draft clearance while the
  // canonical run outcome is unresolved. This is not a backend run grant.
  type FinalityHold = {
    conversationId: string; runId: string | null; submissionId: string | null;
  };
  const finalityHoldRef = useRef<FinalityHold | null>(null);
  const [finalityHold, setFinalityHold] = useState<FinalityHold | null>(null);
  const [finalityFeedback, setFinalityFeedback] = useState<string | null>(null);
  const [checkingFinality, setCheckingFinality] = useState(false);
  const checkingFinalityRef = useRef(false);
  const observedRunId = useRef<string | null>(null);
  // Correlation only, scoped to this explicit governed SDK invocation.
  const submittedIdentity = useRef<{ conversationId: string; submissionId: string } | null>(null);
  const holdUnverifiedRun = useCallback((failure: unknown, runId: string | null) => {
    const admissionConflict = isCopilotRunAdmissionConflict(failure);
    if (!admissionConflict && !isCopilotRunFinalityUnverified(failure)) return false;
    const previous = finalityHoldRef.current;
    const submitted = submittedIdentity.current;
    const submissionId = admissionConflict && submitted?.conversationId === conversationId
      ? submitted.submissionId : null;
    if (previous?.conversationId !== conversationId ||
        (admissionConflict && (previous.runId !== null ||
          (previous.submissionId === null && submissionId !== null)))) {
      // The rejected transport ID may belong to a different attempt. Only
      // correlate against the original governed submission, never guess a run.
      const hold = {
        conversationId, runId: admissionConflict ? null : runId, submissionId,
      };
      finalityHoldRef.current = hold;
      setFinalityHold(hold);
      setFinalityFeedback(null);
    }
    setError(getCopilotRunFailureMessage(failure));
    return true;
  }, [conversationId]);
  // A run may finalize while its exact-stop HTTP request is in flight.
  // Increment only when identity changes, not when the SDK stream closes.
  const runGeneration = useRef(0);
  const pendingStopId = useRef<string | null>(null);
  // Copyable only in this authenticated component, not an additional draft store.
  const [failedSubmission, setFailedSubmission] = useState<string | null>(null);
  const [copyFeedback, setCopyFeedback] = useState<string | null>(null);
  const {
    draft, setText: setDraftText, readText: readDraftText,
    attachments, updateAttachments,
    status: draftStatus, synced: draftSynced, failureStatus: draftFailureStatus, prepareSubmission,
    prepareRevisionSubmission, refreshSubmittedDraft,
    retry, discardAndReload,
  } = useKarenPersistedDraft(conversationId);
  const rejectedAttachmentClear = useRef<object | null>(null);
  const onDraftChange = useCallback((value: string) => {
    if (typeof value !== "string" || value.length > MAX_INPUT_CHARS ||
        new TextEncoder().encode(value).length > 262144) {
      setError("Draft exceeds the supported message length.");
      return;
    }
    // CopilotKit may echo the existing controlled value after send or stream
    // teardown. Only a real edit may dismiss a visible persistence/run error.
    if (value === readDraftText()) return;
    // An optimistic empty clear dispatched by CopilotKit's input handler during
    // message send must not clobber the authoritative draft or mark it dirty.
    if ((submitPending.current || rejectedAttachmentClear.current) && value === "") return;
    if (!finalityHoldRef.current) setError(null);
    setDraftText(value);
  }, [readDraftText, setDraftText]);
  const draftPort: KarenVoiceDraftPort = {
    readText: readDraftText,
    writeText: onDraftChange,
  };
  // A second click before SDK state flips to running must not start a
  // concurrent run or produce duplicate user-message writes.
  const submitPending = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const attachmentEditsDisabled = draftStatus !== "ready" || agent.isRunning ||
    submitting || failedSubmission !== null;
  const attachFiles = useCallback((references: DraftAttachment[]) => {
    if (!isReady || attachmentEditsDisabled || submitPending.current ||
        agent.threadId !== conversationId) return;
    const next = [...attachments];
    for (const reference of references) {
      const previous = next.find(item => item.source_id === reference.source_id);
      if (previous) {
        if (previous.revision !== reference.revision) {
          setError("A selected file has changed. Remove its older reference before attaching it again.");
          return;
        }
        continue;
      }
      next.push(reference);
    }
    if (next.length > MAX_DRAFT_ATTACHMENTS) {
      setError(`A draft can contain up to ${MAX_DRAFT_ATTACHMENTS} file references. Remove a file before adding more.`);
      return;
    }
    setError(null);
    updateAttachments(next);
  }, [agent.threadId, attachmentEditsDisabled, attachments, conversationId, isReady, updateAttachments]);

  const removeAttachment = useCallback((sourceId: string) => {
    if (!isReady || attachmentEditsDisabled || submitPending.current ||
        agent.threadId !== conversationId) return;
    setError(null);
    updateAttachments(attachments.filter(item => item.source_id !== sourceId));
  }, [agent.threadId, attachmentEditsDisabled, attachments, conversationId, isReady, updateAttachments]);
  // Presentation only: an explicit SDK invocation may fail before AG-UI
  // supplies a valid run ID. This is never backend run identity/stop authority.
  const sdkInvocationPending = useRef(false);
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

  // Source plugins may prepare a user draft, but cannot submit a message or
  // authorize evidence. The canonical conversation draft hook owns CAS writes.
  useEffect(() => {
    const onExternalDraft = (event: Event) => {
      if (!(event instanceof CustomEvent) || !event.cancelable || event.defaultPrevented) return;
      const detail: unknown = event.detail;
      if (!detail || typeof detail !== "object" || Array.isArray(detail)) return;
      const request = detail as Record<string, unknown>;
      if (request.role !== "user" || request.autoSubmit !== false ||
          typeof request.content !== "string") return;
      const incoming = request.content.trim();
      if (!incoming || !isReady || draftStatus !== "ready" ||
          agent.isRunning || agent.threadId !== conversationId ||
          submitPending.current || failedSubmission !== null) return;
      const existing = readDraftText();
      const next = existing.trim() ? existing + "\n\n" + incoming : incoming;
      if (next.length > MAX_INPUT_CHARS || new TextEncoder().encode(next).length > 262144) {
        setError("Search handoff exceeds the supported draft length.");
        return;
      }
      onDraftChange(next);
      // This acknowledges only a locally prepared draft. Saving and model
      // execution remain independently confirmed by the canonical chat flow.
      event.preventDefault();
      window.dispatchEvent(new Event("karen:chat-draft-prepared"));
    };
    window.addEventListener("karen:inject-message", onExternalDraft);
    return () => window.removeEventListener("karen:inject-message", onExternalDraft);
  }, [agent.isRunning, agent.threadId, conversationId, draftStatus, failedSubmission,
    isReady, onDraftChange, readDraftText]);

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
        observedRunId.current = event.runId;
        lastStopRunId.current = null;
        setStopStatus(null);
        setCheckableRunId(null);
        if (!finalityHoldRef.current) setError(null);
      },
      onRunFinalized: () => { activeRunId.current = null; },
      onRunFailed: (failure: unknown) => {
        // Finalized may precede failed. Recover the observed ID only while
        // the explicit invocation or that exact stop remains in flight.
        const observed = observedRunId.current;
        const failedRunId = activeRunId.current ?? (
          observed !== null && (sdkInvocationPending.current ||
            pendingStopId.current === observed || lastStopRunId.current === observed)
            ? observed : null
        );
        const failedBeforeStart = failedRunId === null && sdkInvocationPending.current;
        activeRunId.current = null;
        // SDK may emit RUN_ERROR before RUN_STARTED, or resolve runAgent()
        // instead of rejecting on a terminal stream failure. Report only
        // while this consumer's explicit SDK invocation is in flight, or
        // for an attested run ID. Never synthesize a backend run identity.
        const unconfirmedStop = failedRunId !== null &&
          (pendingStopId.current === failedRunId ||
           lastStopRunId.current === failedRunId);
        if (mounted.current && (failedRunId !== null || failedBeforeStart)) {
          // A stop request never proves transcript finality. Suppress only
          // ordinary transport failures caused by a stop, not explicit
          // canonical uncertainty.
          if (!holdUnverifiedRun(failure, failedRunId) &&
              !unconfirmedStop && !finalityHoldRef.current) {
            setError(getCopilotRunFailureMessage(failure));
          }
        }
      },
    });
    return () => {
      runGeneration.current += 1;
      activeRunId.current = null;
      pendingStopId.current = null;
      lastStopRunId.current = null;
      observedRunId.current = null;
      sdkInvocationPending.current = false;
      submittedIdentity.current = null;
      subscription.unsubscribe();
    };
  }, [agent, conversationId, isReady, holdUnverifiedRun]);

  const onSubmitMessage = useCallback((value: string) => {
    const text = typeof value === "string" ? value.trim() : "";
    if (attachments.length > 0 || recoveryRun ||
        finalityHoldRef.current?.conversationId === conversationId) {
      // The SDK synchronously emits onChange("") after onSubmitMessage even
      // when admission is rejected. Fence only that turn, not later user edits.
      const rejected = {};
      rejectedAttachmentClear.current = rejected;
      queueMicrotask(() => {
        if (rejectedAttachmentClear.current === rejected) rejectedAttachmentClear.current = null;
      });
    }
    if (recoveryRun || finalityHoldRef.current?.conversationId === conversationId) {
      setError("The previous run is unverified. Check its status and saved history before sending another message.");
      return;
    }
    if (attachments.length > 0) {
      setError("Sending attached files is not supported yet. Remove the attachments before sending your message.");
      return;
    }
    if (failedSubmission !== null) {
      setError("Copy, restore or dismiss the failed unsent message before sending another.");
      return;
    }
    if (!isReady || draftStatus !== "ready" ||
        submitPending.current || agent.isRunning ||
        !text || text.length > MAX_INPUT_CHARS ||
        agent.threadId !== conversationId) {
      setError("Unable to send this message in the verified conversation.");
      return;
    }
    submitPending.current = true;
    setSubmitting(true);
    reportBusy(true);
    setError(null);
    // This is an explicit user gesture. Governed runs retain the original
    // verified draft revision until the backend atomically commits the turn.
    // Only legacy non-governed history uses the existing pre-run clear.
    void (async () => {
      try {
        const submissionId = revisionBoundSubmission
          ? await prepareRevisionSubmission(text)
          : await prepareSubmission(text) ? crypto.randomUUID() : null;
        if (!submissionId || !mounted.current || agent.threadId !== conversationId) {
          if (mounted.current) {
            setError(revisionBoundSubmission
              ? "The original draft revision could not be verified. No message was sent."
              : "The draft could not be safely saved and cleared. No message was sent.");
          }
          return;
        }
        try {
          agent.addMessage({
            id: submissionId,
            role: "user",
            content: text,
          });
        } catch {
          if (mounted.current) {
            if (revisionBoundSubmission && readDraftText().trim() === text) {
              // The original saved revision still exists; do not rewrite it.
            } else if (!readDraftText()) {
              setDraftText(text);
            } else {
              // Never clobber a newer edit while a durable handoff is in flight.
              setCopyFeedback(null);
              setFailedSubmission(text);
            }
            setError("Karen could not queue the message. Your unsent draft was retained.");
          }
          return;
        }
        // This flag is only for observing a terminal SDK error before
        // RUN_STARTED. It is not used for cancel, persistence, or tool policy.
        observedRunId.current = null;
        submittedIdentity.current = revisionBoundSubmission && RUN_ID.test(submissionId)
          ? { conversationId, submissionId } : null;
        sdkInvocationPending.current = true;
        try {
          await copilotkit.runAgent({ agent });
        } catch (failure: unknown) {
          if (mounted.current) {
            // addMessage already accepted this user turn. The SDK may have
            // transmitted or persisted it before the run failed, so putting
            // the same text back in the composer would invite an accidental
            // duplicate submission. Only pre-queue failures restore drafts.
            // Newer edits remain untouched; the user must inspect canonical
            // history before choosing whether to send again.
            if (!holdUnverifiedRun(failure, observedRunId.current) &&
                !finalityHoldRef.current) {
              setError(getCopilotRunFailureMessage(failure));
            }
          }
        } finally {
          sdkInvocationPending.current = false;
          submittedIdentity.current = null;
          if (revisionBoundSubmission && mounted.current && agent.threadId === conversationId) {
            // Neither SDK resolution nor RUN_ERROR is permission to clear a
            // draft. Read the authenticated server state, including any
            // retirement committed despite a lost transport receipt.
            await refreshSubmittedDraft();
          }
        }
      } finally {
        submitPending.current = false;
        if (mounted.current) {
          setSubmitting(false);
          reportBusy(Boolean(agent.isRunning));
        }
      }
    })();
  }, [
    agent, conversationId, copilotkit, isReady, prepareSubmission,
    draftStatus, readDraftText, setDraftText, failedSubmission, attachments.length,
    reportBusy, holdUnverifiedRun, recoveryRun, revisionBoundSubmission,
    prepareRevisionSubmission, refreshSubmittedDraft,
  ]);

  const checkUnverifiedFinality = useCallback(() => {
    const hold = finalityHoldRef.current;
    const identity = hold?.submissionId ?? hold?.runId;
    if (!hold || hold.conversationId !== conversationId ||
        !identity || !RUN_ID.test(identity) || checkingFinalityRef.current ||
        submitPending.current || agent.isRunning || agent.threadId !== conversationId) return;
    checkingFinalityRef.current = true;
    setCheckingFinality(true);
    setFinalityFeedback(null);
    void (async () => {
      try {
        const result: unknown = await apiClient.get<RunStatus>(
          "/api/copilotkit/agent/default/" + (hold.submissionId ? "submissions/" : "runs/") +
            conversationId + "/" + identity + "/status",
        );
        if (!mounted.current || finalityHoldRef.current !== hold) return;
        if (!validRunStatus(result)) throw new Error("Invalid run status");
        if (hold.submissionId) {
          const receipt = result as RunStatus & { runId?: unknown; submissionId?: unknown };
          if (receipt.submissionId !== hold.submissionId ||
              typeof receipt.runId !== "string" || !RUN_ID.test(receipt.runId)) {
            throw new Error("Invalid submission status");
          }
        }
        // Interrupted is an expired lease observation, not a durable
        // terminal receipt. Orphaned work may still need operator recovery.
        if (!["completed", "failed", "cancelled"].includes(result.status)) {
          setFinalityFeedback("No verified completion or confirmed failure is available. Sending remains blocked.");
          return;
        }
        if (!await refreshVerifiedHistory()) {
          if (mounted.current && finalityHoldRef.current === hold) {
            setFinalityFeedback("Run status was read, but saved history could not be verified. Sending remains blocked.");
          }
          return;
        }
        if (!mounted.current || finalityHoldRef.current !== hold ||
            agent.threadId !== conversationId) return;
        if (hold.submissionId) {
          // The original draft may have retired since the initial failed
          // transport. Only the existing CAS hook can reconcile that state.
          await refreshSubmittedDraft();
          if (!mounted.current || finalityHoldRef.current !== hold ||
              agent.threadId !== conversationId) return;
        }
        finalityHoldRef.current = null;
        setFinalityHold(null);
        setError(null);
        setFinalityFeedback("Run status and saved history were checked. Review the restored conversation before sending a new message.");
      } catch {
        if (mounted.current && finalityHoldRef.current === hold) {
          setFinalityFeedback("Run status or saved history is unavailable. Sending remains blocked.");
        }
      } finally {
        checkingFinalityRef.current = false;
        if (mounted.current) setCheckingFinality(false);
      }
    })();
  }, [agent, conversationId, refreshVerifiedHistory, refreshSubmittedDraft]);

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
  const recoveryPanel = draftStatus === "conflict" || draftStatus === "unavailable" ? (() => {
    const conflict = draftStatus === "conflict";
    const explanation = conflict
      ? "This draft or an attached file changed or became unavailable. Your local text and references have been retained."
      : draftFailureStatus === 401 || draftFailureStatus === 403
        ? "Your session must be verified before Karen can access saved drafts."
        : draftFailureStatus === 404
          ? "Karen could not find an authorized draft for this conversation."
          : "Karen could not confirm that your draft was saved. No message was sent.";
    return (
      <section data-testid="karen-copilot-unsynced-draft"
        aria-label="Draft recovery" className="shrink-0 space-y-2 border-b border-destructive/30 p-3">
        <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/5 p-3">
          <h3 className="text-sm font-semibold">{conflict ? "Draft conflict" : "Draft not saved"}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{explanation}</p>
          {draftFailureStatus === 503 && <p className="mt-1 text-xs text-muted-foreground">
            Draft service is temporarily unavailable. Your message is not confirmed saved.
          </p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!conflict && <button type="button" onClick={retry} className="min-h-11 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground">Reconnect and save</button>}
          <button type="button" disabled={!draft} onClick={() => {
            if (!navigator.clipboard?.writeText) {
              setDraftRecoveryFeedback("Clipboard unavailable. Select your unsent text in the composer to copy it.");
              return;
            }
            void navigator.clipboard.writeText(draft)
              .then(() => setDraftRecoveryFeedback("Unsent text copied."))
              .catch(() => setDraftRecoveryFeedback("Copy failed. Select your unsent text in the composer."));
          }} className="min-h-11 rounded-lg border border-input px-3 text-sm disabled:opacity-50">Copy unsent text</button>
          {draftRecoveryFeedback && <p role="status" className="text-xs text-muted-foreground">{draftRecoveryFeedback}</p>}
        </div>
        <details className="rounded-xl border border-border/60 p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {conflict ? "Resolve draft conflict" : "Other recovery options"}
          </summary>
          <p className="mt-2 text-xs text-muted-foreground">
            Reloading fetches the server draft and discards unsaved text and attachment changes. Copy your message first.
          </p>
          <button type="button" onClick={discardAndReload}
            className="mt-2 min-h-11 rounded-lg border border-input px-3 text-sm">
            Discard local changes and reload saved draft
          </button>
        </details>
      </section>
    );
  })() : null;

  return (
    <div data-testid="karen-copilot-controlled-chat"
      className="flex min-h-0 min-w-0 flex-1 flex-col">
      {recoveryPanel}
      {error && <p role="alert" className="border-b border-destructive/40 px-3 py-2 text-sm text-destructive">{error}</p>}
      {finalityHold?.conversationId === conversationId && (
        <section aria-label="Unverified run recovery" className="space-y-2 border-b border-border px-3 py-2">
          <p role="status" className="text-sm">Sending is blocked until the previous run and saved history are checked.</p>
          {finalityHold.runId || finalityHold.submissionId ? (
            <button type="button" disabled={checkingFinality || submitting || agent.isRunning}
              onClick={checkUnverifiedFinality} className="rounded-md border border-input px-3 py-2 text-sm">
              {checkingFinality ? "Checking…" : "Check run status and saved history"}
            </button>
          ) : <p className="text-xs text-muted-foreground">
            No verified run identity was received. Reopen the conversation to check saved history and recovery status. Contact support if the outcome remains unclear.
          </p>}
        </section>
      )}
      {finalityFeedback && <p role="status" className="px-3 py-2 text-sm">{finalityFeedback}</p>}
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
      <div data-testid="karen-copilot-sdk-chat"
        className="flex min-h-0 min-w-0 flex-1 flex-col">
        <CopilotChatView
          messages={agent.messages}
          isRunning={agent.isRunning}
          autoScroll
          messageView={{
            assistantMessage: KarenCopilotAssistantSlot,
            userMessage: KarenCopilotUserSlot,
          }}
          input={{ value: draft, onChange: onDraftChange, onSubmitMessage, onStop }}
        />
      </div>
      <div data-testid="karen-copilot-composer-accessories" aria-label="Composer preferences"
        className="shrink-0 min-w-0 border-t border-border/60 bg-background/95">
        {draftStatus === "ready" && !draftSynced && <p role="status" className="px-3 pt-1 text-xs text-muted-foreground">
          Draft changes pending save…
        </p>}
        {attachments.length > 0 && (
          <section aria-label="Draft attachments" className="space-y-2 px-3 pt-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium">{attachments.length} / {MAX_DRAFT_ATTACHMENTS} file references</p>
              <p role="status" className="text-xs text-muted-foreground">
                {draftStatus === "ready" && draftSynced ? "References saved" : "References not confirmed saved"}
              </p>
            </div>
            <ul className="flex flex-wrap gap-2">
              {attachments.map((reference) => (
                <li key={reference.source_id}
                  className="flex min-w-0 max-w-full items-center gap-2 rounded-lg border border-border px-2">
                  <FileText aria-hidden="true" className="h-4 w-4 shrink-0" />
                  <span title={reference.source_id} className="truncate font-mono text-xs">
                    File {reference.source_id.slice(0, 8)} · {reference.revision.slice(0, 8)}
                  </span>
                  <button type="button" disabled={attachmentEditsDisabled}
                    aria-label={`Remove file reference ${reference.source_id}`}
                    onClick={() => removeAttachment(reference.source_id)}
                    className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-md focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
                    <X aria-hidden="true" className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              File references are saved with the draft, not sent to a model. Remove them before sending.
            </p>
          </section>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 px-2 py-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {fileExplorerPluginId && <KarenComposerFileExplorer
              key={conversationId + ":" + fileExplorerPluginId}
              pluginId={fileExplorerPluginId}
              onAttach={attachFiles}
              existingAttachments={attachments}
              disabled={attachmentEditsDisabled} />}
            {onOpenAgents && <KarenComposerAgentDiscovery onOpenAgents={onOpenAgents}
              disabled={draftStatus !== "ready" || !draftSynced || agent.isRunning || failedSubmission !== null} />}
          </div>
          <div className="w-full sm:w-auto sm:min-w-0 sm:flex-1">
            <KarenCopilotVoiceDock port={draftPort}
              disabled={draftStatus !== "ready" || agent.isRunning || failedSubmission !== null}
              personaControls={personaControls} />
          </div>
        </div>
      </div>
    </div>
  );
}
