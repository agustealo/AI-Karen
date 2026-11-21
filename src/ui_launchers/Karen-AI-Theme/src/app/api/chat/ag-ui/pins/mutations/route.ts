import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { proxyToBackend } from "../../../../_lib/backend-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * KUI-002D3G: ingress validation and single-shot transport only.
 * The canonical Python runtime owns authentication, flags, source admission,
 * tenant isolation, idempotency, CAS, persistence and committed receipts.
 * Never retry an uncertain POST, follow redirects or fabricate success.
 * No consumer control or mutation feature flag is enabled by this route.
 */
const uuid = z.string().uuid();
const reference = z.object({
  conversation_id: uuid,
  assistant_message_id: uuid,
  presentation_id: z.string().min(1).max(160),
  evidence_ref: z.string().min(1).max(160),
}).strict();

const mutation = z.discriminatedUnion("operation", [
  z.object({
    operation: z.literal("pin"),
    idempotency_key: uuid,
    source: reference,
    position: z.number().int().min(0).max(99).optional(),
  }).strict(),
  z.object({
    operation: z.literal("unpin"),
    idempotency_key: uuid,
    pin_id: uuid,
  }).strict(),
  z.object({
    operation: z.literal("reorder"),
    idempotency_key: uuid,
    pin_id: uuid,
    expected_revision: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER),
    position: z.number().int().min(0).max(99),
  }).strict(),
]);

function rejection(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, {
    status,
    headers: { "cache-control": "private, no-store" },
  });
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (request.nextUrl.search) {
    return rejection("Unsupported pin mutation query", 422);
  }
  const mediaType = request.headers.get("content-type")?.split(";")[0]?.trim().toLowerCase();
  if (mediaType !== "application/json") {
    return rejection("Pin mutation requires application/json", 415);
  }

  // Bound untrusted input at transport ingress. Backend repeats all logical
  // validation, and is the sole authority on mutation execution.
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null && (
    !/^\d+$/.test(declaredLength) || Number(declaredLength) > 4096
  )) {
    return rejection("Pin mutation request too large", 413);
  }

  let raw: string;
  try {
    raw = await request.text();
  } catch {
    return rejection("Unreadable pin mutation body", 400);
  }
  if (new TextEncoder().encode(raw).byteLength > 4096) {
    return rejection("Pin mutation request too large", 413);
  }

  let value: unknown;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    return rejection("Invalid pin mutation JSON", 400);
  }
  const parsed = mutation.safeParse(value);
  if (!parsed.success) {
    return rejection("Invalid pin mutation request", 422);
  }

  // Pass precisely the validated logical request, never a client principal,
  // receipt, session identity, attestation, tenant, or forwarding override.
  const response = await proxyToBackend(
    request,
    "/api/chat/ag-ui/pins/mutations",
    {
      rawBody: JSON.stringify(parsed.data),
      retryAttempts: 1,
      followRedirects: false,
    },
  );
  response.headers.set("cache-control", "private, no-store");
  return response;
}
