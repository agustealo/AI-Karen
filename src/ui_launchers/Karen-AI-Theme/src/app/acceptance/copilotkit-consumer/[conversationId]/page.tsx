import type { Metadata } from "next";

import { AuthWrapper } from "@/components/AuthWrapper";
import { SessionProvider } from "@/components/chat/SessionProvider";
import { KarenCopilotConsumerChat } from "@/components/chat/copilotkit/KarenCopilotConsumerChat";
import { requireApprovedCopilotKitPreview } from "../../copilotkit/_lib/preview-gate";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

/**
 * Consumer navigation and model-catalog acceptance, NOT a dashboard cutover.
 * The owned UUID is resolved by canonical SessionProvider after authentication.
 * The exact-host/feature gate denies unauthorized deployment exposure.
 */
export default async function CopilotKitConsumerAcceptancePage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const { conversationId } = await params;
  await requireApprovedCopilotKitPreview(conversationId);

  return (
    <AuthWrapper>
      <link rel="stylesheet" href="/vendor/copilotkit-v2.css" />
      <main data-testid="karen-copilot-consumer-acceptance"
        className="flex h-dvh min-h-0 flex-col bg-background text-foreground">
        <header className="shrink-0 border-b border-border/60 p-3 text-sm">
          CopilotKit consumer candidate. Acceptance environment only.
        </header>
        <SessionProvider initialSessionId={conversationId}>
          <KarenCopilotConsumerChat />
        </SessionProvider>
      </main>
    </AuthWrapper>
  );
}
