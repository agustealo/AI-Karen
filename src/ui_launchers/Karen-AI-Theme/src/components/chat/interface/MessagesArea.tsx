import { ScrollArea } from '@/components/ui/scroll-area';
import type { SuggestedAction } from '@/lib/agent-ui/service';
import type { ChatMessage } from '@/lib/types';
import { MessageBubble } from '../MessageBubble';

interface MessagesAreaProps {
  messages: ChatMessage[];
  onActionClick: (action: SuggestedAction) => void;
  viewportRef: React.RefObject<HTMLDivElement>;
  messagesContainerRef: React.RefObject<HTMLDivElement>;
}

export function MessagesArea({
  messages,
  onActionClick,
  viewportRef,
  messagesContainerRef,
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
