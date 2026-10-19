"use client";

/**
 * Karen-branded assistant-ui frontend over the canonical AG-UI transport.
 *
 * No frontend provider routing, model fallbacks, tools, checkpoint writes,
 * execution policy, or synthetic agent activity. The canonical Karen backend
 * owns all run execution and durable conversations.
 */
import { useCallback, useMemo, useState } from "react";
import {
  AssistantRuntimeProvider,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  ExportedMessageRepository,
} from "@assistant-ui/react";
import { HttpAgent } from "@ag-ui/client";
import { fromAgUiMessages, useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { ArrowDown, ArrowUp, Bot, Loader2, Plus, Square, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";
import type { ConversationResponse } from "@/lib/types";
import { useSession } from "@/components/chat/ChatInterface";

type Activity = {
  stepId?: string;
  agentId?: string;
  status?: string;
  description?: string;
  content?: {
    stepId?: string;
    agentId?: string;
    status?: string;
    description?: string;
  };
};

function KarenActivity({ data }: { data: unknown }) {
  if (typeof data !== "object" || !data) return null;
  const raw = data as Activity;
  const value = raw.content && typeof raw.content === "object"
    ? raw.content : raw;
  const agent = (typeof value.agentId === "string" && value.agentId) || "Agent";
  const status = (typeof value.status === "string" && value.status) || "observed";
  const description =
    typeof value.description === "string" ? value.description : "";
  return (
    <div data-testid="karen-agent-activity" className="my-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-sm">
      <div className="flex items-center gap-2 font-medium">
        <Bot className="h-4 w-4" aria-hidden="true" />
        <span>{agent}</span>
        <span className="ml-auto text-xs text-muted-foreground">{status}</span>
      </div>
      {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
    </div>
  );
}

const agentParts = {
  data: {
    by_name: {
      "agui-activity/KAREN_AGENT_STEP": KarenActivity,
      "agui-activity/KAREN_DEEPAGENTS_PLAN": KarenActivity,
      "agui-activity/KAREN_DEEPAGENTS_SUBAGENT": KarenActivity,
    },
  },
  tools: {
    // Render-only. No client execution, fake tool result, or permission path.
    Fallback: ({ toolName, status }: { toolName?: string; status?: { type?: string } }) => (
      <div className="my-2 rounded-lg border border-border/70 px-3 py-2 text-xs"
        data-testid="karen-observed-tool">
        <span className="font-medium">{toolName || "Observed tool call"}</span>
        <span className="ml-2 text-muted-foreground">
          {status?.type || "pending"}
        </span>
      </div>
    ),
  },
};

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end px-4 py-2">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-3 text-sm text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-start px-4 py-2">
      <div className="w-full max-w-[92%] space-y-2 rounded-2xl border border-border/50 bg-card px-4 py-3 text-sm leading-7">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Bot className="h-4 w-4" aria-hidden="true" /> Karen
        </div>
        <MessagePrimitive.Parts components={agentParts} />
      </div>
    </MessagePrimitive.Root>
  );
}

function KarenThread() {
  return (
    <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
      <ThreadPrimitive.Viewport
        className="relative flex min-h-0 flex-1 flex-col overflow-y-auto"
        autoScroll
      >
        <AuiIf condition={(s) => s.thread.isEmpty}>
          <div className="mx-auto flex min-h-[35vh] max-w-xl flex-col items-center justify-center gap-3 px-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10">
              <Bot className="h-6 w-6" aria-hidden="true" />
            </div>
            <h2 className="text-xl font-semibold tracking-tight">What can Karen help you accomplish?</h2>
            <p className="text-sm text-muted-foreground">
              Ask a question, plan a task, or delegate research. Agent activity appears when the backend actually reports it.
            </p>
          </div>
        </AuiIf>
        <div className="mx-auto w-full max-w-3xl flex-1 py-4" role="log" aria-label="Conversation">
          <ThreadPrimitive.Messages>
            {({ message }) => message.role === "user"
              ? <UserMessage /> : <AssistantMessage />}
          </ThreadPrimitive.Messages>
        </div>
        <ThreadPrimitive.ViewportFooter className="sticky bottom-0 z-10 border-t border-border/60 bg-background/95 px-4 py-3 backdrop-blur">
          <div className="mx-auto max-w-3xl">
            <AuiIf condition={(s) => s.thread.isRunning}>
              <p role="status" aria-live="polite" className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                Karen is working
              </p>
            </AuiIf>
            <ComposerPrimitive.Root className="flex items-end gap-2 rounded-2xl border border-input bg-card p-2 shadow-sm">
              <ComposerPrimitive.Input
                rows={1}
                aria-label="Message Karen"
                placeholder="Message Karen..."
                className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none"
              />
              <AuiIf condition={(s) => s.composer.canCancel}>
                <ComposerPrimitive.Cancel
                  title="Stop response" aria-label="Stop response"
                  className="flex h-10 w-10 items-center justify-center rounded-xl border border-input"
                ><Square className="h-4 w-4" aria-hidden="true" /></ComposerPrimitive.Cancel>
              </AuiIf>
              <ComposerPrimitive.Send
                title="Send message" aria-label="Send message"
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground disabled:opacity-40"
              ><ArrowUp className="h-4 w-4" aria-hidden="true" /></ComposerPrimitive.Send>
            </ComposerPrimitive.Root>
            <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                Models, memory and tools governed by Karen
              </span>
              <ThreadPrimitive.ScrollToBottom
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 hover:bg-muted"
              ><ArrowDown className="h-3 w-3" /> Latest</ThreadPrimitive.ScrollToBottom>
            </div>
          </div>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
  );
}

type DurableMessage = { id?: string; role: string; content: string };

async function readOwnedHistory(conversationId: string) {
  const conversation = await apiClient.get<ConversationResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
  );
  if (conversation.id !== conversationId) {
    throw new Error("Conversation history identity mismatch");
  }
  const saved = (conversation.messages || []) as DurableMessage[];
  const converted = saved
    .filter((m) => (m.role === "user" || m.role === "assistant") && typeof m.content === "string")
    .map((m, i) => ({
      id: m.id || `${conversationId}-persisted-${i}`,
      role: m.role as "user" | "assistant",
      content: m.content,
    }));
  return fromAgUiMessages(
    converted as Parameters<typeof fromAgUiMessages>[0],
    { showThinking: false },
  );
}

