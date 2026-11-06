"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { createContext, useContext, useEffect, useRef, useState } from "react";
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
  replayEvents?: unknown;
};

type KarenRecoveredTranscript = {
  conversationId: string;
  messages: KarenCopilotTextMessage[];
  omittedEntries: number;
  pageOffset: number;
  hasMore: boolean;
  nextOffset: number | null;
  revision: string | null;
};

// The canonical history endpoint bounds the original response to 2 MiB.
// Formatting adds labels and separators. Never silently truncate evidence.
const MAX_RECOVERED_CLIPBOARD_BYTES = 2 * 1024 * 1024;

export function formatRecoveredConversationText(
  messages: readonly KarenCopilotTextMessage[],
): string {
  return messages.map(message =>
    (message.role === "user" ? "You" : "Karen") + ":\n" + message.content,
  ).join("\n\n");
}

type KarenOwnedTranscriptResponse = {
  threadId: string;
  messages: KarenOwnedHistoryMessage[];
  read_only: true;
  text_only: true;
  omitted_entries: number;
  page_offset?: number;
  has_more?: boolean;
  next_offset?: number | null;
  snapshot_revision?: string;
};

function verifiedTranscriptPage(
  recovery: KarenOwnedTranscriptResponse,
  conversationId: string,
  offset: number,
  expectedRevision: string | null = null,
): KarenRecoveredTranscript {
  if (recovery.threadId !== conversationId ||
      recovery.read_only !== true || recovery.text_only !== true ||
      !Number.isInteger(recovery.omitted_entries) ||
      recovery.omitted_entries < 0 || recovery.omitted_entries > 500) {
    throw new Error("Recovery transcript identity or mode mismatch");
  }
  const pageOffset = recovery.page_offset ?? 0;
  const hasMore = recovery.has_more ?? false;
  const revision = recovery.snapshot_revision ?? null;
  if (pageOffset !== offset || typeof hasMore !== "boolean" ||
      (revision !== null && (typeof revision !== "string" ||
        revision.length === 0 || revision.length > 100)) ||
      (expectedRevision !== null && revision !== expectedRevision) ||
      (offset > 0 && revision === null) ||
      (hasMore && (revision === null || recovery.next_offset !== offset + 500)) ||
      (!hasMore && recovery.next_offset !== undefined &&
        recovery.next_offset !== null)) {
    throw new Error("Recovery transcript page integrity mismatch");
  }
  return {
    conversationId,
    messages: toCopilotTextMessages(recovery.messages),
    omittedEntries: recovery.omitted_entries,
    pageOffset,
    hasMore,
    nextOffset: hasMore ? offset + 500 : null,
    revision,
  };
}

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
  onStartNewConversation,
}: {
  conversationId: string;
  children: ReactNode;
  /** Only canonical SessionProvider navigation; never copies an SDK thread. */
  onStartNewConversation?: () => Promise<void>;
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
  const [transcript, setTranscript] = useState<KarenRecoveredTranscript | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [copyBusy, setCopyBusy] = useState(false);
  const [pageBusy, setPageBusy] = useState(false);
  const [pageStatus, setPageStatus] = useState<string | null>(null);
  const recoveryGeneration = useRef(0);

  useEffect(() => {
    recoveryGeneration.current += 1;
    if (!isReady) return;
    let cancelled = false;
    setLoaded(null);
    setError(null);
    setVerifiedParts(new Map());
    setTranscript(null);
    setCopyStatus(null);
    setCopyBusy(false);
    setPageBusy(false);
    setPageStatus(null);

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
            setTranscript(null);
            setError(null);
            setLoaded(conversationId);
            restored = true;
          } catch (error: unknown) {
            if (cancelled || restoreQueued) continue;
            const status = error && typeof error === "object" && "status" in error
              ? (error as { status?: unknown }).status : undefined;
            const replayUnsupported = status === 409 || (
              error instanceof Error && /^Unsupported verified /.test(error.message)
            );
            if (replayUnsupported) {
              // A fresh authenticated request to the canonical owned snapshot
              // is the only authority for text recovery. Never reuse an
              // unverified snapshot, invent messages, or mutate the SDK agent.
              try {
                const recovery = await apiClient.get<KarenOwnedTranscriptResponse>(
                  "/api/copilotkit/threads/" + conversationId + "/messages?view=transcript",
                );
                if (cancelled || restoreQueued) continue;
                setTranscript(verifiedTranscriptPage(recovery, conversationId, 0));
              } catch {
                if (cancelled || restoreQueued) continue;
                setTranscript(null);
              }
            } else {
              setTranscript(null);
            }
            if (!cancelled && !restoreQueued) {
              setError(replayUnsupported
                ? "This conversation contains content that Karen cannot faithfully restore in this chat yet. No partial conversation was opened. Verified saved text may be viewed read-only below when available."
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
      recoveryGeneration.current += 1;
      unsubscribe?.();
    };
  }, [agent, conversationId, isReady, retryAttempt]);

  const loadRecoveredPage = async (offset: number) => {
    const previous = transcript;
    if (!previous || previous.conversationId !== conversationId || pageBusy ||
        !previous.revision || !Number.isInteger(offset) || offset < 0 ||
        offset > 100000 || offset % 500 !== 0 ||
        (offset !== previous.pageOffset - 500 &&
         offset !== previous.nextOffset)) return;

    const generation = recoveryGeneration.current;
    setPageBusy(true);
    setPageStatus(null);
    try {
      const page = await apiClient.get<KarenOwnedTranscriptResponse>(
        "/api/copilotkit/threads/" + conversationId +
        "/messages?view=transcript&offset=" + offset,
      );
      if (generation !== recoveryGeneration.current) return;
      const verified = verifiedTranscriptPage(
        page, conversationId, offset, previous.revision,
      );
      setTranscript(verified);
      setCopyStatus(null);
    } catch {
      if (generation === recoveryGeneration.current) {
        setPageStatus("Another transcript page could not be verified. The last verified page remains available.");
      }
    } finally {
      if (generation === recoveryGeneration.current) setPageBusy(false);
    }
  };

  const copyRecoveredText = async () => {
    if (!transcript || transcript.conversationId !== conversationId ||
        copyBusy || transcript.messages.length === 0) return;
    setCopyBusy(true);
    setCopyStatus(null);
    try {
      const text = formatRecoveredConversationText(transcript.messages);
      if (new TextEncoder().encode(text).byteLength > MAX_RECOVERED_CLIPBOARD_BYTES) {
        setCopyStatus("Verified conversation text exceeds the clipboard limit. Select the messages below to copy them manually.");
        return;
      }
      if (!navigator.clipboard?.writeText) {
        setCopyStatus("Clipboard unavailable. Select the messages below to copy them manually.");
        return;
      }
      await navigator.clipboard.writeText(text);
      setCopyStatus(
        (transcript.pageOffset > 0 || transcript.hasMore
          ? "Verified transcript page copied. "
          : "Verified conversation text copied. ") +
        "Start a new conversation and paste it there if you want Karen to use that context.",
      );
    } catch {
      setCopyStatus("Copy could not be confirmed. Select the messages below to copy them manually.");
    } finally {
      setCopyBusy(false);
    }
  };

  if (!isReady || (loaded !== conversationId && !error)) {
    return <p role="status" className="text-sm text-muted-foreground">Restoring conversation...</p>;
  }
  if (error) {
    const recovered = transcript?.conversationId === conversationId ? transcript : null;
    return (
      <div className="flex w-full min-w-0 flex-col items-start gap-3 p-3">
        <p role="alert" className="text-sm text-destructive">{error}</p>
        {recovered && (
          <section aria-label="Recovered read-only text transcript"
            data-testid="karen-read-only-transcript" className="w-full min-w-0 rounded-md border p-3">
            <h3 className="text-sm font-semibold">Saved conversation text</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              This is a read-only, owner-verified text projection, not a restored
              chat. Rich cards, attachments, citations, and tool activity are
              not shown. Messages cannot be sent from this view. Copying text
              does not restore hidden cards, attachments, citations or tool
              results. A new conversation will not automatically inherit it.
              {recovered.revision && " Each page is owner-verified separately."}
              {recovered.omittedEntries > 0 &&
                ` ${recovered.omittedEntries} non-chat entries were withheld.`}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" disabled={copyBusy || pageBusy || recovered.messages.length === 0}
                onClick={() => void copyRecoveredText()}
                className="min-h-11 rounded-lg border border-input px-3 text-sm disabled:opacity-50">
                {copyBusy ? "Copying verified text…" : recovered.pageOffset > 0 || recovered.hasMore
                  ? "Copy this verified transcript page" : "Copy verified conversation text"}
              </button>
              {onStartNewConversation && (
                <button type="button" onClick={() => void onStartNewConversation()}
                  className="min-h-11 rounded-lg border border-input px-3 text-sm">
                  Start a new conversation
                </button>
              )}
            </div>
            {recovered.revision && (recovered.pageOffset > 0 || recovered.hasMore) && (
              <nav aria-label="Recovered transcript pages" className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  Saved entry page {recovered.pageOffset / 500 + 1}; only this page is displayed.
                </span>
                {recovered.pageOffset > 0 && (
                  <button type="button" disabled={pageBusy}
                    onClick={() => void loadRecoveredPage(recovered.pageOffset - 500)}
                    className="min-h-11 rounded-lg border border-input px-3 text-sm disabled:opacity-50">
                    Previous page
                  </button>
                )}
                {recovered.hasMore && recovered.nextOffset !== null && (
                  <button type="button" disabled={pageBusy}
                    onClick={() => void loadRecoveredPage(recovered.nextOffset!)}
                    className="min-h-11 rounded-lg border border-input px-3 text-sm disabled:opacity-50">
                    Next 500 saved entries
                  </button>
                )}
              </nav>
            )}
            {pageStatus && <p role="status" data-testid="karen-recovered-page-status"
              className="mt-2 text-xs text-muted-foreground">{pageStatus}</p>}
            {copyStatus && <p role="status" data-testid="karen-recovered-copy-status"
              className="mt-2 text-xs text-muted-foreground">{copyStatus}</p>}
            <ol className="mt-3 max-h-[65vh] space-y-3 overflow-y-auto"
              aria-label="Saved user and assistant messages">
              {recovered.messages.map(message => (
                <li key={message.id} className="min-w-0 rounded-md border p-2">
                  <p className="mb-1 text-xs font-semibold">
                    {message.role === "user" ? "You" : "Karen"}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
                </li>
              ))}
            </ol>
          </section>
        )}
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
