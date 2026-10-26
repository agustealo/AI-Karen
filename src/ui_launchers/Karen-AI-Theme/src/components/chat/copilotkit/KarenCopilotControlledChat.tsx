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
import { useCallback, useState } from "react";

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

  const onSubmitMessage = useCallback((value: string) => {
    const text = typeof value === "string" ? value.trim() : "";
    if (!isReady || agent.isRunning || !text || text.length > MAX_INPUT_CHARS ||
        agent.threadId !== conversationId) {
      setError("Unable to send this message in the verified conversation.");
      return;
    }
    setError(null);
    // This is an explicit user gesture. No automatic initial greeting/run.
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    });
    void copilotkit.runAgent({ agent }).catch(() => {
      // Do not substitute a canned model answer or pretend persistence.
      setError("Karen could not complete the request. Check the conversation history.");
    });
  }, [agent, conversationId, copilotkit, isReady]);

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
        input={{ onSubmitMessage, onStop }}
      />
    </div>
  );
}
