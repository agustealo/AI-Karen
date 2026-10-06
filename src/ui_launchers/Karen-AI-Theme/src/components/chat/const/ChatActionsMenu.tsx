import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown,
  Copy,
  Download,
  History,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { toast } from '@/hooks/use-toast';

import type { Session } from '../types';

interface ChatActionsMenuProps {
  currentSession: Session | null;
  isLoadingSessions: boolean;
  createNewSession: () => Promise<void>;
  refreshSessions: () => Promise<void>;
  updateSessionTitle: (sessionId: string, newTitle: string) => Promise<boolean>;
  deleteSession: (sessionId: string) => Promise<boolean | void>;
  onOpenHistory: () => void;
  onExportChat?: () => Promise<void> | void;
  onCopyChat?: () => Promise<void> | void;
}

const CLOSE_DELAY_MS = 140;
const MAX_TITLE_LENGTH = 120;

const isEditableTarget = (target: EventTarget | null): boolean => {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return Boolean(
    target.closest(
      'input, textarea, select, [contenteditable="true"], [role="textbox"]',
    ),
  );
};

const getErrorMessage = (
  error: unknown,
  fallback = 'Karen could not complete that action.',
): string => {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  if (typeof error === 'string' && error.trim()) {
    return error.trim();
  }

  return fallback;
};

