"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "@/lib/api";
import {
  KarenVerifiedHistoryProvider,
  parseKarenVerifiedHistory,
  type VerifiedHistoryParts,
} from "./KarenCopilotVerifiedHistory";


/**
 * This is an interaction adapter, not an alternate conversation store.
 * The canonical conversation repository owns user/tenant scope, order,
 * message contents, and durable writes.
 */
type KarenOwnedThreadResponse = {
  threadId: string;
  messages: KarenOwnedHistoryMessage[];
  // Backend-verified CUSTOM events exist, but this v2 manual hydrator only
  // supports text. Never silently discard presentation/receipt provenance.
  replayEvents?: unknown;
};

// The history gate owns the sole SDK agent registration for this conversation.
// Children consume the same instance; a second useAgent call with the same ID
// causes CopilotKitCore.registerProxiedAgent to reject the duplicate.
type ScopedAgentRegistration = ReturnType<typeof useAgent>;
const ScopedAgentContext = createContext<ScopedAgentRegistration | null>(null);

export function useKarenScopedAgent(): ScopedAgentRegistration {
  const registration = useContext(ScopedAgentContext);
  if (!registration) {
    throw new Error("CopilotKit conversation agent is unavailable outside its verified history gate");
  }
  return registration;
}

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
  if (messages.length > 500) {
    throw new Error("Canonical conversation history exceeds the text limit");
  }
  const ids = new Set<string>();
  return messages.map((message) => {
    if (!message || (message.role !== "user" && message.role !== "assistant") ||
        typeof message.id !== "string" || !message.id.trim() ||
        message.id.length > 200 || ids.has(message.id) ||
        typeof message.content !== "string" || message.content.length > 65536) {
      throw new Error("Canonical conversation history contains an invalid message");
    }
    ids.add(message.id);
    return {
      id: message.id,
      role: message.role,
      content: message.content,
    };
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
  const registration = useAgent({
    agentId: karenScopedAgentId(conversationId),
    runtimeAgentId: "default",
    threadId: conversationId,
  });
  const { agent, isReady } = registration;
  const [loaded, setLoaded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [verifiedParts, setVerifiedParts] = useState<VerifiedHistoryParts>(new Map());

  useEffect(() => {
    if (!isReady) return;
    let cancelled = false;
    setLoaded(null);
    setError(null);
    setVerifiedParts(new Map());

    // Run events merely trigger another authenticated read; they do not
    // authorize a client CUSTOM event as a saved execution receipt.
    let unsubscribe: (() => void) | undefined;
    let restoring = false;
    // A run can finalize while its prior canonical read is still in flight.
    // Coalesce repeated notifications into one additional authorized read.
    // Never display the earlier snapshot if a newer notification is queued.
    let restoreQueued = false;
    const restore = async (): Promise<boolean> => {
      if (cancelled) return false;
      if (restoring) {
        restoreQueued = true;
        return false;
      }
      restoring = true;
      let restored = false;
      try {
        do {
          restoreQueued = false;
          try {
            // Authorization-sensitive read. Never reuse process-local UI
            // bootstrap cache across account or tenant transitions.
            const snapshot = await apiClient.get<KarenOwnedThreadResponse>(
              "/api/copilotkit/threads/" + conversationId + "/messages",
            );
            if (cancelled) return false;
            if (snapshot.threadId !== conversationId || !Array.isArray(snapshot.messages)) {
              throw new Error("Conversation history identity mismatch");
            }
            // Validate the complete backend-verified rich replay before
            // installing it. A newer event invalidates this read's freshness.
            const messages = toCopilotTextMessages(snapshot.messages);
            const parts = parseKarenVerifiedHistory(
              snapshot.replayEvents ?? [], messages,
            );
            if (restoreQueued) continue;
            agent.setMessages(messages);
            setVerifiedParts(parts);
            setError(null);
            setLoaded(conversationId);
            restored = true;
          } catch (error: unknown) {
            if (!cancelled && !restoreQueued) {
              const status = error && typeof error === "object" && "status" in error
                ? (error as { status?: unknown }).status : undefined;
              setError(status === 409
                ? "This conversation contains content that Karen cannot faithfully restore in this chat yet. No partial conversation was opened. Retry after the required presentation support is available."
                : "Karen could not verify or restore this conversation.");
              restored = false;
            }
          }
        } while (restoreQueued && !cancelled);
        return restored && !cancelled;
      } finally {
        restoring = false;
      }
    };

    // Subscribe only to the real, ready agent and only after installing
    // verified history. SDK finalization is a signal to reread Karen's
    // committed transcript, never permission to invent a terminal event.
    const start = async () => {
      const restored = await restore();
      if (!restored || cancelled || typeof agent.subscribe !== "function") return;
      const subscription = agent.subscribe({
        onRunFinalized: () => {
          if (!cancelled) void restore();
        },
        onRunFailed: () => {
          if (!cancelled) void restore();
        },
      });
      unsubscribe = subscription.unsubscribe;
    };
    void start();

    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [agent, conversationId, isReady, retryAttempt]);

  if (!isReady || (loaded !== conversationId && !error)) {
    return <p role="status" className="text-sm text-muted-foreground">Restoring conversation...</p>;
  }
  if (error) {
    return (
      <div className="flex flex-col items-start gap-2 p-3">
        <p role="alert" className="text-sm text-destructive">{error}</p>
        <button type="button" className="rounded-md border border-input px-3 py-2 text-sm"
          onClick={() => setRetryAttempt(attempt => attempt + 1)}>
          Retry verified conversation
        </button>
      </div>
    );
  }
  return (
    <ScopedAgentContext.Provider value={registration}>
      <KarenVerifiedHistoryProvider parts={verifiedParts}>
        {children}
      </KarenVerifiedHistoryProvider>
    </ScopedAgentContext.Provider>
  );
}
