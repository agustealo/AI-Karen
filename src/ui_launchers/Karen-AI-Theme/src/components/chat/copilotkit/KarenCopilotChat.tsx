"use client";

import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import { useAuth } from "@/lib/useAuth";
import { KarenCopilotHistoryGate } from "./KarenCopilotHistoryGate";
import { KarenCopilotControlledChat } from "./KarenCopilotControlledChat";
import { KarenCopilotVerifiedRail } from "./KarenCopilotVerifiedRail";
import { KarenPersonaSelector } from "../KarenPersonaSelector";

const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * CopilotKit v2 compatibility entry point. This component is deliberately
 * NOT mounted until the authenticated runtime gateway, server-owned thread
 * history and feature-parity tests have been completed.
 *
 * The dashboard retains the current assistant-ui implementation for now.
 * The isolated acceptance-only route may mount this candidate if its server-
 * side exact-host gate is explicitly enabled; it is not a consumer cutover.
 * The high-level CopilotChat starts inference on first mount, so this shell
 * uses the native controlled CopilotChatView with explicit submit-only runs.
 * Consumer cutover still requires exact-revision browser and UX acceptance.
 */
export interface KarenCopilotChatProps {
  /** Canonical persisted conversation ID, obtained through SessionProvider. */
  conversationId: string;
  /** Optional user preference from Karen's backend-owned model catalog. */
  preferredProvider?: string | null;
  preferredModel?: string | null;
  onBusyChange?: (busy: boolean) => void;
}

export function KarenCopilotChat({
  conversationId,
  preferredProvider = null,
  preferredModel = null,
  onBusyChange,
}: KarenCopilotChatProps) {
  const { user, isAuthenticated, isLoading } = useAuth();
  if (isLoading || !isAuthenticated || !user ||
      typeof user.user_id !== "string" || !user.user_id.trim() ||
      typeof user.tenant_id !== "string" || !user.tenant_id.trim()) {
    // Never retain another account's provider, agent, draft, or voice state.
    return <p role="status" className="text-sm text-muted-foreground">
      Authenticated conversation unavailable.
    </p>;
  }
  if (!CONVERSATION_UUID.test(conversationId)) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Karen could not verify the conversation identity.
      </p>
    );
  }

  // Only a paired, bounded preference is forwarded. It is never a model
  // execution decision; ChatRuntime validates eligibility and reports actual
  // provider/model in its execution receipt.
  if ((preferredProvider === null) !== (preferredModel === null) ||
      (preferredProvider !== null && (!preferredProvider.trim() || preferredProvider.length > 100)) ||
      (preferredModel !== null && (!preferredModel.trim() || preferredModel.length > 200))) {
    return (
      <p role="alert" className="text-sm text-destructive">
        Karen could not validate the requested model.
      </p>
    );
  }
  const properties = preferredProvider !== null && preferredModel !== null
    ? {
        preferred_llm_provider: preferredProvider.trim(),
        preferred_model: preferredModel.trim(),
      }
    : undefined;

  const scopeKey = [user.tenant_id, user.user_id, conversationId].join(":");
  return (
    <section
      aria-label="Karen CopilotKit conversation"
      className="flex min-h-0 min-w-0 flex-1 flex-col bg-background text-foreground"
    >
      <CopilotKitProvider key={scopeKey} runtimeUrl="/api/copilotkit" agentId="default" properties={properties}>
        <KarenCopilotHistoryGate conversationId={conversationId}>
          <div className="flex min-h-0 min-w-0 flex-1">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              <KarenCopilotControlledChat key={conversationId} conversationId={conversationId} onBusyChange={onBusyChange} />
              <div data-testid="karen-copilot-persona-footer"
                className="sticky bottom-0 z-10 shrink-0 border-t border-border/60 bg-background/95 px-4 py-3 backdrop-blur">
                <KarenPersonaSelector />
              </div>
            </div>
            <KarenCopilotVerifiedRail />
          </div>
        </KarenCopilotHistoryGate>
      </CopilotKitProvider>
    </section>
  );
}
