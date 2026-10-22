import { fromAgUiMessages } from "@assistant-ui/react-ag-ui";
import type { ThreadMessageLike } from "@assistant-ui/react";
import { presentationFromStructuredContent } from "./KarenPresentationRegistry";

export type DurableHistoryMessage = {
  id?: string;
  role: string;
  content: string;
  structured_content?: Record<string, unknown> | null;
};

/** Restore backend-owned presentation parts without introducing client-side storage. */
export function restoreOwnedHistoryMessages(
  conversationId: string,
  saved: DurableHistoryMessage[],
): ThreadMessageLike[] {
  const eligible = saved.filter((m) =>
    (m.role === "user" || m.role === "assistant") && typeof m.content === "string",
  );
  const converted = eligible.map((m, i) => ({
    id: m.id || `${conversationId}-persisted-${i}`,
    role: m.role as "user" | "assistant",
    content: m.content,
  }));
  const imported = fromAgUiMessages(
    converted as Parameters<typeof fromAgUiMessages>[0],
    { showThinking: false },
  );
  const persistedById = new Map(converted.map((item, index) => [item.id, eligible[index]]));
  return imported.map((message): ThreadMessageLike => {
    const original = message.id ? persistedById.get(message.id) : undefined;
    const envelope = original?.role === "assistant"
      ? presentationFromStructuredContent(original.structured_content) : null;
    if (!envelope) return message;
    return {
      ...message,
      content: [
        ...(typeof message.content === "string"
          ? [{ type: "text" as const, text: message.content }]
          : message.content),
        { type: "data" as const, name: "karen.presentation.v1", data: envelope },
      ],
    };
  });
}

/** The authenticated API response is the only authority for restored history. */
export async function readOwnedConversationHistory(
  conversationId: string,
  fetchConversation: (id: string) => Promise<{ id: string; messages?: DurableHistoryMessage[] | null }>,
): Promise<ThreadMessageLike[]> {
  const conversation = await fetchConversation(conversationId);
  if (conversation.id !== conversationId) {
    throw new Error("Conversation history identity mismatch");
  }
  return restoreOwnedHistoryMessages(conversationId, conversation.messages || []);
}
