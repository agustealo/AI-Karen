"use client";

/**
 * Canonical consumer session/navigation adapter for the CopilotKit chat.
 *
 * SessionProvider remains the sole owner of persisted conversation identities.
 * This adapter performs no history writes, provider routing, or SDK inference.
 * It is mounted by the dashboard on the draft cutover branch; browser and
 * release parity remain unverified until acceptance runs against that revision.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Plus, Search } from "lucide-react";

import { useSession } from "@/components/chat/SessionProvider";
import { KarenCopilotChat } from "./KarenCopilotChat";
import { KarenComposerRuntimeCatalog } from "../runtime/KarenComposerRuntimeCatalog";
import type { ComposerModelRequest } from "../runtime/KarenComposerRuntimeCatalog";

export function KarenCopilotConsumerChat() {
  const {
    currentSession,
    strictInitialSession,
    workspaceRunId,
    sessions,
    createNewSession,
    loadSession,
    isLoadingSessions,
    error: sessionError,
  } = useSession();
  const [query, setQuery] = useState("");
  const [modelRequest, setModelRequest] = useState<ComposerModelRequest>(null);
  const [runBusy, setRunBusy] = useState(false);
  const busyRef = useRef(false);
  const handleBusyChange = useCallback((busy: boolean) => {
    busyRef.current = busy;
    setRunBusy(busy);
  }, []);
  const handleModelRequest = useCallback((request: ComposerModelRequest) => {
    if (!busyRef.current) setModelRequest(request);
  }, []);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [navigationBusy, setNavigationBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const historyButtonRef = useRef<HTMLButtonElement>(null);
  const pendingRef = useRef(false);

  useEffect(() => {
    if (historyOpen) inputRef.current?.focus();
  }, [historyOpen]);

  const closeHistory = useCallback(() => {
    setHistoryOpen(false);
    historyButtonRef.current?.focus();
  }, []);

  const performNavigation = useCallback(async (operation: () => Promise<void>) => {
    if (pendingRef.current || busyRef.current) {
      if (busyRef.current) setNavigationError("Stop or finish the current run before changing conversations.");
      return;
    }
    pendingRef.current = true;
    setNavigationBusy(true);
    setNavigationError(null);
    try {
      await operation();
      closeHistory();
    } catch {
      setNavigationError("Conversation change could not be saved. Your current conversation is unchanged.");
    } finally {
      pendingRef.current = false;
      setNavigationBusy(false);
    }
  }, [closeHistory]);

  const matchingSessions = useMemo(() => {
    const filter = query.trim().toLocaleLowerCase();
    return sessions.filter(session =>
      (session.title || "Untitled conversation").toLocaleLowerCase().includes(filter)
    );
  }, [query, sessions]);

  if (isLoadingSessions) {
    return (
      <div role="status" className="flex min-h-0 flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
        Loading conversations…
      </div>
    );
  }

  if (!currentSession) {
    return (
      <section aria-label="Start a Karen conversation" className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 p-4">
        <p role={sessionError || navigationError ? "alert" : "status"} className="max-w-md text-center text-sm text-muted-foreground">
          {navigationError || sessionError || "Start a durable conversation to chat with Karen."}
        </p>
        {!strictInitialSession && (
          <button
            type="button"
            disabled={navigationBusy || runBusy}
            onClick={() => void performNavigation(createNewSession)}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            New conversation
          </button>
        )}
      </section>
    );
  }

  return (
    <section data-testid="karen-copilot-consumer-chat" data-conversation-id={currentSession.id} aria-label="Karen conversation workspace"
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <header className="flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-border/60 px-4">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">{currentSession.title || "Conversation"}</h2>
          <p className="text-xs text-muted-foreground">Karen runtime controls model execution and saved history</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div id="karen-rail-customize-menu" className="hidden xl:flex" aria-label="Customize conversation intelligence" />
          <span aria-hidden="true" className="hidden h-6 w-px bg-border xl:block" />
          {!strictInitialSession && (
            <>
            <button type="button" ref={historyButtonRef} disabled={navigationBusy || runBusy}
              aria-label="Find conversations" aria-expanded={historyOpen}
              aria-controls={historyOpen ? "karen-copilot-history" : undefined}
              onClick={() => { if (!busyRef.current && !pendingRef.current) setHistoryOpen(open => !open); }}
              className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-input px-3 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
              <Search aria-hidden="true" className="h-4 w-4" />
              <span className="hidden sm:inline">Conversations</span>
            </button>
            <button type="button" aria-label="New conversation" title="New conversation"
              disabled={navigationBusy || runBusy} onClick={() => void performNavigation(createNewSession)}
              className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-input hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
              <Plus aria-hidden="true" className="h-4 w-4" />
            </button>
            </>
          )}
        </div>
      </header>
      {navigationError && <p role="alert" className="border-b border-destructive/40 px-4 py-2 text-sm text-destructive">{navigationError}</p>}
      {!strictInitialSession && historyOpen && (
        <section id="karen-copilot-history" aria-label="Conversation history"
          onKeyDown={event => {
            if (event.key === "Escape") {
              event.preventDefault();
              closeHistory();
            }
          }}
          className="shrink-0 border-b border-border/60 bg-background px-4 py-3">
          <label htmlFor="karen-copilot-history-search" className="mb-2 block text-sm font-medium">Find a conversation</label>
          <div className="relative max-w-lg">
            <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" />
            <input id="karen-copilot-history-search" ref={inputRef} type="search"
              value={query} onChange={event => setQuery(event.target.value)}
              placeholder="Search conversation titles"
              className="h-11 w-full rounded-xl border border-input bg-background pl-10 pr-3 text-base outline-offset-2 focus-visible:outline-2 focus-visible:outline-ring" />
          </div>
          <div role="group" aria-label="Matching conversations" className="mt-2 max-h-48 overflow-y-auto">
            {matchingSessions.length === 0 ? (
              <p className="py-3 text-sm text-muted-foreground">No matching conversations.</p>
            ) : matchingSessions.map(session => (
              <button type="button" key={session.id} disabled={navigationBusy || runBusy}
                data-conversation-id={session.id}
                aria-current={session.id === currentSession.id ? "page" : undefined}
                onClick={() => void performNavigation(() => loadSession(session.id))}
                className="block min-h-11 w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50 aria-[current=page]:bg-muted aria-[current=page]:font-semibold">
                {session.title || "Untitled conversation"}
              </button>
            ))}
          </div>
        </section>
      )}
      <details data-testid="karen-copilot-model-discovery" className="shrink-0 border-b border-border/60 px-4 py-2">
        <summary className="cursor-pointer text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
          Model and provider
        </summary>
        <fieldset disabled={runBusy} className="max-w-2xl py-2 disabled:opacity-60">
          <KarenComposerRuntimeCatalog selection={modelRequest} onSelectionChange={handleModelRequest} />
        </fieldset>
        {runBusy && <p role="status" className="text-xs text-muted-foreground">
          Model changes are unavailable while Karen is processing this message.
        </p>}
      </details>
      <KarenCopilotChat
        key={currentSession.id}
        conversationId={currentSession.id}
        preferredProvider={modelRequest?.provider ?? null}
        preferredModel={modelRequest?.model ?? null}
        workspaceRunId={workspaceRunId}
        onBusyChange={handleBusyChange}
      />
    </section>
  );
}
