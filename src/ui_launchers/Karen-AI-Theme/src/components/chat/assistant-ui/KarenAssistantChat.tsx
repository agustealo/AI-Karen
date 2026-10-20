"use client";

/**
 * Karen-branded assistant-ui frontend over the canonical AG-UI transport.
 *
 * No frontend provider routing, model fallbacks, tools, checkpoint writes,
 * execution policy, or synthetic agent activity. The canonical Karen backend
 * owns all run execution and durable conversations.
 */
import { isValidElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  ActionBarPrimitive,
  AuiIf,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  ExportedMessageRepository,
} from "@assistant-ui/react";
import { HttpAgent } from "@ag-ui/client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fromAgUiMessages, useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { ArrowDown, ArrowUp, Bot, Check, CheckCircle2, ChevronDown, CircleAlert, Clock3, Copy, Loader2, Plus, Search, Square, ShieldCheck } from "lucide-react";
import { apiClient } from "@/lib/api";
import type { ConversationResponse } from "@/lib/types";
import { useSession } from "@/components/chat/ChatInterface";

type Activity = {
  stepId?: string;
  agentId?: string;
  status?: string;
  description?: string;
  runId?: string;
  eventId?: string;
  timestamp?: string;
  content?: {
    stepId?: string;
    agentId?: string;
    status?: string;
    description?: string;
    runId?: string;
    eventId?: string;
    timestamp?: string;
  };
};

function KarenActivity({ data, category = "Agent step" }: { data: unknown; category?: "Agent step" | "Plan" | "Subagent" }) {
  const disclosureRef = useRef<HTMLDetailsElement>(null);
  const raw = (typeof data === "object" && data ? data : {}) as Activity;
  const value = raw.content && typeof raw.content === "object"
    ? raw.content : raw;
  const fields = value as Record<string, unknown>;
  const agent = (typeof fields.agent_id === "string" && fields.agent_id) || (typeof value.agentId === "string" && value.agentId) || "Agent";
  const status = (typeof value.status === "string" && value.status) || "observed";
  const description =
    typeof value.description === "string" ? value.description : "";
  // Display only identifiers and timestamps supplied by an observed runtime event.
  // Do not synthesize event ordering or a completed workflow from missing fields.
  const runId = typeof fields.run_id === "string" ? fields.run_id
    : typeof value.runId === "string" ? value.runId : "";
  const eventId = typeof fields.event_id === "string" ? fields.event_id
    : typeof value.eventId === "string" ? value.eventId : "";
  const rawTimestamp = typeof fields.timestamp === "string" ? fields.timestamp
    : typeof fields.occurred_at === "string" ? fields.occurred_at : "";
  const reportedAt = rawTimestamp && !Number.isNaN(Date.parse(rawTimestamp))
    ? new Date(rawTimestamp).toLocaleString() : "";
  // Unknown statuses remain observed, never inferred as success.
  const normalized = status.trim().toLowerCase();
  const failed = ["failed", "failure", "error", "errored", "cancelled", "canceled"].includes(normalized);
  const done = ["finished", "completed", "complete", "succeeded", "success"].includes(normalized);
  const StatusIcon = failed ? CircleAlert : done ? CheckCircle2 : Clock3;
  useEffect(() => {
    // Open failures once when observed, but let the user collapse the details.
    if (failed && disclosureRef.current) disclosureRef.current.open = true;
  }, [failed]);
  if (!data || typeof data !== "object") return null;
  return (
    <details ref={disclosureRef} data-testid="karen-agent-activity" className="my-2 rounded-xl border border-border/60 bg-muted/20 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <Bot className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate font-medium">{category}: {agent}</span>
        <StatusIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs text-muted-foreground" aria-label={`Reported status: ${status}`}>{status}</span>
        <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </summary>
      <div className="border-t border-border/50 px-3 py-3 text-muted-foreground">
        {description ? <p className="whitespace-pre-wrap">{description}</p> : <p>No further activity details were reported.</p>}
        {(typeof fields.step_id === "string" && fields.step_id || value.stepId) ? <p className="mt-2 break-all text-xs">Step: {typeof fields.step_id === "string" ? fields.step_id : value.stepId}</p> : null}
        {runId ? <p className="mt-1 break-all text-xs">AG-UI run: {runId}</p> : null}
        {eventId ? <p className="mt-1 break-all text-xs">Event: {eventId}</p> : null}
        {reportedAt ? <p className="mt-1 text-xs">Reported: {reportedAt}</p> : null}
      </div>
    </details>
  );
}

