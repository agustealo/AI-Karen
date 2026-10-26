"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "@/lib/api";


/**
 * This is an interaction adapter, not an alternate conversation store.
 * The canonical conversation repository owns user/tenant scope, order,
 * message contents, and durable writes.
 */
type KarenOwnedThreadResponse = {
  threadId: string;
  messages: KarenOwnedHistoryMessage[];
};

/** One private local UI agent per owned conversation, all routing to Karen default runtime. */
export function karenScopedAgentId(conversationId: string): string {
  return "karen-" + conversationId;
}

export type KarenOwnedHistoryMessage = {
  id: string;
  role: string;
  content: string;
};

export type KarenCopilotTextMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export function toCopilotTextMessages(
  messages: KarenOwnedHistoryMessage[],
): KarenCopilotTextMessage[] {
  if (!Array.isArray(messages)) {
    throw new Error("Canonical conversation history is unavailable");
  }
  return messages.flatMap((message) => {
    if (message.role !== "user" && message.role !== "assistant") return [];
    if (typeof message.id !== "string" || !message.id.trim() ||
        typeof message.content !== "string") {
      throw new Error("Canonical conversation history contains an invalid message");
    }
    return [{
      id: message.id,
      role: message.role,
      content: message.content,
    }];
  });
}

/**
 * Hold the v2 chat mount until Karen confirms the selected conversation
 * actually belongs to the signed-in user. Never replace failed history
 * retrieval with an empty thread or SDK-local fallback.
 *
 * The SDK's default connect/history operation is not enabled in Karen yet.
 * This is the supported v2 manual-hydration seam for the eventual cutover;
 * replay and rich-presentation parity are separate acceptance gates.
 */
export function KarenCopilotHistoryGate({
  conversationId,
  children,
}: {
  conversationId: string;
  children: ReactNode;
}) {
  const { agent, isReady } = useAgent({
    agentId: karenScopedAgentId(conversationId),
    runtimeAgentId: "default",
    threadId: conversationId,
  });
  const [loaded, setLoaded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isReady) return;
    let cancelled = false;
    setLoaded(null);
    setError(null);

    void (async () => {
      try {
        // Authorization-sensitive read. Never reuse the process-local UI
        // bootstrap cache across account or tenant transitions.
        const snapshot = await apiClient.get<KarenOwnedThreadResponse>(
          "/api/copilotkit/threads/" + conversationId + "/messages",
        );
        if (cancelled) return;
        if (snapshot.threadId !== conversationId || !Array.isArray(snapshot.messages)) {
          throw new Error("Conversation history identity mismatch");
        }
        const messages = toCopilotTextMessages(snapshot.messages);
        // A thread switch must never retain another conversation's agent state.
        agent.setMessages(messages);
        setLoaded(conversationId);
      } catch (error: unknown) {
        if (!cancelled) {
          // A verified conversation can still require an unsupported rich
          // renderer. Explain the limitation rather than presenting partial
          // history as successfully restored.
          const status = error && typeof error === "object" && "status" in error
            ? (error as { status?: unknown }).status : undefined;
          setError(status === 409
            ? "This conversation contains interactive or structured content that CopilotKit cannot restore yet. Use the existing conversation view."
            : "Karen could not verify or restore this conversation.");
        }
      }
    })();

    return () => { cancelled = true; };
  }, [agent, conversationId, isReady]);

  if (!isReady || (loaded !== conversationId && !error)) {
    return <p role="status" className="text-sm text-muted-foreground">Restoring conversation...</p>;
  }
  if (error) {
    return <p role="alert" className="text-sm text-destructive">{error}</p>;
  }
  return <>{children}</>;
}
