import { FormEvent, KeyboardEvent, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Mic, MicOff, Settings2 } from 'lucide-react';
import { ProviderSettingsModal } from '../const/ProviderSettingsModal';
import { SessionHistory } from '../const/SessionHistory';
import { ChatActionsMenu } from '../const/ChatActionsMenu';
import type { ProviderDetails, Session } from '../types';

interface ChatInputProps {
  // Form handling
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  displayedInputValue: string;
  onInputChange: (value: string) => void;

  // Button states
  isLoading: boolean;
  isAuthLoading: boolean;
  isRecording: boolean;
  isBackendOffline: boolean;
  speechRecognitionSupported: boolean;
  showStopButton: boolean;

  // Streaming status
  streamingStatus: string;

  // Button handlers
  onMicClick: () => void;
  onStopRequest: () => void;

  // Provider settings
  providers: ProviderDetails[];
  selectableProviders: ProviderDetails[];
  selectedProvider: string;
  selectedModel: string;
  applyModelSelection: (providerId: string, modelId: string) => Promise<void>;
  isUpdatingModelSelection: boolean;
  onRefreshModels: () => Promise<void>;

  // Session management
  sessions: Session[];
  currentSession: Session | null;
  isLoadingSessions: boolean;
  error: string | null;
  loadSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<boolean | void>;
  deleteSessions: (sessionIds: string[]) => Promise<boolean>;
  updateSessionTitle: (sessionId: string, newTitle: string) => Promise<boolean>;
  refreshSessions: () => Promise<void>;
  createNewSession: () => Promise<void>;
  onExportChat: () => Promise<void> | void;
  onCopyChat?: () => Promise<void> | void;
}

const DEFAULT_INPUT_PLACEHOLDER = 'Ask Karen anything...';
const AUTH_LOADING_PLACEHOLDER = 'Loading your profile...';
const OFFLINE_PLACEHOLDER = 'Offline mode - limited functionality';