function KarenAgUiRuntime({ threadId }: { threadId: string }) {
  const { createNewSession, loadSession } = useSession();
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const agent = useMemo(
    () => new HttpAgent({ url: "/api/chat/ag-ui" }),
    [],
  );
  const historyLoad = useCallback(
    async () => ExportedMessageRepository.fromArray(
      await readOwnedHistory(threadId),
    ),
    [threadId],
  );
  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
    onError: (error) => setRuntimeError(error.message || "Agent run failed"),
    adapters: {
      history: {
        load: historyLoad,
        // ChatRuntime persists its own transcript, including errors.
        // No UI-only "saved" state or second persistence service.
        append: async () => {},
      },
      threadList: {
        threadId,
        onSwitchToNewThread: async () => {
          await createNewSession();
        },
        onSwitchToThread: async (id: string) => {
          await loadSession(id);
          return { messages: await readOwnedHistory(id) };
        },
      },
    },
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {runtimeError && (
        <p role="alert" className="border-b border-destructive/40 px-4 py-2 text-sm text-destructive">
          {runtimeError}
        </p>
      )}
      <KarenThread />
    </AssistantRuntimeProvider>
  );
}

export default function KarenAssistantChat() {
  const {
    currentSession, sessions, createNewSession, loadSession,
    isLoadingSessions, error,
  } = useSession();
  if (isLoadingSessions) {
    return <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" /> Loading conversations…
    </div>;
  }
  if (!currentSession) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <p role={error ? "alert" : undefined} className="text-sm text-muted-foreground">
          {error || "Start a durable conversation to chat with Karen."}
        </p>
        <button type="button" onClick={() => void createNewSession()}
          className="rounded-xl bg-primary px-4 py-2 text-primary-foreground">
          New conversation
        </button>
      </div>
    );
  }
  return (
    <div data-testid="karen-assistant-ui-chat" className="flex h-full min-h-0 flex-1 flex-col overflow-hidden">
      <header className="flex min-h-14 items-center justify-between gap-3 border-b border-border/60 px-4">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{currentSession.title || "Conversation"}</p>
          <p className="text-xs text-muted-foreground">Agent activity is based on observed runtime events</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            aria-label="Choose conversation"
            value={currentSession.id}
            onChange={(event) => void loadSession(event.target.value)}
            className="max-w-40 rounded-lg border border-input bg-background px-2 py-2 text-xs"
          >
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>{session.title}</option>
            ))}
          </select>
          <button
            title="New conversation" aria-label="New conversation"
            type="button" onClick={() => void createNewSession()}
            className="flex h-9 w-9 items-center justify-center rounded-lg border border-input"
          ><Plus className="h-4 w-4" /></button>
        </div>
      </header>
      <KarenAgUiRuntime key={currentSession.id} threadId={currentSession.id} />
    </div>
  );
}
