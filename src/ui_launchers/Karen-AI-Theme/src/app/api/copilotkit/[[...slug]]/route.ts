import { HttpAgent } from "@ag-ui/client-v1";
import { NextRequest, NextResponse } from "next/server";

import { getBackendBaseUrl } from "../../_lib/backend-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type AuthenticatedPrincipal = {
  user_id: string;
  tenant_id: string;
  is_active: boolean;
};

/**
 * Resolve the current actor through Karen's canonical auth service.
 *
 * Neither CopilotKit state nor a browser x-user-id/x-tenant-id is an authority.
 * This check is repeated for every SDK discovery, run and thread request.
 */
export async function verifyKarenCopilotSession(
  request: NextRequest,
  backendBaseUrl: string,
): Promise<{ principal: AuthenticatedPrincipal; headers: Record<string, string> } | NextResponse> {
  const authorization = request.headers.get("authorization");
  const cookie = request.headers.get("cookie");
  if (!authorization && !cookie) {
    return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  }

  const headers: Record<string, string> = {};
  if (authorization) headers.Authorization = authorization;
  if (cookie) headers.Cookie = cookie;

  let response: Response;
  try {
    response = await fetch(`${backendBaseUrl}/api/auth/me`, {
      method: "GET",
      headers,
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch {
    return NextResponse.json({ detail: "Authentication service unavailable" }, { status: 503 });
  }
  if (response.status === 401 || response.status === 403) {
    return NextResponse.json({ detail: "Authentication required" }, { status: response.status });
  }
  if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
    return NextResponse.json({ detail: "Authentication service unavailable" }, { status: 503 });
  }

  let principal: Partial<AuthenticatedPrincipal>;
  try {
    principal = (await response.json()) as Partial<AuthenticatedPrincipal>;
  } catch {
    return NextResponse.json({ detail: "Invalid authentication response" }, { status: 503 });
  }

  if (
    typeof principal.user_id !== "string" ||
    !principal.user_id ||
    typeof principal.tenant_id !== "string" ||
    !principal.tenant_id ||
    principal.tenant_id === "default" ||
    principal.is_active !== true
  ) {
    return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  }
  return { principal: principal as AuthenticatedPrincipal, headers };
}

/**
 * CopilotKit is an interaction gateway, not Karen's model/tool executor.
 *
 * Every request gets a fresh runtime/agent and a fresh credential projection.
 * Never put authenticated agents in a process-global registry or reuse across
 * users/tenants. The canonical backend performs the final authorization.
 */
const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;
const MAX_RUN_BYTES = 524288;

/** Refuse SDK endpoints without canonical thread authorization or durability. */
export function validateCopilotRoute(request: NextRequest): NextResponse | null {
  const path = request.nextUrl.pathname;
  if (request.method === "GET" && path === "/api/copilotkit/info") return null;
  if (request.method !== "POST" || path !== "/api/copilotkit/agent/default/run") {
    return NextResponse.json({ detail: "CopilotKit route is unavailable" }, { status: 404 });
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return NextResponse.json({ detail: "Expected JSON AG-UI request" }, { status: 415 });
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_RUN_BYTES)) {
    return NextResponse.json({ detail: "AG-UI input is too large" }, { status: 413 });
  }
  return null;
}

/** Transport validation only. Final thread ownership belongs to ChatRuntime. */
async function validateRunEnvelope(request: NextRequest): Promise<NextResponse | null> {
  if (request.method !== "POST") return null;
  let body: string;
  try {
    body = await request.clone().text();
  } catch {
    return NextResponse.json({ detail: "Unreadable AG-UI request" }, { status: 400 });
  }
  if (new TextEncoder().encode(body).length > MAX_RUN_BYTES) {
    return NextResponse.json({ detail: "AG-UI input is too large" }, { status: 413 });
  }
  let data: unknown;
  try {
    data = JSON.parse(body);
  } catch {
    return NextResponse.json({ detail: "Malformed AG-UI request" }, { status: 400 });
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return NextResponse.json({ detail: "Invalid AG-UI envelope" }, { status: 422 });
  }
  const run = data as Record<string, unknown>;
  if (typeof run.threadId !== "string" || !CONVERSATION_UUID.test(run.threadId) ||
      typeof run.runId !== "string" || !RUN_ID.test(run.runId)) {
    return NextResponse.json({ detail: "Invalid AG-UI conversation or run identity" }, { status: 422 });
  }
  if (!Array.isArray(run.messages) || run.messages.length < 1 || run.messages.length > 50 ||
      (run.tools !== undefined && (!Array.isArray(run.tools) || run.tools.length > 0)) ||
      (run.context !== undefined && (!Array.isArray(run.context) || run.context.length > 0)) ||
      (run.state !== undefined && run.state !== null &&
        (typeof run.state !== "object" || Array.isArray(run.state) ||
          Object.keys(run.state as object).length > 0))) {
    return NextResponse.json({ detail: "Unsupported AG-UI input" }, { status: 422 });
  }
  return null;
}

async function handle(request: NextRequest): Promise<Response> {
  const unavailable = validateCopilotRoute(request);
  if (unavailable) return unavailable;
  const rejected = await validateRunEnvelope(request);
  if (rejected) return rejected;
  const backendBaseUrl = getBackendBaseUrl();
  const auth = await verifyKarenCopilotSession(request, backendBaseUrl);
  if (auth instanceof NextResponse) return auth;

  // This SDK agent does not own memory, model routing, policy, or tools.
  const agent = new HttpAgent({
    url: `${backendBaseUrl}/api/chat/ag-ui`,
    headers: auth.headers,
    // Redirects must not replay authenticated transcripts to another origin.
    fetch: (url, init) => fetch(url, { ...init, redirect: "manual", cache: "no-store" }),
  });

  // Local-first default. Operators may explicitly opt into SDK metadata telemetry.
  if (process.env.COPILOTKIT_TELEMETRY_DISABLED === undefined) {
    process.env.COPILOTKIT_TELEMETRY_DISABLED = "true";
  }

  // Import after the local-first policy is configured. The SDK may initialise
  // its telemetry client on module load, before a runtime instance exists.
  const { CopilotRuntime, createCopilotRuntimeHandler } =
    await import("@copilotkit/runtime/v2");

  const copilot = new CopilotRuntime({
    agents: { default: agent },
    // The only credential-bearing headers are the current request's
    // server-verified headers above. Do not forward arbitrary x-* claims.
    forwardHeaders: { allow: ["content-type"] },
  });
  const handler = createCopilotRuntimeHandler({
    runtime: copilot,
    basePath: "/api/copilotkit",
  });

  return handler(request);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
