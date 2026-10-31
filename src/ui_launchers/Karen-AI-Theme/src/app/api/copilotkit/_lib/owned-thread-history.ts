import { NextRequest, NextResponse } from "next/server";

export type KarenVerifiedPrincipal = {
  user_id: string;
  tenant_id: string;
  is_active: boolean;
};

const MAX_HISTORY_BYTES = 2 * 1024 * 1024;
const MAX_MESSAGES = 500;
const CONVERSATION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HISTORY_ROUTE =
  /^\/api\/copilotkit\/threads\/([0-9a-f-]{36})\/messages$/i;

export function ownedThreadHistoryId(request: NextRequest): string | null {
  const match = HISTORY_ROUTE.exec(request.nextUrl.pathname);
  return match && CONVERSATION_UUID.test(match[1]) ? match[1] : null;
}

async function readBoundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("Missing canonical response body");
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let length = 0;
  let content = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > MAX_HISTORY_BYTES) {
      await reader.cancel().catch(() => undefined);
      throw new Error("Canonical response exceeds limit");
    }
    content += decoder.decode(value, { stream: true });
  }
  content += decoder.decode();
  return JSON.parse(content);
}

function failure(detail: string, status: number): NextResponse {
  return NextResponse.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });
}

async function readKarenGovernedHistory(
  request: NextRequest,
  baseUrl: string,
  headers: Record<string, string>,
  principal: KarenVerifiedPrincipal,
  threadId: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(
      baseUrl + "/api/chat/ag-ui/threads/" + threadId + "/history",
      { method: "GET", headers, redirect: "manual", cache: "no-store", signal: request.signal },
    );
  } catch {
    return failure("Governed conversation history unavailable", 503);
  }
  if ([401, 403, 404].includes(response.status)) {
    return failure("Conversation unavailable", 404);
  }
  if (response.status === 409) {
    return failure("Complete governed replay is unavailable", 409);
  }
  if (response.status === 502) {
    return failure("Complete governed replay could not be verified", 502);
  }
  if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
    return failure("Governed conversation history unavailable", 503);
  }
  const size = response.headers.get("content-length");
  if (size !== null && (!/^\d+$/.test(size) || Number(size) > MAX_HISTORY_BYTES)) {
    return failure("Governed history exceeds limit", 502);
  }
  let body: unknown;
  try {
    body = await readBoundedJson(response);
  } catch {
    return failure("Invalid governed conversation history", 502);
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return failure("Invalid governed conversation history", 502);
  }
  const data = body as Record<string, unknown>;
  if (data.schema_version !== 1 || data.threadId !== threadId ||
      data.owner_user_id !== principal.user_id ||
      data.owner_tenant_id !== principal.tenant_id) {
    return failure("Conversation unavailable", 404);
  }
  if (!Array.isArray(data.messages) || data.messages.length > MAX_MESSAGES ||
      !Array.isArray(data.replayEvents) || data.replayEvents.length > MAX_MESSAGES * 8 ||
      data.response_source !== "persisted_history" || data.replay_only !== true) {
    return failure("Invalid governed conversation history", 502);
  }
  const allowedRoles = new Set(["user", "assistant"]);
  const messages: Array<{ id: string; role: "user" | "assistant"; content: string }> = [];
  const owners = new Map<string, string>();
  for (const item of data.messages) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return failure("Invalid governed message", 502);
    }
    const m = item as Record<string, unknown>;
    if (Object.keys(m).some((key) => !["id", "role", "content"].includes(key)) ||
        typeof m.id !== "string" || !m.id || m.id.length > 200 ||
        typeof m.role !== "string" || !allowedRoles.has(m.role) ||
        typeof m.content !== "string" || m.content.length > 65536 ||
        owners.has(m.id)) {
      return failure("Invalid governed message", 502);
    }
    owners.set(m.id, m.role);
    messages.push({ id: m.id, role: m.role as "user" | "assistant", content: m.content });
  }
  const replayEvents: Array<Record<string, unknown>> = [];
  for (const entry of data.replayEvents) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      return failure("Invalid governed replay event", 502);
    }
    const e = entry as Record<string, unknown>;
    if (Object.keys(e).some((key) => !["type", "name", "value", "messageId"].includes(key)) ||
        e.type !== "CUSTOM" ||
        !["karen.presentation.v1", "karen.execution_receipt.v1",
          "karen.response_integrity.v1", "karen.agent_step.v1"].includes(String(e.name)) ||
        typeof e.messageId !== "string" || owners.get(e.messageId) !== "assistant" ||
        !e.value || typeof e.value !== "object" || Array.isArray(e.value)) {
      return failure("Invalid governed replay event", 502);
    }
    replayEvents.push({ type: "CUSTOM", name: e.name, value: e.value, messageId: e.messageId });
  }
  return NextResponse.json(
    { threadId, messages, replayEvents },
    { headers: { "Cache-Control": "private, no-store" } },
  );
}


