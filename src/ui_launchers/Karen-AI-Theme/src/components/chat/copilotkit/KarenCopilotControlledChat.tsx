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
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const setDraftText = useCallback((text: string) => {
    if (text.length > MAX_INPUT_CHARS) {
      setError("Draft exceeds the supported message length.");
      return;
    }
    draftRef.current = text;
    setDraft(text);
  }, []);
  const draftPort: KarenVoiceDraftPort = {
    readText: () => draftRef.current,
    writeText: setDraftText,
  };
  useEffect(() => {
    // Drafts are intentionally not inherited by a different conversation.
    // A future durable draft owner must use authenticated user/tenant scope.
    draftRef.current = "";
    setDraft("");
    setError(null);
  }, [conversationId]);
  // A second click before SDK state flips to running must not start a
  // concurrent run or produce duplicate user-message writes.
  const submitPending = useRef(false);

  const onSubmitMessage = useCallback((value: string) => {
    const text = typeof value === "string" ? value.trim() : "";
    if (!isReady || submitPending.current || agent.isRunning ||
        !text || text.length > MAX_INPUT_CHARS ||
        agent.threadId !== conversationId) {
      setError("Unable to send this message in the verified conversation.");
      return;
    }
    submitPending.current = true;
    setError(null);
    setDraftText("");
    // This is an explicit user gesture. No automatic initial greeting/run.
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    });
    void Promise.resolve().then(() => copilotkit.runAgent({ agent }))
      .catch(() => {
        // Do not substitute a canned model answer or pretend persistence.
        // Preserve the unsent text for retry unless the user started a new draft.
        if (!draftRef.current) setDraftText(text);
        setError("Karen could not complete the request. Check the conversation history.");
      }).finally(() => {
        submitPending.current = false;
      });
  }, [agent, conversationId, copilotkit, isReady, setDraftText]);

  const onStop = useCallback(() => {
    if (!agent.isRunning) return;
    // SDK stop is a transport operation. Final durable cancellation and
    // its receipt must still be proven by the backend owned-run contract.
    void copilotkit.stopAgent({ agent });
  }, [agent, copilotkit]);

  if (!isReady) {
    return <p role="status" className="text-sm text-muted-foreground">Connecting conversation...</p>;
  }

  return (
    <div data-testid="karen-copilot-controlled-chat"
      className="flex min-h-0 min-w-0 flex-1 flex-col">
      {error && <p role="alert" className="border-b border-destructive/40 px-3 py-2 text-sm text-destructive">{error}</p>}
      <CopilotChatView
        messages={agent.messages}
        isRunning={agent.isRunning}
        autoScroll
        messageView={{ assistantMessage: KarenCopilotAssistantSlot }}
        input={{ value: draft, onChange: setDraftText, onSubmitMessage, onStop }}
      />
      <div data-testid="karen-copilot-voice-controls"
        className="flex shrink-0 items-center gap-2 border-t border-border/50 px-3 py-1">
        <KarenLocalDictationCapture port={draftPort} />
        <KarenBrowserDictationCapture port={draftPort} />
      </div>
    </div>
  );
}
