"use client";

/**
 * Reuse the canonical conversation intelligence rail at every viewport size.
 * Receipt admission is exclusively handled by verified saved-history parsing.
 * Neither layout projects SDK state into execution claims.
 */
import ConversationContextRail from "@/components/chat/ConversationContextRail";
import { useKarenLatestVerifiedExecution, useKarenLatestVerifiedAgentSteps } from "./KarenCopilotVerifiedHistory";

/** Show the honest absence when the latest saved turn lacks verified steps. */
function ActivityReplayNotice() {
  return (
    <p role="status" data-testid="karen-copilot-activity-replay-unavailable"
      className="border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
      No attested agent steps are available for the latest saved assistant turn. No activity is inferred from SDK state.
    </p>
  );
}

function RailUnavailable({ embedded = false }: { embedded?: boolean }) {
  return (
    <aside aria-label="Conversation intelligence deck"
      data-testid="karen-copilot-rail-unverified"
      className={embedded
        ? "min-h-0 w-full p-3"
        : "hidden h-full min-h-0 w-[21rem] shrink-0 overflow-y-auto border-l border-border/70 bg-background/45 p-4 xl:block 2xl:w-[22rem]"}>
      <h2 className="text-sm font-semibold">Conversation intelligence</h2>
      <p className="mt-3 text-sm text-muted-foreground">
        No backend-verified execution receipt is available for this conversation.
        Runtime details will appear after Karen confirms and saves an execution.
      </p>
    </aside>
  );
}

export function KarenCopilotVerifiedRail() {
  const receipt = useKarenLatestVerifiedExecution();
  const agentSteps = useKarenLatestVerifiedAgentSteps();
  return (
    <>
      <details data-testid="karen-copilot-mobile-intelligence"
        className="order-first w-full shrink-0 border-b border-border/70 bg-background/80 xl:hidden">
        <summary className="flex min-h-11 cursor-pointer items-center px-4 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-ring">
          Conversation intelligence
        </summary>
        <div className="max-h-[min(55dvh,28rem)] min-h-0 overflow-y-auto overscroll-contain border-t border-border/60">
          {receipt
            ? <><ConversationContextRail metadata={receipt} agentSteps={agentSteps} embedded />{agentSteps.length === 0 && <ActivityReplayNotice />}</>
            : <RailUnavailable embedded />}
        </div>
      </details>
      {receipt
        ? <><ConversationContextRail metadata={receipt} agentSteps={agentSteps} />{agentSteps.length === 0 && <ActivityReplayNotice />}</>
        : <RailUnavailable />}
    </>
  );
}
