import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";

import { AuthWrapper } from "@/components/AuthWrapper";
import { KarenCopilotChat } from "@/components/chat/copilotkit/KarenCopilotChat";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { robots: { index: false, follow: false } };

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const APPROVED_HOST = /^(?=.{1,253}$)[a-z0-9][a-z0-9.-]*(?::[0-9]{2,5})?$/;

/**
 * Standalone acceptance-only candidate, never the dashboard's consumer mount.
 * Enabled solely by an explicit server-side operator flag AND an exact
 * deployment host. Defaults to 404 and cannot be enabled by query params,
 * cookies, NEXT_PUBLIC_ variables or the browser.
 *
 * AuthWrapper gates the UI; CopilotKitHistoryGate and canonical API enforce
 * conversation ownership and tenant scope before any transcript is shown.
 * Browser proof must use a sanitized account and approved deployment.
 */
export default async function CopilotKitAcceptancePage({
  params,
}: {
  params: Promise<{ conversationId: string }>;
}) {
  const enabled = process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED === "true";
  const allowedHost = process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_HOST ?? "";
  if (!enabled || !APPROVED_HOST.test(allowedHost)) notFound();

  // Never trust forwarded host/proto as a bypass for this acceptance-only page.
  const incomingHost = (await headers()).get("host");
  if (incomingHost !== allowedHost) notFound();

  const { conversationId } = await params;
  if (!UUID.test(conversationId)) notFound();

  return (
    <AuthWrapper>
      <link rel="stylesheet" href="/vendor/copilotkit-v2.css" />
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
