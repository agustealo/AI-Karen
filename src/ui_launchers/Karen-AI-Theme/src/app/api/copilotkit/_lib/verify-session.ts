import { NextRequest, NextResponse } from "next/server";
import { sanitizeBackendCookies } from "../../_lib/backend-cookies";

export type AuthenticatedPrincipal = {
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
  const cookie = sanitizeBackendCookies(request.headers.get("cookie") || "");
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