export function ChatInput({
  onSubmit,
  displayedInputValue,
  onInputChange,
  isLoading,
  isAuthLoading,
  isRecording,
  isBackendOffline,
  speechRecognitionSupported,
  showStopButton,
  streamingStatus,
  onMicClick,
  onStopRequest,
  providers,
  selectableProviders,
  selectedProvider,
  selectedModel,
  applyModelSelection,
  isUpdatingModelSelection,
  onRefreshModels,
  sessions,
  currentSession,
  isLoadingSessions,
  error,
  loadSession,
  deleteSession,
  deleteSessions,
  updateSessionTitle,
  refreshSessions,
  createNewSession,
  onExportChat,
  onCopyChat,
}: ChatInputProps) {
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [composerSettingsOpen, setComposerSettingsOpen] = useState(false);

  const trimmedInput = displayedInputValue.trim();

  const inputPlaceholder = useMemo(() => {
    // Placeholder describes the composer, never transient runtime execution.
    if (isAuthLoading) {
      return AUTH_LOADING_PLACEHOLDER;
    }

    if (isBackendOffline) {
      return OFFLINE_PLACEHOLDER;
    }

    return DEFAULT_INPUT_PLACEHOLDER;
  }, [
    isAuthLoading,
    isBackendOffline,
  ]);

  const canUseMic =
    !isLoading && !isAuthLoading && !isBackendOffline && speechRecognitionSupported;

  const canSubmitMessage =
    !isAuthLoading &&
    !isRecording &&
    !isBackendOffline &&
    (isLoading || (Boolean(trimmedInput) && Boolean(selectedProvider) && Boolean(selectedModel)));

  const submitButtonLabel = showStopButton
    ? 'Stop current response generation'
    : 'Send message';

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    onInputChange(event.target.value);
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.defaultPrevented || event.key !== 'Enter' || event.shiftKey ||
        event.altKey || event.ctrlKey || event.metaKey ||
        event.nativeEvent.isComposing || event.keyCode === 229) {
      return;
    }

    // Enter sends; Shift+Enter inserts a newline. During generation we keep
    // the draft editable when allowed but never start a second request.
    event.preventDefault();
    if (!isLoading && canSubmitMessage) {
      event.currentTarget.form?.requestSubmit();
    }
  };

  const handleSubmitButtonClick = () => {
    /*
     * During generation, this button is the request-cancel control.
     * Normal message submission remains owned by the form onSubmit handler.
     */
    if (isLoading) {
      onStopRequest();
    }
  };

  return (
    <div id="chat-input-area" className="shrink-0 border-t border-border/70 bg-background/70 backdrop-blur-xl">
      <div className="chat-input-container mx-auto max-w-5xl px-3 py-3 md:px-5">
        <div className="mb-2 flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="sr-only">
            <select 
              data-testid="chat-provider-select" 
              value={selectedProvider} 
              onChange={(e) => applyModelSelection(e.target.value, 'auto')}
            >
              {selectableProviders.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
            </select>
            <select 
              data-testid="chat-model-select" 
              value={selectedModel} 
              onChange={(e) => applyModelSelection(selectedProvider, e.target.value)}
            >
              {!selectableProviders.find(p => p.id === selectedProvider)?.models.some(m => m.id === 'auto') && (
                <option value="auto">auto</option>
              )}
              {(selectableProviders.find(p => p.id === selectedProvider)?.models || []).map(m => (
                <option key={m.id} value={m.id}>{m.id}</option>
              ))}
            </select>
          </div>
          {/* Provider/session controls live above the input so the active runtime is visible before submit. */}
          <div className="flex flex-wrap gap-2">
            <ProviderSettingsModal
              providers={providers}
              selectableProviders={selectableProviders}
              selectedProvider={selectedProvider}
              selectedModel={selectedModel}
              applyModelSelection={applyModelSelection}
              isUpdatingModelSelection={isUpdatingModelSelection}
              onRefreshModels={onRefreshModels}
            />

            <Button type="button" size="icon" variant="outline"
              aria-label="Composer settings" aria-expanded={composerSettingsOpen}
              onClick={() => setComposerSettingsOpen((open) => !open)}>
              <Settings2 className="h-4 w-4" />
            </Button>
            <ChatActionsMenu
              currentSession={currentSession}
              isLoadingSessions={isLoadingSessions}
              createNewSession={createNewSession}
              refreshSessions={refreshSessions}
              updateSessionTitle={updateSessionTitle}
              deleteSession={deleteSession}
              onOpenHistory={() => setIsHistoryOpen(true)}
              onExportChat={onExportChat}
              onCopyChat={onCopyChat}
            />

            <SessionHistory
              sessions={sessions}
              currentSession={currentSession}
              isLoadingSessions={isLoadingSessions}
              error={error}
              loadSession={loadSession}
              deleteSession={deleteSession}
              deleteSessions={deleteSessions}
              updateSessionTitle={updateSessionTitle}
              refreshSessions={refreshSessions}
              createNewSession={createNewSession}
              open={isHistoryOpen}
              onOpenChange={setIsHistoryOpen}
              hideTrigger
            />
          </div>
        </div>

        {composerSettingsOpen && (
          <section aria-label="Composer capabilities" className="mb-3 rounded-xl border border-border/70 bg-card p-3 text-xs">
            <h3 className="text-sm font-semibold">Conversation controls</h3>
            <p className="mt-1 text-muted-foreground">Provider and model availability come from Karen's runtime. Change them using the model selector.</p>
            <dl className="mt-2 grid gap-2 sm:grid-cols-2">
              <div><dt className="font-medium">Persona</dt><dd className="text-muted-foreground">Managed by Karen's authorized persona runtime; selection appears when available.</dd></div>
              <div><dt className="font-medium">Voice</dt><dd className="text-muted-foreground">{speechRecognitionSupported ? 'Microphone transcription available' : 'Not supported in this browser'}</dd></div>
              <div><dt className="font-medium">Streaming</dt><dd className="text-muted-foreground">{streamingStatus || 'Runtime-managed response delivery'}</dd></div>
              <div><dt className="font-medium">Tools and approvals</dt><dd className="text-muted-foreground">Governed by backend permissions. No client-side auto-approval.</dd></div>
            </dl>
          </section>
        )}
        {isLoading && streamingStatus && (
          <div role="status" aria-live="polite" className="mb-2 text-xs text-muted-foreground" data-testid="chat-processing-status">
            {streamingStatus}
          </div>
        )}

        <form
          onSubmit={onSubmit}
          className="flex w-full items-center gap-2 sm:gap-3"
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={`h-10 w-10 sm:h-11 sm:w-11 ${
              isRecording ? 'animate-pulse text-destructive' : ''
            }`}
            onClick={onMicClick}
            disabled={!canUseMic && !isRecording}
            aria-label={isRecording ? 'Stop voice recording' : 'Start voice recording'}
            aria-pressed={isRecording}
            aria-describedby="mic-help"
          >
            {isRecording ? (
              <MicOff className="h-5 w-5" aria-hidden="true" />
            ) : (
              <Mic className="h-5 w-5" aria-hidden="true" />
            )}
          </Button>

          <Textarea
            rows={2}
            value={displayedInputValue}
            onChange={handleInputChange}
            onKeyDown={handleComposerKeyDown}
            placeholder={inputPlaceholder}
            className="min-h-12 max-h-40 flex-1 resize-y overflow-y-auto border-border/80 bg-card/70 text-sm shadow-inner sm:text-[15px]"
            data-testid="chat-input"
            disabled={isAuthLoading}
            aria-label="Chat message input"
            aria-describedby="input-help"
            aria-invalid={isBackendOffline}
            autoComplete="off"
            spellCheck
            aria-multiline="true"
          />

          <Button
            type={isLoading ? 'button' : 'submit'}
            size="icon"
            onClick={isLoading ? handleSubmitButtonClick : undefined}
            disabled={!canSubmitMessage}
            className={`h-10 w-10 sm:h-11 sm:w-11 ${
              isLoading ? 'bg-destructive hover:bg-destructive/90' : ''
            }`}
            data-testid="chat-submit"
            aria-label={submitButtonLabel}
            aria-describedby="submit-help"
          >
            <span aria-hidden="true" className="text-lg sm:text-xl">
              {showStopButton ? '⏹️' : '🚀'}
            </span>
          </Button>
        </form>
      </div>

      {/* Screen-reader help text stays colocated with the controls that reference it. */}
      <div className="sr-only">
        <div id="mic-help">
          {speechRecognitionSupported
            ? 'Voice input for chat messages'
            : 'Voice input not supported in this browser'}
        </div>

        <div id="input-help">
          Type your message to KAREN. Press Enter to send, Shift+Enter for new
          line.
        </div>

        <div id="submit-help">
          {showStopButton
            ? 'Stop the current AI response generation'
            : 'Send your message to KAREN'}
        </div>
      </div>
    </div>
  );
}
