"use client";

/**
 * Isolate optional, evidence-bound cards from the canonical conversation UI.
 * This is rendering containment only: it grants no evidence, replay or action
 * permission and never fabricates missing presentation data.
 */
import { AgentErrorBoundary } from "@/components/agent-ui/AgentErrorBoundary";
import { KarenPresentationRegistry } from "./KarenPresentationRegistry";

export function KarenSafePresentation({ data }: { data: unknown }) {
  return (
    <AgentErrorBoundary
      fallback={
        <p role="status" data-testid="karen-presentation-render-error"
          className="my-2 rounded-lg border border-border/60 px-3 py-2 text-xs text-muted-foreground">
          This card could not be displayed. The conversation text remains available.
        </p>
      }
    >
      <KarenPresentationRegistry data={data} />
    </AgentErrorBoundary>
  );
}
