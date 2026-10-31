"use client";

/**
 * CopilotKit's right rail is the existing Karen intelligence renderer.
 * Only a backend-verified, persisted execution receipt may populate it.
 * Without one, show an explicit unavailable state rather than mock data.
 */
import ConversationContextRail from "@/components/chat/ConversationContextRail";
import { useKarenLatestVerifiedExecution } from "./KarenCopilotVerifiedHistory";

export function KarenCopilotVerifiedRail() {
  const receipt = useKarenLatestVerifiedExecution();
  if (!receipt) {
    return (
      <aside aria-label="Conversation intelligence deck"
        data-testid="karen-copilot-rail-unverified"
        className="hidden h-full min-h-0 w-[21rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/45 p-4 xl:block 2xl:w-[22rem]">
        <h2 className="text-sm font-semibold">Conversation intelligence</h2>
        <p className="mt-3 text-sm text-muted-foreground">
          No backend-verified execution receipt is available for this conversation.
          Runtime details will appear after Karen confirms and saves an execution.
        </p>
      </aside>
    );
  }
  return <ConversationContextRail metadata={receipt} agentSteps={[]} />;
}
