import { NextRequest, NextResponse } from "next/server";

import type { KarenVerifiedPrincipal } from "./owned-thread-history";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RUN = /^[A-Za-z0-9_-]{1,100}$/;
const ROUTE = /^\/api\/copilotkit\/threads\/([0-9a-f-]{36})\/runs\/([A-Za-z0-9_-]{1,100})\/events$/i;
const INTEGER = /^(0|[1-9][0-9]*)$/;
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_EVENT_BYTES = 32768;

const REPLAYABLE_TYPES = new Set([
  "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
  "TEXT_MESSAGE_END", "CUSTOM", "RUN_ERROR", "RUN_FINISHED",
]);
const REPLAYABLE_CUSTOM = new Set([
  "karen.presentation.v1", "karen.execution_receipt.v1",
  "karen.response_integrity.v1",
]);
const TERMINAL = new Set(["completed", "failed", "cancelled", "orphaned"]);

function refuse(status: number, detail: string): NextResponse {
  return NextResponse.json({ detail }, {
    status, headers: { "Cache-Control": "private, no-store" },
  });
}

export function ownedRunEventTarget(
  request: NextRequest,
): { threadId: string; runId: string } | null {
  const match = ROUTE.exec(request.nextUrl.pathname);
  return match && UUID.test(match[1]) && RUN.test(match[2])
    ? { threadId: match[1], runId: match[2] } : null;
}

async function boundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("No event history");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let value = "";
  let size = 0;
  for (;;) {
    const next = await reader.read();
    if (next.done) break;
    size += next.value.byteLength;
    if (size > MAX_RESPONSE_BYTES) {
      void reader.cancel().catch(() => undefined);
      throw new Error("Observed history exceeds limit");
    }
    value += decoder.decode(next.value, { stream: true });
  }
  return JSON.parse(value + decoder.decode());
}

/**
 * A separately addressable read-only observation, NOT SDK agent.connect().
 * Never infer a completed assistant message from an unclosed event journal.
 */
export async function readKarenOwnedRunEvents(
  request: NextRequest,
  backendBaseUrl: string,
  headers: Record<string, string>,
  principal: KarenVerifiedPrincipal,
  threadId: string,
  runId: string,
): Promise<Response> {
  const query = request.nextUrl.searchParams;
  if ([...query.keys()].some((key) => key !== "after" && key !== "limit") ||
      query.getAll("after").length > 1 || query.getAll("limit").length > 1) {
    return refuse(422, "Unsupported event cursor parameters");
  }
  const rawAfter = query.get("after") ?? "0";
  const rawLimit = query.get("limit") ?? "50";
  if (!INTEGER.test(rawAfter) || !INTEGER.test(rawLimit) ||
      rawAfter.length > 4 || rawLimit.length > 3) {
    return refuse(422, "Invalid event cursor");
  }
  const after = Number(rawAfter);
  const limit = Number(rawLimit);
  if (after > 2048 || limit < 1 || limit > 100) {
    return refuse(422, "Invalid event cursor");
  }

  let response: Response;
  try {
    response = await fetch(
      backendBaseUrl + "/api/chat/ag-ui/runs/" + threadId + "/" + runId +
        "/events?after=" + after + "&limit=" + limit,
      { method: "GET", headers, cache: "no-store", redirect: "manual",
        signal: request.signal },
    );
  } catch {
    return refuse(503, "Observed event history unavailable");
  }
  if ([401, 403, 404].includes(response.status)) {
    return refuse(404, "Chat run unavailable");
  }
  if (!response.ok ||
      !response.headers.get("content-type")?.includes("application/json")) {
    return refuse(503, "Observed event history unavailable");
  }
  const headerLength = response.headers.get("content-length");
  if (headerLength !== null &&
      (!INTEGER.test(headerLength) ||
       Number(headerLength) > MAX_RESPONSE_BYTES)) {
    return refuse(502, "Oversized observed history");
  }
  let body: unknown;
  try {
    body = await boundedJson(response);
  } catch {
    return refuse(502, "Invalid observed history");
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return refuse(502, "Invalid observed history");
  }
  const data = body as Record<string, unknown>;
  if (data.owner_user_id !== principal.user_id ||
      data.owner_tenant_id !== principal.tenant_id ||
      data.threadId !== threadId || data.runId !== runId) {
    return refuse(404, "Chat run unavailable");
  }
  if (!Array.isArray(data.events) || data.events.length > limit ||
      !Number.isInteger(data.nextCursor) ||
      (data.nextCursor as number) < after ||
      (data.nextCursor as number) > 2048 ||
      typeof data.hasMore !== "boolean" ||
      typeof data.terminalConfirmed !== "boolean" ||
      typeof data.journalTerminalObserved !== "boolean" ||
      data.continuationAvailable !== false ||
      data.responseSource !== "observed_event_journal" ||
      typeof data.runStatus !== "string" ||
      !["running", "cancelling", "completed", "failed", "cancelled",
        "orphaned", "interrupted"].includes(data.runStatus)) {
    return refuse(502, "Invalid observed cursor contract");
  }
  if (data.terminalConfirmed !== TERMINAL.has(data.runStatus) ||
      (data.journalTerminalObserved === true &&
       !data.terminalConfirmed)) {
    return refuse(502, "Contradictory observed run status");
  }
  const events: Array<{ seq: number; event: Record<string, unknown> }> = [];
  let seq = after;
  let observedTerminal = false;
  for (const item of data.events) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return refuse(502, "Invalid observed event");
    }
    const record = item as Record<string, unknown>;
    if (typeof record.seq !== "number" || !Number.isInteger(record.seq) ||
        record.seq !== seq + 1 ||
        !record.event || typeof record.event !== "object" ||
        Array.isArray(record.event)) {
      return refuse(502, "Incomplete observed event sequence");
    }
    const event = record.event as Record<string, unknown>;
    if (typeof event.type !== "string" ||
        !REPLAYABLE_TYPES.has(event.type) ||
        (event.type === "CUSTOM" &&
         (typeof event.name !== "string" || !REPLAYABLE_CUSTOM.has(event.name))) ||
        (event.threadId !== undefined && event.threadId !== threadId) ||
        (event.runId !== undefined && event.runId !== runId)) {
      // Do not silently discard tools, actions, private state, or unsupported UI.
      return refuse(409, "Observed event cannot be faithfully restored");
    }
    const bytes = new TextEncoder().encode(JSON.stringify(event)).byteLength;
    if (bytes > MAX_EVENT_BYTES) {
      return refuse(502, "Oversized observed event");
    }
    if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
      if (!data.terminalConfirmed ||
          (event.type === "RUN_FINISHED" && data.runStatus !== "completed") ||
          (event.type === "RUN_ERROR" && data.runStatus === "completed")) {
        return refuse(502, "Unverified observed terminal");
      }
      observedTerminal = true;
    }
    seq = record.seq;
    events.push({ seq, event });
  }
  if (data.nextCursor !== seq ||
      (data.hasMore && events.length === 0) ||
      (data.journalTerminalObserved && !data.terminalConfirmed)) {
    return refuse(502, "Incomplete observed event page");
  }
  // A terminal could be on another page. Do not synthesize it here.
  return NextResponse.json({
    threadId, runId, events, nextCursor: seq,
    hasMore: data.hasMore, runStatus: data.runStatus,
    terminalConfirmed: data.terminalConfirmed,
    journalTerminalObserved: data.journalTerminalObserved,
    continuationAvailable: false,
    responseSource: "observed_event_journal",
  }, { headers: { "Cache-Control": "private, no-store" } });
}
