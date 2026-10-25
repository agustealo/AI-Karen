"use client";

import { CopilotChat, CopilotKitProvider } from "@copilotkit/react-core/v2";

const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * CopilotKit v2 compatibility entry point. This component is deliberately
 * NOT mounted until the authenticated runtime gateway, server-owned thread
 * history and feature-parity tests have been completed.
 *
 * The dashboard retains the current assistant-ui implementation for now.
 * CopilotChat may issue an initial run on mount. That behavior must be
 * suppressed or reconciled with SessionProvider before production cutover.
 */
export function KarenCopilotChat({
  conversationId,
}: {
  conversationId: string;
}) {
  if (!CONVERSATION_UUID.test(conversationId)) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Karen could not verify the conversation identity.
      </p>
    );
  }

  return (
    <section
      aria-label="Karen CopilotKit conversation"
      className="flex min-h-0 min-w-0 flex-1 flex-col bg-background text-foreground"
    >
      <CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="default">
        <CopilotChat
          agentId="default"
          threadId={conversationId}
          labels={{
            chatInputPlaceholder: "Message Karen...",
          }}
        />
      </CopilotKitProvider>
    </section>
  );
}
