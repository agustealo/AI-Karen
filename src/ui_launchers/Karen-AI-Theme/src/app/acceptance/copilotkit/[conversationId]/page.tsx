import type { Metadata } from "next";
import { AuthWrapper } from "@/components/AuthWrapper";
import { KarenCopilotChat } from "@/components/chat/copilotkit/KarenCopilotChat";
import { requireApprovedCopilotKitPreview } from "../_lib/preview-gate";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

/**
 * Standalone native SDK acceptance, gated by the shared server-only host rule.
 * Never mounts on the regular dashboard and never implies consumer cutover.
 */
export default async function CopilotKitAcceptancePage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  await requireApprovedCopilotKitPreview(conversationId);

  return (
    <AuthWrapper>
      <main data-testid="karen-copilot-acceptance-preview"
        className="flex h-dvh min-h-0 flex-col bg-background text-foreground">
        <header className="shrink-0 border-b border-border/60 p-3 text-sm">
          CopilotKit candidate preview. Acceptance environment only.
        </header>
        <KarenCopilotChat conversationId={conversationId} />
      </main>
    </AuthWrapper>
  );
}
