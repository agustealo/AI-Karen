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
import { Loader2, MoreHorizontal, Plus, Search } from "lucide-react";

import { useSession } from "@/components/chat/SessionProvider";
import { KarenCopilotChat } from "./KarenCopilotChat";
import { KarenComposerRuntimeCatalog } from "../KarenComposerRuntimeCatalog";
import type { ComposerModelRequest } from "../KarenComposerRuntimeCatalog";

export function KarenCopilotConsumerChat() {
  const {
    currentSession,
    strictInitialSession,
    workspaceRunId,
    sessions,
    createNewSession,
    loadSession,
    updateSessionTitle,
    deleteSessionWithOutcome,
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
  const [manageOpen, setManageOpen] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
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

  const performNavigation = useCallback(async (operation: () => Promise<boolean | void>) => {
    if (pendingRef.current || busyRef.current) {
      if (busyRef.current) setNavigationError("Stop or finish the current run before changing conversations.");
      return;
    }
    pendingRef.current = true;
    setNavigationBusy(true);
    setNavigationError(null);
    try {
      const verified = await operation();
      if (verified === false) {
        setNavigationError("The requested conversation was not verified. Your conversation history remains open.");
        return;
      }
      closeHistory();
    } catch {
      setNavigationError("Conversation change could not be saved. Your current conversation is unchanged.");
    } finally {
      pendingRef.current = false;
      setNavigationBusy(false);
    }
  }, [closeHistory]);

  const saveTitle = useCallback(async () => {
    if (!currentSession || pendingRef.current || busyRef.current) return;
    const title = titleDraft.trim();
    if (!title || title.length > 160) {
      setNavigationError("Use a conversation title between 1 and 160 characters.");
      return;
    }
    pendingRef.current = true;
    setNavigationBusy(true);
    setNavigationError(null);
    try {
      const saved = await updateSessionTitle(currentSession.id, title);
      if (saved !== true) {
        setNavigationError("Karen could not save the conversation title.");
        return;
      }
      setEditingTitle(false);
      setManageOpen(false);
    } catch {
      setNavigationError("Karen could not save the conversation title.");
    } finally {
      pendingRef.current = false;
      setNavigationBusy(false);
    }
  }, [currentSession, titleDraft, updateSessionTitle]);

  const removeConversation = useCallback(async () => {
    if (!currentSession || pendingRef.current || busyRef.current || !deleteConfirm) return;
    pendingRef.current = true;
    setNavigationBusy(true);
    setNavigationError(null);
    try {
      const result = await deleteSessionWithOutcome(currentSession.id);
      if (!result.deleted) {
        setNavigationError("Karen could not delete this conversation.");
        return;
      }
      setDeleteConfirm(false);
      setManageOpen(false);
      if (result.replacementCreated === false) {
        setNavigationError("Conversation deleted, but a new conversation could not be created. Start a new conversation to continue.");
      } else if (!result.historyRefreshed) {
        setNavigationError("Conversation deleted, but the history list could not be refreshed.");
      }
    } catch {
      setNavigationError("Karen could not delete this conversation.");
    } finally {
      pendingRef.current = false;
      setNavigationBusy(false);
    }
  }, [currentSession, deleteConfirm, deleteSessionWithOutcome]);

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
          {navigationError || sessionError || "What would you like to work on?"}
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
          <p className="text-xs text-muted-foreground">Your space to think, create, and get things done</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div id="karen-rail-customize-menu" className="hidden xl:flex" aria-label="Customize conversation intelligence" />
          <span aria-hidden="true" className="hidden h-6 w-px bg-border xl:block" />
          {!strictInitialSession && (
            <>
            <button type="button" aria-label="Conversation options" aria-expanded={manageOpen}
              disabled={navigationBusy || runBusy}
              onClick={() => {
                setManageOpen(open => !open);
                setEditingTitle(false);
                setDeleteConfirm(false);
                setTitleDraft(currentSession.title || "");
              }}
              className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-input hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50">
              <MoreHorizontal aria-hidden="true" className="h-4 w-4" />
            </button>
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
      {!strictInitialSession && manageOpen && (
        <section aria-label="Conversation options" className="shrink-0 border-b border-border/60 bg-background px-4 py-3">
          {!editingTitle && !deleteConfirm && (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={navigationBusy || runBusy}
                onClick={() => { setEditingTitle(true); setTitleDraft(currentSession.title || ""); }}
                className="min-h-11 rounded-lg border border-input px-3 text-sm">Rename conversation</button>
              <button type="button" disabled={navigationBusy || runBusy}
                onClick={() => setDeleteConfirm(true)}
                className="min-h-11 rounded-lg border border-destructive/50 px-3 text-sm text-destructive">
                Delete conversation
              </button>
            </div>
          )}
          {editingTitle && (
            <form onSubmit={event => { event.preventDefault(); void saveTitle(); }}
              className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium">
                Conversation title
                <input aria-label="Conversation title" value={titleDraft} maxLength={160}
                  onChange={event => setTitleDraft(event.target.value)}
                  className="min-h-11 rounded-lg border border-input bg-background px-3 text-sm" />
              </label>
              <button type="submit" disabled={navigationBusy || runBusy || !titleDraft.trim()}
                className="min-h-11 rounded-lg bg-primary px-3 text-sm text-primary-foreground disabled:opacity-50">
                Save title
              </button>
              <button type="button" onClick={() => setEditingTitle(false)} disabled={navigationBusy}
                className="min-h-11 rounded-lg border border-input px-3 text-sm">Cancel</button>
            </form>
          )}
          {deleteConfirm && (
            <div role="group" aria-label="Confirm conversation deletion" className="space-y-2">
              <p className="text-sm">Delete this conversation and its saved messages? This cannot be undone.</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={navigationBusy || runBusy}
                  onClick={() => void removeConversation()}
                  className="min-h-11 rounded-lg bg-destructive px-3 text-sm text-destructive-foreground disabled:opacity-50">
                  Confirm delete
                </button>
                <button type="button" disabled={navigationBusy} onClick={() => setDeleteConfirm(false)}
                  className="min-h-11 rounded-lg border border-input px-3 text-sm">Keep conversation</button>
              </div>
            </div>
          )}
        </section>
      )}
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
          Model preferences
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