function KarenLearningDecision({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const decision = data as Record<string, unknown>;
  const selection = decision.selection_source;
  const status = decision.learning_signal_status;
  if (typeof selection !== "string" || typeof status !== "string") return null;
  const label = selection === "shadow_operational_recommendation"
    ? "Learned recommendation evaluated in shadow. Registered model used."
    : selection === "learning_operational_reliability_v1"
      ? "Learned operational evidence influenced model selection."
      : selection === "explicit_runtime_or_user"
        ? "Explicit model selection retained."
        : "Registered model selection retained.";
  return (
    <details data-testid="karen-learning-provenance"
      className="my-2 rounded-xl border border-border/60 bg-muted/20 text-sm">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 font-medium">Model decision</span>
        <span className="text-xs text-muted-foreground">Details</span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </summary>
      <div className="space-y-2 border-t border-border/50 px-3 py-3">
        <p>{label}</p>
        <p className="text-muted-foreground">Evidence: {status}. Operational evidence is not proof of answer correctness.</p>
      </div>
    </details>
  );
}

function KarenCheckpoint({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const checkpoint = data as Record<string, unknown>;
  if (checkpoint.checkpoint_verified !== true) return null;
  return (
    <details data-testid="karen-checkpoint-evidence"
      className="my-2 rounded-xl border border-border/60 text-sm">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
        <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 font-medium">Checkpoint persisted</span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      </summary>
      <p className="border-t border-border/50 px-3 py-3 text-muted-foreground">
        The runtime verified storage, but restart recovery is not verified. No resume action is available.
      </p>
    </details>
  );
}

function KarenApprovalNotice({ data }: { data: unknown }) {
  if (!data || typeof data !== "object") return null;
  const approval = data as Record<string, unknown>;
  if (typeof approval.approval_id !== "string" || !approval.approval_id) return null;
  return (
    <div role="status" data-testid="karen-approval-required"
      className="my-2 rounded-lg border border-amber-600/40 p-3 text-xs">
      The runtime requires approval. Use the governed approvals workflow to review this action.
      No action will execute from this informational notice.
    </div>
  );
}

function KarenAgentStep({ data }: { data: unknown }) {
  return <KarenActivity data={data} category="Agent step" />;
}

function KarenAgentPlan({ data }: { data: unknown }) {
  return <KarenActivity data={data} category="Plan" />;
}

function KarenSubagent({ data }: { data: unknown }) {
  return <KarenActivity data={data} category="Subagent" />;
}

const agentParts = {
  data: {
    by_name: {
      "karen.learning_decision": KarenLearningDecision,
      "karen.checkpoint": KarenCheckpoint,
      "karen.approval_required": KarenApprovalNotice,
      "agui-activity/KAREN_AGENT_STEP": KarenAgentStep,
      "agui-activity/KAREN_DEEPAGENTS_PLAN": KarenAgentPlan,
      "agui-activity/KAREN_DEEPAGENTS_SUBAGENT": KarenSubagent,
    },
  },
  tools: {
    // Render-only. No client execution, fake tool result, or permission path.
    Fallback: ({ toolName, status }: { toolName?: string; status?: { type?: string } }) => {
      const observedState = status?.type || "unknown";
      const stateLabel = observedState === "complete"
        ? "Tool call completed"
        : observedState === "running"
          ? "Tool call in progress"
          : observedState === "incomplete"
            ? "Tool call incomplete"
            : "Tool activity observed";
      return (
        <details className="my-2 rounded-xl border border-border/70 bg-muted/20 text-sm"
          data-testid="karen-observed-tool">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            <Bot className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate font-medium">{toolName || "Observed tool call"}</span>
            <span className="text-xs text-muted-foreground">{stateLabel}</span>
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          </summary>
          <p className="border-t border-border/50 px-3 py-3 text-sm text-muted-foreground">
            This is observed tool lifecycle activity. It does not confirm that an external action succeeded.
            Only Karen&apos;s governed execution receipt can confirm an external side effect.
          </p>
        </details>
      );
    },
  },
};

function KarenCodeBlock({ children }: { children?: ReactNode }) {
  const codeElement = isValidElement<{ children?: ReactNode; className?: string }>(children)
    ? children : null;
  const source = typeof codeElement?.props.children === "string"
    ? codeElement.props.children.replace(/\\n$/, "") : null;
  const language = codeElement?.props.className?.match(/language-([a-zA-Z0-9_+-]+)/)?.[1];
  const [copied, setCopied] = useState(false);

  useEffect(() => setCopied(false), [source]);

  const copyCode = async () => {
    if (source === null || !navigator.clipboard?.writeText) return;
    try {
      await navigator.clipboard.writeText(source);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="my-3 min-w-0 overflow-hidden rounded-lg border border-border/60 bg-muted/40">
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-border/50 px-3">
        <span className="truncate font-mono text-xs text-muted-foreground">{language || "Code"}</span>
        <button type="button" onClick={() => void copyCode()}
          disabled={source === null}
          aria-label={copied ? "Code copied" : "Copy code block"}
          className="inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50">
          {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre className="max-w-full overflow-x-auto p-3 text-sm leading-6">{children}</pre>
    </div>
  );
}

function KarenMarkdownText({ text }: { text: string }) {
  return (
    <div className="min-w-0 break-words text-sm leading-7 text-foreground [&_a]:break-all [&_a]:text-primary [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-4 [&_code]:break-words [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_pre]:my-3 [&_pre]:max-w-full [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-3 [&_pre_code]:break-normal [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_ul]:list-disc [&_ol]:list-decimal [&_ul]:pl-5 [&_ol]:pl-5 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{ pre: KarenCodeBlock }}
        urlTransform={(url) => /^(https?:|mailto:)/i.test(url) ? url : ""}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function KarenCopyAction() {
  return (
    <ActionBarPrimitive.Root hideWhenRunning className="px-1">
      <ActionBarPrimitive.Copy
        aria-label="Copy message"
        title="Copy message"
        copiedDuration={2000}
        className="group/copy inline-flex min-h-10 items-center gap-2 rounded-lg px-3 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:opacity-50"
      >
        <Copy className="h-4 w-4 group-data-[copied]/copy:hidden" aria-hidden="true" />
        <Check className="hidden h-4 w-4 group-data-[copied]/copy:block" aria-hidden="true" />
        <span className="group-data-[copied]/copy:hidden">Copy</span>
        <span className="hidden group-data-[copied]/copy:inline">Copied</span>
      </ActionBarPrimitive.Copy>
    </ActionBarPrimitive.Root>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex flex-col items-end gap-1 px-4 py-2">
      <div className="max-w-[92%] whitespace-pre-wrap break-words rounded-2xl bg-primary px-4 py-3 text-base leading-6 text-primary-foreground sm:max-w-[85%]">
        <MessagePrimitive.Parts />
      </div>
      <KarenCopyAction />
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="flex flex-col items-start gap-1 px-4 py-2">
      <div className="w-full max-w-full space-y-3 rounded-2xl border border-border/50 bg-card px-4 py-4 text-base leading-7 sm:max-w-[95%] sm:px-5">
        <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Bot className="h-4 w-4" aria-hidden="true" /> Karen
        </div>
        <MessagePrimitive.Parts components={{ ...agentParts, Text: KarenMarkdownText }} />
      </div>
      <KarenCopyAction />
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
                className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2 text-base outline-none"
              />
              <AuiIf condition={(s) => s.composer.canCancel}>
                <ComposerPrimitive.Cancel
                  title="Stop response" aria-label="Stop response"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-input"
                ><Square className="h-4 w-4" aria-hidden="true" /></ComposerPrimitive.Cancel>
              </AuiIf>
              <ComposerPrimitive.Send
                title="Send message" aria-label="Send message"
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground disabled:opacity-40"
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
          // The canonical SessionProvider switches conversations and remounts
          // KarenAgUiRuntime by durable thread ID. History loads there through
          // the repository adapter, not a second untyped message conversion.
          await loadSession(id);
          return { messages: [] };
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
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const historySearchRef = useRef<HTMLInputElement>(null);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (historyOpen) historySearchRef.current?.focus();
  }, [historyOpen]);
  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    historyTriggerRef.current?.focus();
  }, []);
  const switchConversation = useCallback(async (id: string) => {
    setNavigationError(null);
    try {
      await loadSession(id);
      closeHistory();
    } catch {
      setNavigationError("Unable to open that conversation. Please try again.");
    }
  }, [loadSession, closeHistory]);
  const startConversation = useCallback(async () => {
    setNavigationError(null);
    try {
      await createNewSession();
      setHistoryOpen(false);
    } catch {
      setNavigationError("Unable to create a conversation. Please try again.");
    }
  }, [createNewSession]);
  const matchingSessions = useMemo(() => sessions.filter((session) =>
    (session.title || "Untitled conversation").toLowerCase().includes(historyQuery.trim().toLowerCase()),
  ), [sessions, historyQuery]);
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
        <button type="button" onClick={() => void startConversation()}
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
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button" ref={historyTriggerRef} aria-label="Find conversations" aria-expanded={historyOpen} aria-controls={historyOpen ? "karen-conversation-history" : undefined}
            onClick={() => setHistoryOpen((open) => !open)}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-input px-3 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
          >
            <Search className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Conversations</span>
          </button>
          <button
            title="New conversation" aria-label="New conversation"
            type="button" onClick={() => void startConversation()}
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-input hover:bg-muted"
          ><Plus className="h-4 w-4" /></button>
        </div>
      </header>
      {navigationError && <p role="alert" className="border-b border-destructive/40 px-4 py-2 text-sm text-destructive">{navigationError}</p>}
      {historyOpen && (
        <section id="karen-conversation-history" aria-label="Conversation history"
          className="border-b border-border/60 bg-background px-4 py-3"
          onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); closeHistory(); } }}>
          <label htmlFor="karen-history-search" className="mb-2 block text-sm font-medium">Find a conversation</label>
          <div className="relative max-w-lg">
            <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <input id="karen-history-search" ref={historySearchRef} type="search" value={historyQuery}
              onChange={(event) => setHistoryQuery(event.target.value)}
              placeholder="Search conversation titles"
              className="h-11 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-base outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring" />
          </div>
          <div className="mt-2 max-h-48 overflow-y-auto" role="group" aria-label="Matching conversations">
            {matchingSessions.length === 0 ? (
              <p className="py-3 text-sm text-muted-foreground">No matching conversations.</p>
            ) : matchingSessions.map((session) => (
              <button key={session.id} type="button"
                aria-current={session.id === currentSession.id ? "page" : undefined}
                onClick={() => void switchConversation(session.id)}
                className="block min-h-11 w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring aria-[current=page]:bg-muted aria-[current=page]:font-semibold">
                {session.title || "Untitled conversation"}
              </button>
            ))}
          </div>
        </section>
      )}
      <KarenAgUiRuntime key={currentSession.id} threadId={currentSession.id} />
    </div>
  );
}
