import { headers } from "next/headers";
import { notFound } from "next/navigation";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const APPROVED_HOST = /^(?=.{1,253}$)[a-z0-9][a-z0-9.-]*(?::[0-9]{2,5})?$/;

/**
 * Shared server-only gate for isolated CopilotKit acceptance surfaces.
 * An env opt-in AND the exact incoming host are mandatory; browser-supplied
 * forwarded host, query parameters and public variables never grant access.
 */
export async function requireApprovedCopilotKitPreview(
  conversationId: string,
): Promise<void> {
  const enabled =
    process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED === "true";
  const allowedHost =
    process.env.KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_HOST ?? "";
  if (!enabled || !APPROVED_HOST.test(allowedHost)) notFound();

  const incomingHost = (await headers()).get("host");
  if (incomingHost !== allowedHost || !UUID.test(conversationId)) notFound();
}
