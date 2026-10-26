import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

import {
  readKarenOwnedThreadMessages,
  type KarenVerifiedPrincipal,
} from "./owned-thread-history";

const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RUN_ID = /^[A-Za-z0-9_-]{1,100}$/;
const MAX_CONNECT_BYTES = 512 * 1024;

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
    const reader = request.clone().body?.getReader();
    if (!reader) return refuse("Malformed thread connection request", 400);
    const decoder = new TextDecoder("utf-8", { fatal: true });
    let body = "";
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_CONNECT_BYTES) {
        // request.clone() creates a tee. Waiting for cancellation of only
        // one branch can deadlock when the original remains unread.
        void reader.cancel().catch(() => undefined);
        return refuse("Thread connection request too large", 413);
      }
      body += decoder.decode(value, { stream: true });
    }
    body += decoder.decode();
    input = JSON.parse(body);
  } catch {
    return refuse("Malformed thread connection request", 400);
  }
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return refuse("Invalid thread connection request", 422);
  }
  const values = input as Record<string, unknown>;
  // CopilotKit v2 calls connect() using RunAgentInput. The protocol adds
  // client-side messages and hints, but none can authorize server operations.
  // Ignore that transcript entirely; replay comes only from owned history.
  const allowed = new Set([
    "threadId", "runId", "messages", "state", "tools",
    "context", "forwardedProps",
  ]);
  const isEmptyRecord = (value: unknown) =>
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === 0;
  const allowArray = (value: unknown) => Array.isArray(value) && value.length === 0;
  const hints = values.forwardedProps;
  const hintsRecord =
    hints && typeof hints === "object" && !Array.isArray(hints)
      ? hints as Record<string, unknown> : null;
  const provider = hintsRecord?.preferred_llm_provider;
  const model = hintsRecord?.preferred_model;
  const hintsValid = hints === undefined || (
    hintsRecord !== null &&
    Object.keys(hintsRecord).every((key) =>
      key === "preferred_llm_provider" || key === "preferred_model") &&
    (provider === undefined && model === undefined || (
      typeof provider === "string" && provider.trim().length > 0 &&
      provider.length <= 100 && typeof model === "string" &&
      model.trim().length > 0 && model.length <= 200
    ))
  );
  if (
    Object.keys(values).some((key) => !allowed.has(key)) ||
    typeof values.threadId !== "string" ||
    !CONVERSATION_UUID.test(values.threadId) ||
    (values.runId !== undefined &&
      (typeof values.runId !== "string" || !RUN_ID.test(values.runId))) ||
    (values.messages !== undefined &&
      (!Array.isArray(values.messages) || values.messages.length > 500)) ||
    (values.tools !== undefined && !allowArray(values.tools)) ||
    (values.context !== undefined && !allowArray(values.context)) ||
    (values.state !== undefined && !isEmptyRecord(values.state)) ||
    !hintsValid
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
  governedHistory = false,
): Promise<Response> {
  const stored = await readKarenOwnedThreadMessages(
    request, backendBaseUrl, headers, principal, threadId, governedHistory,
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
  if (snapshot.threadId !== threadId || !Array.isArray(snapshot.messages) ||
      (governedHistory && !Array.isArray(snapshot.replayEvents))) {
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
    ...(governedHistory ? (snapshot.replayEvents as Record<string, unknown>[]) : []),
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
