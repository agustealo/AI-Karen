import { NextRequest, NextResponse } from "next/server";

const MAX_STOP_BYTES = 4096;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;

/**
 * Only an exact runId can be stopped. The SDK's thread-only stop behavior is
 * deliberately denied: a threadId is never a capability or a unique run.
 */
export async function readKarenScopedStopRunId(
  request: NextRequest,
): Promise<string | NextResponse> {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_STOP_BYTES)) {
    return NextResponse.json({ detail: "Stop request too large" }, { status: 413 });
  }
  let input: unknown;
  try {
    const reader = request.clone().body?.getReader();
    if (!reader) throw new Error("Missing request");
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let bytes = 0;
    let body = "";
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > MAX_STOP_BYTES) {
        // A cloned NextRequest body uses a tee. Awaiting reader.cancel()
        // may wait for the original, unconsumed branch and deadlock the
        // request. Reject immediately; cancellation is best-effort only.
        void reader.cancel().catch(() => undefined);
        return NextResponse.json({ detail: "Stop request too large" }, { status: 413 });
      }
      body += decoder.decode(part.value, { stream: true });
    }
    body += decoder.decode();
    input = JSON.parse(body);
  } catch {
    return NextResponse.json({ detail: "Malformed stop request" }, { status: 400 });
  }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return NextResponse.json({ detail: "Invalid stop request" }, { status: 422 });
  }
  const values = input as Record<string, unknown>;
  if (
    Object.keys(values).length !== 1 ||
    typeof values.runId !== "string" ||
    !RUN_ID.test(values.runId)
  ) {
    return NextResponse.json({
      detail: "A specific runId is required to cancel a run",
    }, { status: 422 });
  }
  return values.runId;
}


/** Shared bounded parser for trusted backend run receipts and read-only status.
 * Never buffer arbitrary upstream JSON, follow redirects or expose raw errors.
 */
async function readBoundedRunJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("missing receipt");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let bytes = 0;
  let body = "";
  while (true) {
    const part = await reader.read();
    if (part.done) break;
    bytes += part.value.byteLength;
    if (bytes > MAX_STOP_BYTES) {
      void reader.cancel().catch(() => undefined);
      throw new Error("oversized receipt");
    }
    body += decoder.decode(part.value, { stream: true });
  }
  body += decoder.decode();
  return JSON.parse(body);
}

/**
 * Canonical FastAPI still enforces user, tenant, thread ownership and RLS.
 * The SDK runner is NOT invoked; it has no Karen chat cancellation authority.
 */
export async function stopKarenOwnedRun(
  request: NextRequest,
  backendBaseUrl: string,
  verifiedHeaders: Record<string, string>,
  threadId: string,
  runId: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(
      backendBaseUrl + "/api/chat/ag-ui/runs/" + threadId + "/" + runId + "/cancel",
      {
        method: "POST",
        headers: verifiedHeaders,
        redirect: "manual",
        cache: "no-store",
        signal: request.signal,
      },
    );
  } catch {
    return NextResponse.json({ detail: "Run cancellation unavailable" }, { status: 503 });
  }
  if (response.status === 404 || response.status === 401 || response.status === 403) {
    return NextResponse.json({ detail: "Chat run unavailable" }, { status: 404 });
  }
  if (response.status === 409) {
    return NextResponse.json({ detail: "Chat run is no longer cancellable" }, { status: 409 });
  }
  if (
    (response.status !== 202 && response.status !== 200) ||
    !response.headers.get("content-type")?.includes("application/json")
  ) {
    return NextResponse.json({ detail: "Run cancellation unavailable" }, { status: 503 });
  }
  let receipt: unknown;
  try {
    receipt = await readBoundedRunJson(response);
  } catch {
    return NextResponse.json({ detail: "Invalid cancellation receipt" }, { status: 503 });
  }
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
    return NextResponse.json({ detail: "Invalid cancellation receipt" }, { status: 503 });
  }
  const state = receipt as Record<string, unknown>;
  if (response.status === 202 && state.status === "cancelling" &&
      state.cancel_requested === true && state.cancellation_confirmed === false) {
    return NextResponse.json(
      { status: "cancelling", cancel_requested: true, cancellation_confirmed: false },
      { status: 202, headers: { "Cache-Control": "private, no-store" } },
    );
  }
  if (response.status === 200 && state.status === "cancelled" &&
      state.cancel_requested === true && state.cancellation_confirmed === true) {
    return NextResponse.json(
      { status: "cancelled", cancel_requested: true, cancellation_confirmed: true },
      { status: 200, headers: { "Cache-Control": "private, no-store" } },
    );
  }
  return NextResponse.json({ detail: "Invalid cancellation receipt" }, { status: 503 });
}

/**
 * Read the canonical owned run state without resending a stop mutation.
 * The server still reauthorizes tenant, user, conversation and run row.
 */
export async function readKarenOwnedRunStatus(
  request: NextRequest,
  backendBaseUrl: string,
  verifiedHeaders: Record<string, string>,
  threadId: string,
  runId: string,
): Promise<Response> {
  if (!RUN_ID.test(runId)) {
    return NextResponse.json({ detail: "Invalid run identity" }, { status: 422 });
  }
  let response: Response;
  try {
    response = await fetch(
      backendBaseUrl + "/api/chat/ag-ui/runs/" + threadId + "/" + runId + "/status",
      {
        method: "GET",
        headers: verifiedHeaders,
        cache: "no-store",
        redirect: "manual",
        signal: request.signal,
      },
    );
  } catch {
    return NextResponse.json({ detail: "Chat run status unavailable" }, { status: 503 });
  }
  if ([401, 403, 404].includes(response.status)) {
    return NextResponse.json({ detail: "Chat run unavailable" }, { status: 404 });
  }
  if (response.status !== 200 ||
      !response.headers.get("content-type")?.includes("application/json")) {
    return NextResponse.json({ detail: "Chat run status unavailable" }, { status: 503 });
  }
  let data: unknown;
  try {
    data = await readBoundedRunJson(response);
  } catch {
    return NextResponse.json({ detail: "Invalid run status receipt" }, { status: 503 });
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return NextResponse.json({ detail: "Invalid run status receipt" }, { status: 503 });
  }
  const record = data as Record<string, unknown>;
  if (!["running", "cancelling", "cancelled", "completed", "failed",
        "orphaned", "interrupted"].includes(String(record.status)) ||
      typeof record.cancel_requested !== "boolean" ||
      typeof record.cancellation_confirmed !== "boolean" ||
      (record.cancellation_confirmed === true &&
        (record.status !== "cancelled" || record.cancel_requested !== true))) {
    return NextResponse.json({ detail: "Invalid run status receipt" }, { status: 503 });
  }
  return NextResponse.json({
    status: record.status,
    cancel_requested: record.cancel_requested,
    cancellation_confirmed: record.cancellation_confirmed,
  }, { status: 200, headers: { "Cache-Control": "private, no-store" } });
}
