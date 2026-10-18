import { ScrollArea } from '@/components/ui/scroll-area';
import type { SuggestedAction } from '@/lib/agent-ui/service';
import type { ChatMessage } from '@/lib/types';
import { MessageBubble } from '../MessageBubble';

interface MessagesAreaProps {
  messages: ChatMessage[];
  onActionClick: (action: SuggestedAction) => void;
  viewportRef: React.RefObject<HTMLDivElement>;
  messagesContainerRef: React.RefObject<HTMLDivElement>;
  showWelcome?: boolean;
  onPromptSelect?: (prompt: string) => void;
}

export function MessagesArea({
  messages,
  onActionClick,
  viewportRef,
  messagesContainerRef,
  showWelcome = false,
  onPromptSelect,
}: MessagesAreaProps) {
  return (
    <ScrollArea
      className="flex-1 p-4 md:p-6"
      viewportRef={viewportRef}
    >
      {/*
       * The viewport ref belongs to ScrollArea; the container ref belongs to the
       * message stack. scrollManagement uses both so streaming content can stay
       * pinned only when the user has not intentionally scrolled away.
       */}
      <div
        ref={messagesContainerRef}
        className="w-full space-y-1 pb-4"
        role="log"
        aria-label="Chat messages"
        aria-live="polite"
        aria-relevant="additions text"
      >
        {showWelcome && messages.length === 0 && onPromptSelect && (
          <section
            data-testid="chat-welcome"
            aria-label="Get started with Karen"
            className="mx-auto flex w-full max-w-2xl flex-col items-center gap-5 px-3 py-10 text-center sm:py-16"
          >
            <div className="space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                What can Karen help you accomplish?
              </h1>
              <p className="mx-auto max-w-xl text-sm leading-relaxed text-muted-foreground sm:text-base">
                Explore an idea, write something useful, or plan your next step.
                Choose an example to edit in the message box, or ask your own question.
              </p>
            </div>
            <div className="grid w-full gap-3 sm:grid-cols-2">
              {[
                { label: 'Make a plan', prompt: 'Help me make a practical plan for a project I want to start.' },
                { label: 'Write and improve', prompt: 'Help me write a clear, professional message.' },
                { label: 'Understand a topic', prompt: 'Explain a complicated topic in plain language, with examples.' },
                { label: 'Think through a decision', prompt: 'Help me compare options and decide what to do next.' },
              ].map((suggestion) => (
                <button
                  key={suggestion.label}
                  type="button"
                  className="rounded-xl border border-border/70 bg-card/60 px-4 py-4 text-left text-sm font-medium transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => onPromptSelect(suggestion.prompt)}
                >
                  {suggestion.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Examples fill your message box. Nothing is sent until you choose Send.
            </p>
          </section>
        )}
        {messages.map((message) => (
          <MessageBubble
            key={message.id}
            message={message}
            onActionClick={onActionClick}
          />
        ))}
      </div>
    </ScrollArea>
  );
}
