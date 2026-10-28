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
import { CopilotChatView, useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useRef, useState } from "react";
import { KarenLocalDictationCapture } from "../assistant-ui/KarenLocalDictation";
import { KarenBrowserDictationCapture } from "../assistant-ui/KarenBrowserDictation";
import type { KarenVoiceDraftPort } from "../KarenVoiceDraftPort";

import { karenScopedAgentId } from "./KarenCopilotHistoryGate";
import { KarenCopilotAssistantSlot } from "./KarenCopilotVerifiedHistory";
import { useKarenPersistedDraft } from "./useKarenPersistedDraft";

const MAX_INPUT_CHARS = 65536;

export function KarenCopilotControlledChat({
  conversationId,
}: {
  conversationId: string;
}) {
  const { agent, isReady } = useAgent({
    agentId: karenScopedAgentId(conversationId),
    runtimeAgentId: "default",
    threadId: conversationId,
  });
  const { copilotkit } = useCopilotKit();
  const [error, setError] = useState<string | null>(null);
  // Copyable only in this authenticated component, not an additional draft store.
  const [failedSubmission, setFailedSubmission] = useState<string | null>(null);
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
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, [conversationId]);

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
      }
    })();
  }, [
    agent, conversationId, copilotkit, isReady, clearBeforeSubmit,
    draftStatus, draftSynced, readDraftText, setDraftText, failedSubmission,
  ]);

  const onStop = useCallback(() => {
    if (!agent.isRunning) return;
    // SDK stop is a transport operation. Final durable cancellation and
    // its receipt must still be proven by the backend owned-run contract.
    void copilotkit.stopAgent({ agent });
  }, [agent, copilotkit]);

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
      {failedSubmission !== null && (
        <div data-testid="karen-copilot-failed-submission"
          className="flex flex-col gap-2 border-b border-destructive/40 px-3 py-2">
          <p role="status" className="text-sm text-muted-foreground">
            The earlier message was not queued. Copy or restore it before continuing.
          </p>
          <textarea aria-label="Unsent failed message" readOnly value={failedSubmission}
            className="min-h-16 w-full rounded-lg border border-input p-2 text-sm" />
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={Boolean(draft)}
              onClick={() => {
                if (readDraftText()) return;
                setDraftText(failedSubmission);
                setFailedSubmission(null);
              }}>
              Restore to empty composer
            </button>
            <button type="button" onClick={() => setFailedSubmission(null)}>
              Dismiss failed message
            </button>
          </div>
        </div>
      )}
      {!draftSynced && <p role="status" className="px-3 text-xs text-muted-foreground">
        Saving draft to your conversation…
      </p>}
      <CopilotChatView
        messages={agent.messages}
        isRunning={agent.isRunning}
        autoScroll
        messageView={{ assistantMessage: KarenCopilotAssistantSlot }}
        input={{ value: draft, onChange: onDraftChange, onSubmitMessage, onStop }}
      />
      <div data-testid="karen-copilot-voice-controls"
        className="flex shrink-0 items-center gap-2 border-t border-border/50 px-3 py-1">
        <KarenLocalDictationCapture port={draftPort} />
        <KarenBrowserDictationCapture port={draftPort} />
      </div>
    </div>
  );
}
