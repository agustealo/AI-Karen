import { HttpAgent } from "@ag-ui/client-v1";
import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
} from "@copilotkit/runtime/v2";
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
async function handle(request: NextRequest): Promise<Response> {
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

  // Local-first default. Operators may explicitly opt into SDK metadata telemetry.\n  if (process.env.COPILOTKIT_TELEMETRY_DISABLED === undefined) {\n    process.env.COPILOTKIT_TELEMETRY_DISABLED = "true";\n  }\n\n  const copilot = new CopilotRuntime({
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
