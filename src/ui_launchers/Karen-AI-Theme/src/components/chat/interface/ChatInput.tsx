import { FormEvent, KeyboardEvent, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Mic, MicOff, Sparkles } from 'lucide-react';
import { ProviderSettingsModal } from '../const/ProviderSettingsModal';
import { SessionHistory } from '../const/SessionHistory';
import { ChatActionsMenu } from '../const/ChatActionsMenu';
import type { ProviderDetails, Session } from '../types';

interface ChatInputProps {
  // Form handling
  onSubmit: (e: FormEvent<HTMLFormElement>) => void;
  displayedInputValue: string;
  onInputChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void;
  onPaste: (e: React.ClipboardEvent<HTMLInputElement>) => void;

  // Button states
  isLoading: boolean;
  isAuthLoading: boolean;
  isRecording: boolean;
  isSuggestingStarter: boolean;
  isEditingDuringProcessing: boolean;
  isBackendOffline: boolean;
  speechRecognitionSupported: boolean;
  showStopButton: boolean;

  // Streaming status
  streamingStatus: string;

  // Button handlers
  onMicClick: () => void;
  onSuggestStarter: () => void;
  onStopRequest: () => void;

  // Provider settings
  providers: ProviderDetails[];
  selectableProviders: ProviderDetails[];
  selectedProvider: string;
  selectedModel: string;
  applyModelSelection: (providerId: string, modelId: string) => Promise<void>;
  isUpdatingModelSelection: boolean;

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
  onShareChat?: () => Promise<void> | void;
  onClearChat?: () => Promise<void> | void;
  onSearchInChat?: () => void;
}

const DEFAULT_INPUT_PLACEHOLDER = 'Ask Karen anything...';
const AUTH_LOADING_PLACEHOLDER = 'Loading your profile...';
const EDIT_DURING_PROCESSING_PLACEHOLDER =
  'Type while Karen is still processing...';
const OFFLINE_PLACEHOLDER = 'Offline mode - limited functionality';

export function ChatInput({
  onSubmit,
  displayedInputValue,
  onInputChange,
  onKeyDown,
  onPaste,
  isLoading,
  isAuthLoading,
  isRecording,
  isSuggestingStarter,
  isEditingDuringProcessing,
  isBackendOffline,
  speechRecognitionSupported,
  showStopButton,
  streamingStatus,
  onMicClick,
  onSuggestStarter,
  onStopRequest,
  providers,
  selectableProviders,
  selectedProvider,
  selectedModel,
  applyModelSelection,
  isUpdatingModelSelection,
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
  onShareChat,
  onClearChat,
  onSearchInChat,
}: ChatInputProps) {
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);

  const trimmedInput = displayedInputValue.trim();

  const inputPlaceholder = useMemo(() => {
    /*
     * Placeholder priority mirrors runtime state:
     * auth loading > editable streaming state > offline warning > live streaming status > normal prompt.
     * This keeps transient streaming status visible without hiding hard blockers.
     */
    if (isAuthLoading) {
      return AUTH_LOADING_PLACEHOLDER;
    }

    if (isLoading && isEditingDuringProcessing) {
      return EDIT_DURING_PROCESSING_PLACEHOLDER;
    }

    if (isBackendOffline) {
      return OFFLINE_PLACEHOLDER;
    }

    return streamingStatus || DEFAULT_INPUT_PLACEHOLDER;
  }, [
    isAuthLoading,
    isLoading,
    isEditingDuringProcessing,
    isBackendOffline,
    streamingStatus,
  ]);

  const canEditInput =
    !isAuthLoading && (!showStopButton || isEditingDuringProcessing);

  const canUseMic =
    !isLoading && !isAuthLoading && !isBackendOffline && speechRecognitionSupported;

  const canSuggestStarter =
    !isLoading && !isSuggestingStarter && !isRecording && !isBackendOffline;

  const canSubmitMessage =
    !isAuthLoading &&
    !isRecording &&
    !isBackendOffline &&
    (isLoading || (Boolean(trimmedInput) && Boolean(selectedProvider) && Boolean(selectedModel)));

  const submitButtonLabel = showStopButton
    ? 'Stop current response generation'
    : 'Send message';

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    /*
     * While Karen is streaming, the parent may allow edit-during-processing.
     * If not enabled, we freeze input edits so the user cannot accidentally
     * mutate the prompt attached to the active request.
     */
    if (!canEditInput) {
      return;
    }

    onInputChange(event.target.value);
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
    <div id="chat-input-area">
      <div className="chat-input-container sticky bottom-0 border-t border-border bg-background/80 p-3 backdrop-blur-sm md:p-4">
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
            />

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
              onShareChat={onShareChat}
              onClearChat={onClearChat}
              onSearchInChat={onSearchInChat}
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

          <div className="flex self-center sm:self-auto">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onSuggestStarter}
              disabled={!canSuggestStarter}
              className="h-9 px-3 text-xs sm:text-sm"
              aria-label={
                isSuggestingStarter
                  ? 'Generating conversation starter suggestion'
                  : 'Generate a conversation starter suggestion'
              }
              aria-describedby="starter-help"
            >
              <Sparkles className="mr-2 h-4 w-4" aria-hidden="true" />
              <span className="hidden sm:inline">
                {isSuggestingStarter ? 'Getting idea...' : 'Need an idea?'}
              </span>
              <span className="sm:hidden">
                {isSuggestingStarter ? 'Idea...' : 'Idea'}
              </span>
            </Button>
          </div>
        </div>

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

          <Input
            type="text"
            value={displayedInputValue}
            onChange={handleInputChange}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            placeholder={inputPlaceholder}
            className="h-10 flex-1 bg-[#292929] text-sm sm:h-11 sm:text-base"
            data-testid="chat-input"
            disabled={isAuthLoading}
            aria-label="Chat message input"
            aria-describedby="input-help"
            aria-invalid={isBackendOffline}
            autoComplete="off"
            spellCheck
            role="textbox"
            aria-multiline="false"
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
        <div id="starter-help">Get a suggested conversation starter from Karen AI</div>

        <div id="mic-help">
          {speechRecognitionSupported
            ? 'Voice input for chat messages'
            : 'Voice input not supported in this browser'}
        </div>

        <div id="input-help">
          Type your message to Karen AI. Press Enter to send, Shift+Enter for new
          line.
        </div>

        <div id="submit-help">
          {showStopButton
            ? 'Stop the current AI response generation'
            : 'Send your message to Karen AI'}
        </div>
      </div>
    </div>
  );
}