export function ChatActionsMenu({
  currentSession,
  isLoadingSessions,
  createNewSession,
  refreshSessions,
  updateSessionTitle,
  deleteSession,
  onOpenHistory,
  onExportChat,
  onCopyChat,
}: ChatActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const [supportsHover, setSupportsHover] = useState(false);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isActionBusy, setIsActionBusy] = useState(false);

  const closeTimerRef = useRef<number | null>(null);

  const activeTitle = useMemo(() => {
    return currentSession?.title?.trim() || 'No active chat';
  }, [currentSession?.title]);

  const canUseSessionActions = Boolean(currentSession) && !isLoadingSessions;
  const canRunAction = !isLoadingSessions && !isActionBusy;
  const canUseCurrentChatActions = canUseSessionActions && canRunAction;
  const hasActionDialogOpen = renameOpen || deleteOpen;

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }

    const media = window.matchMedia('(hover: hover) and (pointer: fine)');

    const apply = (matches: boolean) => setSupportsHover(matches);
    apply(media.matches);

    const handler = (event: MediaQueryListEvent) => apply(event.matches);

    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', handler);
      return () => media.removeEventListener('change', handler);
    }

    media.addListener(handler);
    return () => media.removeListener(handler);
  }, []);

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current !== null && typeof window !== 'undefined') {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => clearCloseTimer();
  }, [clearCloseTimer]);

  const closeMenu = useCallback(() => {
    clearCloseTimer();
    setOpen(false);
  }, [clearCloseTimer]);

  const handlePointerEnter = useCallback(() => {
    if (!supportsHover || hasActionDialogOpen) {
      return;
    }

    clearCloseTimer();
    setOpen(true);
  }, [supportsHover, hasActionDialogOpen, clearCloseTimer]);

  const handlePointerLeave = useCallback(() => {
    if (!supportsHover || hasActionDialogOpen || typeof window === 'undefined') {
      return;
    }

    clearCloseTimer();

    closeTimerRef.current = window.setTimeout(() => {
      setOpen(false);
    }, CLOSE_DELAY_MS);
  }, [supportsHover, hasActionDialogOpen, clearCloseTimer]);

  const runAction = useCallback(
    async (
      action: () => Promise<void> | void,
      errorTitle: string,
      fallbackMessage?: string,
    ) => {
      if (isActionBusy) {
        return;
      }

      setIsActionBusy(true);

      try {
        await action();
      } catch (error) {
        toast({
          title: errorTitle,
          description: getErrorMessage(error, fallbackMessage),
          variant: 'destructive',
        });
      } finally {
        setIsActionBusy(false);
      }
    },
    [isActionBusy],
  );

  const handleNewChat = useCallback(async () => {
    if (!canRunAction) {
      return;
    }

    await runAction(
      async () => {
        await createNewSession();
        closeMenu();
      },
      'Unable to start new chat',
      'Karen could not create a new conversation.',
    );
  }, [canRunAction, closeMenu, createNewSession, runAction]);

  const handleRefresh = useCallback(async () => {
    if (!canRunAction) {
      return;
    }

    await runAction(
      async () => {
        await refreshSessions();
        closeMenu();
      },
      'Unable to refresh history',
      'Karen could not refresh chat history.',
    );
  }, [canRunAction, closeMenu, refreshSessions, runAction]);

  const handleOpenHistory = useCallback(() => {
    closeMenu();
    onOpenHistory();
  }, [closeMenu, onOpenHistory]);

  const handleStartRename = useCallback(() => {
    if (!currentSession || !canUseCurrentChatActions) {
      return;
    }

    setRenameValue(currentSession.title || '');
    setRenameOpen(true);
    closeMenu();
  }, [canUseCurrentChatActions, closeMenu, currentSession]);

  const handleRenameOpenChange = useCallback((nextOpen: boolean) => {
    setRenameOpen(nextOpen);

    if (!nextOpen) {
      setRenameValue('');
    }
  }, []);

  const handleRenameSave = useCallback(async () => {
    if (!currentSession || isActionBusy) {
      return;
    }

    const nextTitle = renameValue.trim();

    if (!nextTitle) {
      toast({
        title: 'Name required',
        description: 'Please enter a chat title before saving.',
        variant: 'destructive',
      });
      return;
    }

    const currentTitle = currentSession.title?.trim() || '';

    if (nextTitle === currentTitle) {
      setRenameOpen(false);
      setRenameValue('');
      return;
    }

    await runAction(
      async () => {
        const success = await updateSessionTitle(currentSession.id, nextTitle);

        if (success) {
          toast({
            title: 'Chat renamed',
            description: `Session renamed to "${nextTitle}".`,
          });

          setRenameOpen(false);
          setRenameValue('');
        }
      },
      'Unable to rename chat',
      'Karen could not rename that conversation.',
    );
  }, [
    currentSession,
    isActionBusy,
    renameValue,
    runAction,
    updateSessionTitle,
  ]);

  const handleDeleteConfirm = useCallback(async () => {
    if (!currentSession || isActionBusy) {
      return;
    }

    await runAction(
      async () => {
        const success = await deleteSession(currentSession.id);

        if (success) {
          toast({
            title: 'Chat deleted',
            description: 'The current chat was deleted.',
          });

          setDeleteOpen(false);
        }
      },
      'Unable to delete chat',
      'Karen could not delete that conversation.',
    );
  }, [currentSession, deleteSession, isActionBusy, runAction]);

  const handleExport = useCallback(async () => {
    if (!onExportChat || !canUseCurrentChatActions) {
      return;
    }

    await runAction(
      async () => {
        await onExportChat();
        closeMenu();
      },
      'Unable to export chat',
      'Karen could not export the current conversation.',
    );
  }, [canUseCurrentChatActions, closeMenu, onExportChat, runAction]);

  const handleCopyChat = useCallback(async () => {
    if (!onCopyChat || !canUseCurrentChatActions) {
      return;
    }

    await runAction(
      async () => {
        await onCopyChat();
        closeMenu();
      },
      'Unable to copy chat',
      'Karen could not copy the current conversation.',
    );
  }, [canUseCurrentChatActions, closeMenu, onCopyChat, runAction]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        open ||
        hasActionDialogOpen ||
        isEditableTarget(event.target) ||
        event.defaultPrevented
      ) {
        return;
      }

      const key = event.key.toLowerCase();
      const isCtrlOrCmd = event.ctrlKey || event.metaKey;

      if (event.key === 'F2') {
        event.preventDefault();
        handleStartRename();
        return;
      }

      if (isCtrlOrCmd) {
        switch (key) {
          case 'n':
            event.preventDefault();
            void handleNewChat();
            return;

          case 'r':
            event.preventDefault();
            void handleRefresh();
            return;

          case 'h':
            event.preventDefault();
            handleOpenHistory();
            return;

          default:
            break;
        }
      }

      if (event.altKey) {
        switch (key) {
          case 'c':
            event.preventDefault();
            void handleCopyChat();
            return;

          case 'e':
            event.preventDefault();
            void handleExport();
            return;

          default:
            break;
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [
    open,
    hasActionDialogOpen,
    handleNewChat,
    handleRefresh,
    handleOpenHistory,
    handleStartRename,
    handleCopyChat,
    handleExport,
  ]);

  return (
    <>
      <div
        className="inline-flex"
        onMouseEnter={handlePointerEnter}
        onMouseLeave={handlePointerLeave}
      >
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="flex h-9 items-center gap-2 border border-input bg-background px-3 hover:bg-accent hover:text-accent-foreground"
              aria-label="Chat actions"
              aria-haspopup="menu"
              aria-expanded={open}
            >
              <MessageSquare className="h-4 w-4" />
              <span>CHAT</span>
              <ChevronDown className="h-4 w-4 opacity-70" />
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="start" sideOffset={8} className="w-60">
            <DropdownMenuLabel>Chat Actions</DropdownMenuLabel>

            <div
              className="truncate px-2 pb-2 text-xs text-muted-foreground"
              title={activeTitle}
            >
              {activeTitle}
            </div>

            <DropdownMenuSeparator />

            <DropdownMenuGroup>
              <DropdownMenuItem
                disabled={!canRunAction}
                onClick={() => void handleNewChat()}
              >
                <Plus className="mr-2 h-4 w-4" />
                <span>New Chat</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Ctrl+N
                </span>
              </DropdownMenuItem>

              <DropdownMenuItem onClick={handleOpenHistory}>
                <History className="mr-2 h-4 w-4" />
                <span>History</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Ctrl+H
                </span>
              </DropdownMenuItem>

              <DropdownMenuItem
                disabled={!canRunAction}
                onClick={() => void handleRefresh()}
              >
                <RefreshCw
                  className={`mr-2 h-4 w-4 ${isLoadingSessions ? 'animate-spin' : ''}`}
                />
                <span>Refresh</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Ctrl+R
                </span>
              </DropdownMenuItem>
            </DropdownMenuGroup>

            <DropdownMenuSeparator />

            <DropdownMenuGroup>
              <DropdownMenuItem
                disabled={!canUseCurrentChatActions}
                onClick={handleStartRename}
              >
                <Pencil className="mr-2 h-4 w-4" />
                <span>Rename Chat</span>
                <span className="ml-auto text-xs text-muted-foreground">F2</span>
              </DropdownMenuItem>

              <DropdownMenuItem
                disabled={!canUseCurrentChatActions || !onCopyChat}
                onClick={() => void handleCopyChat()}
              >
                <Copy className="mr-2 h-4 w-4" />
                <span>Copy Chat</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Alt+C
                </span>
              </DropdownMenuItem>

              <DropdownMenuItem
                disabled={!canUseCurrentChatActions || !onExportChat}
                onClick={() => void handleExport()}
              >
                <Download className="mr-2 h-4 w-4" />
                <span>Export Chat</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  Alt+E
                </span>
              </DropdownMenuItem>

              <DropdownMenuItem
                disabled={!canUseCurrentChatActions}
                onClick={() => {
                  setDeleteOpen(true);
                  closeMenu();
                }}
                className="text-destructive focus:text-destructive"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                <span>Delete Chat</span>
              </DropdownMenuItem>
            </DropdownMenuGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <Dialog open={renameOpen} onOpenChange={handleRenameOpenChange}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Rename Chat</DialogTitle>
            <DialogDescription>
              Update the title for the current conversation.
            </DialogDescription>
          </DialogHeader>

          <Input
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void handleRenameSave();
              }

              if (event.key === 'Escape') {
                event.preventDefault();
                handleRenameOpenChange(false);
              }
            }}
            placeholder="Enter chat title"
            maxLength={MAX_TITLE_LENGTH}
            autoFocus
            aria-label="Chat title"
          />

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleRenameOpenChange(false)}
              disabled={isActionBusy}
            >
              Cancel
            </Button>

            <Button
              type="button"
              onClick={() => void handleRenameSave()}
              disabled={isActionBusy || !renameValue.trim()}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Current Chat?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the current conversation and its messages.
              This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isActionBusy}>Cancel</AlertDialogCancel>

            <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90"
              onClick={(event) => {
                event.preventDefault();
                void handleDeleteConfirm();
              }}
              disabled={isActionBusy}
            >
              Delete Chat
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </>
  );
}