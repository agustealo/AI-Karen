import { NextRequest, NextResponse } from "next/server";
import { proxyToBackend } from "../../../_lib/backend-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Non-executing authenticated ingress for Karen's canonical presentation-pin
 * readback. Ownership, RLS, completed-run evidence, and release flags remain
 * entirely authoritative in the Python runtime. Never synthesize an empty
 * list, cache response data, or expose a client-owned mutation surface here.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  if (request.nextUrl.search) {
    return NextResponse.json(
      { detail: "Unsupported pin readback query" },
      { status: 422, headers: { "cache-control": "private, no-store" } },
    );
  }

  const response = await proxyToBackend(
    request,
    "/api/chat/ag-ui/pins",
    { retryAttempts: 1, followRedirects: false },
  );
  response.headers.set("cache-control", "private, no-store");
  return response;
}