/**
 * Karen conversation repository remains sole owner. CopilotKit receives an
 * ephemeral, bounded projection and never touches its unauthorised thread store.
 */
export async function readKarenOwnedThreadMessages(
  request: NextRequest,
  baseUrl: string,
  headers: Record<string, string>,
  principal: KarenVerifiedPrincipal,
  threadId: string,
  governedHistory = false,
): Promise<Response> {
  if (governedHistory) {
    return readKarenGovernedHistory(request, baseUrl, headers, principal, threadId);
  }
  let response: Response;
  try {
    response = await fetch(baseUrl + "/api/conversations/" + threadId + "?message_limit=" + (MAX_MESSAGES + 1), {
      method: "GET",
      headers,
      redirect: "manual",
      cache: "no-store",
      signal: request.signal,
    });
  } catch {
    return failure("Conversation history unavailable", 503);
  }

  // Do not reveal to a foreign principal whether the thread exists.
  if ([401, 403, 404].includes(response.status)) {
    return failure("Conversation unavailable", 404);
  }
  if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
    return failure("Conversation history unavailable", 503);
  }
  const length = response.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_HISTORY_BYTES)) {
    return failure("Conversation history exceeds limit", 502);
  }
  let snapshot: unknown;
  try {
    snapshot = await readBoundedJson(response);
  } catch {
    return failure("Invalid canonical conversation history", 502);
  }
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    return failure("Invalid canonical conversation history", 502);
  }
  const data = snapshot as Record<string, unknown>;
  // Backend GetOwnedSnapshot is the tenant boundary. Check the returned user
  // and UUID again so a faulty proxy response cannot expose another transcript.
  if (data.id !== threadId || data.user_id !== principal.user_id) {
    return failure("Conversation unavailable", 404);
  }
  if (!Array.isArray(data.messages) || data.messages.length > MAX_MESSAGES) {
    return failure("Conversation history verification failed", 502);
  }

  const messages: Array<{ id: string; role: "user" | "assistant"; content: string }> = [];
  for (const item of data.messages) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      return failure("Invalid canonical conversation message", 502);
    }
    const message = item as Record<string, unknown>;
    // Never silently discard privileged activity, attachments, or validated
    // presentation receipts. CopilotKit's text-only adapter cannot replay them
    // faithfully yet, so an incomplete transcript must not look restored.
    const metadata = message.metadata;
    const metadataMap =
      metadata && typeof metadata === "object" && !Array.isArray(metadata)
        ? metadata as Record<string, unknown>
        : {};
    const richKeys = [
      "structured_content", "presentation", "presentation_payload",
      "karen.presentation.v1", "tool_activity", "tool_calls",
      "attachments", "artifacts", "execution_receipt",
      "actual_provider", "actual_model", "response_source",
      "requested_provider", "requested_model", "runtime_engine",
      "fallback_level", "degradation_reason", "degraded_mode",
      "citations", "sources", "agent_steps", "tool_results",
    ];
    const carriesRichValue = (value: unknown): boolean =>
      value !== undefined && value !== null && value !== "" &&
      (!Array.isArray(value) || value.length > 0) &&
      (typeof value !== "object" || Object.keys(value).length > 0);
    if (
      (message.role !== "user" && message.role !== "assistant") ||
      richKeys.some((key) =>
        carriesRichValue(message[key]) || carriesRichValue(metadataMap[key]),
      ) ||
      carriesRichValue(message.function_call) ||
      carriesRichValue(message.function_response)
    ) {
      return failure("Complete conversation replay is not yet supported", 409);
    }
    if (typeof message.id !== "string" || !message.id.trim() || message.id.length > 200 ||
        typeof message.content !== "string" || message.content.length > 65536) {
      return failure("Invalid canonical conversation message", 502);
    }
    messages.push({
      id: message.id, role: message.role, content: message.content,
    });
  }
  return NextResponse.json(
    { threadId, messages },
    { headers: { "Cache-Control": "private, no-store" } },
  );
}
