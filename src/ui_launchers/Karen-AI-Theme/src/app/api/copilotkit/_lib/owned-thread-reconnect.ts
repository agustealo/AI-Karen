import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

import {
  readKarenOwnedThreadMessages,
  type KarenVerifiedPrincipal,
} from "./owned-thread-history";

const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;
const MAX_CONNECT_BYTES = 16 * 1024;

function refuse(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
}

/** Validate SDK reconnect input; it can never supply authority or tools. */
export async function readKarenConnectThreadId(
  request: NextRequest,
): Promise<string | NextResponse> {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return refuse("Expected JSON thread connection", 415);
  }
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_CONNECT_BYTES)) {
    return refuse("Thread connection request too large", 413);
  }
  let input: unknown;
  try {
    const raw = await request.clone().text();
    if (new TextEncoder().encode(raw).byteLength > MAX_CONNECT_BYTES) {
      return refuse("Thread connection request too large", 413);
    }
    input = JSON.parse(raw);
  } catch {
    return refuse("Malformed thread connection request", 400);
  }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return refuse("Invalid thread connection request", 422);
  }
  const values = input as Record<string, unknown>;
  if (
    Object.keys(values).some((key) => key !== "threadId" && key !== "runId") ||
    typeof values.threadId !== "string" ||
    !CONVERSATION_UUID.test(values.threadId) ||
    (values.runId !== undefined &&
      (typeof values.runId !== "string" || !RUN_ID.test(values.runId)))
  ) {
    return refuse("Unsupported thread connection fields", 422);
  }
  return values.threadId;
}

/**
 * Restore only canonical, completed plaintext history.
 *
 * RUN_STARTED/FINISHED delimit a synthetic *history playback stream*, never
 * a provider invocation. Metadata explicitly identifies the response source.
 * This does not reattach to an in-progress model run or execute new work.
 */
export async function connectKarenOwnedThread(
  request: NextRequest,
  backendBaseUrl: string,
  headers: Record<string, string>,
  principal: KarenVerifiedPrincipal,
  threadId: string,
): Promise<Response> {
  const stored = await readKarenOwnedThreadMessages(
    request, backendBaseUrl, headers, principal, threadId,
  );
  if (!stored.ok) return stored;

  let body: unknown;
  try {
    body = await stored.json();
  } catch {
    return refuse("Canonical history replay failed", 502);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return refuse("Canonical history replay failed", 502);
  }
  const snapshot = body as Record<string, unknown>;
  if (snapshot.threadId !== threadId || !Array.isArray(snapshot.messages)) {
    return refuse("Canonical history replay failed", 502);
  }

  const runId = "history_" + randomUUID();
  const source = "persisted_history";
  const events = [
    {
      type: "RUN_STARTED",
      threadId,
      runId,
      metadata: { response_source: source, replay_only: true },
    },
    {
      type: "MESSAGES_SNAPSHOT",
      messages: snapshot.messages,
    },
    {
      type: "RUN_FINISHED",
      threadId,
      runId,
      metadata: { response_source: source, replay_only: true },
    },
  ];
  const stream = new TextEncoder().encode(
    events.map((event) => "data: " + JSON.stringify(event) + "\n\n").join(""),
  );
  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Karen-Response-Source": source,
      "X-Accel-Buffering": "no",
    },
  });
}
