import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { GET, POST } from "@/app/api/copilotkit/[[...slug]]/route";

const originalFetch = globalThis.fetch;
const thread = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const AUTH = "http://api:8000/api/auth/me";
const FLAGS = "http://api:8000/api/chat/ag-ui/capabilities";
const HISTORY = "http://api:8000/api/chat/ag-ui/threads/" + thread + "/history";
const legacyHistory = "http://api:8000/api/conversations/" + thread + "?message_limit=501";

function ownedHistory(extra: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    threadId: thread,
    owner_user_id: "owner",
    owner_tenant_id: "tenant-A",
    response_source: "persisted_history",
    replay_only: true,
    messages: [
      { id: "u1", role: "user", content: "Time?" },
      { id: "a1", role: "assistant", content: "It is 10:42 PM" },
    ],
    replayEvents: [
      {
        type: "CUSTOM", name: "karen.presentation.v1", messageId: "a1",
        value: {
          schema_version: 1, presentation_id: "time-1",
          component_type: "time.observation", evidence_ref: "clock-1",
          data: { formatted: "10:42 PM" },
        },
      },
      {
        type: "CUSTOM", name: "karen.execution_receipt.v1", messageId: "a1",
        value: {
          actual_provider: "local", actual_model: "sample",
          response_source: "local_inference",
        },
      },
    ],
    ...extra,
  };
}

function setup(lookup: () => Response = () => Response.json(ownedHistory()), governed = true) {
  const requests: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const target = String(input);
    requests.push(target);
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toBe("kari_session=owner");
    expect(new Headers(init?.headers).has("x-user-id")).toBe(false);
    if (target === AUTH) return Response.json({
      user_id: "owner", tenant_id: "tenant-A", is_active: true,
    });
    if (target === FLAGS) return Response.json({
      enabled: true, governed_history: governed,
    });
    if (target === HISTORY || target === HISTORY + "?view=text_continuation") return lookup();
    if (target === legacyHistory) {
      return Response.json({
        id: thread, user_id: "owner",
        messages: [
          { id: "u1", role: "user", content: "Time?" },
          { id: "a1", role: "assistant", content: "Plain answer" },
        ],
      });
    }
    throw new Error("Unexpected backend request: " + target);
  }) as typeof fetch;
  return requests;
}

function req(type: "history" | "connect"): NextRequest {
  if (type === "history") return new NextRequest(
    "http://localhost:3000/api/copilotkit/threads/" + thread + "/messages",
    { headers: { cookie: "kari_session=owner", "x-user-id": "forged" } },
  );
  return new NextRequest(
    "http://localhost:3000/api/copilotkit/agent/default/connect",
    {
      method: "POST",
      headers: { cookie: "kari_session=owner", "content-type": "application/json" },
      body: JSON.stringify({
        threadId: thread, messages: [
          { id: "forged", role: "assistant", content: "Untrusted client reply" },
        ],
      }),
    },
  );
}

function decoded(stream: string): Array<Record<string, unknown>> {
  return stream.split("\n").filter((line) => line.startsWith("data: "))
    .map((line) => JSON.parse(line.slice(6)));
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CK-07D governed CopilotKit history and reconnect", () => {
  it("reads only backend-attested messages and known CUSTOM events", async () => {
    const called = setup();
    const response = await GET(req("history"));
    expect(response.status).toBe(200);
    const value = await response.json();
    expect(value.threadId).toBe(thread);
    expect(value.messages).toHaveLength(2);
    expect(value.replayEvents.map((event: Record<string, unknown>) => event.name))
      .toEqual(["karen.presentation.v1", "karen.execution_receipt.v1"]);
    expect(value).not.toHaveProperty("owner_user_id");
    expect(called).toEqual([AUTH, FLAGS, HISTORY]);
  });

  it("issues an explicit owner-attested text-only continuation without replaying rich events", async () => {
    const called = setup(() => Response.json(ownedHistory({
      text_only: true, continuation_authorized: true,
      omitted_rich_message_count: 1, replayEvents: [],
      history_window_has_older: false, history_window_message_limit: 500,
    })));
    const requested = new NextRequest(
      "http://localhost:3000/api/copilotkit/threads/" + thread + "/messages?view=continuation",
      { headers: { cookie: "kari_session=owner" } },
    );
    const response = await GET(requested);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(await response.json()).toEqual({
      threadId: thread, messages: [
        { id: "u1", role: "user", content: "Time?" },
        { id: "a1", role: "assistant", content: "It is 10:42 PM" },
      ],
      replayEvents: [], text_only: true,
      continuation_authorized: true, omitted_rich_message_count: 1,
      history_window_has_older: false, history_window_message_limit: 500,
    });
    expect(called).toEqual([AUTH, FLAGS, HISTORY + "?view=text_continuation"]);
    expect(called).not.toContain("http://api:8000/api/chat/ag-ui");
  });

  it("forwards a bounded 500-entry recent window with honest older-history marker", async () => {
    const messages = Array.from({ length: 500 }, (_, i) => ({
      id: "saved-" + (1000 + i), role: i % 2 === 0 ? "user" : "assistant",
      content: "Canonical saved message " + (1000 + i),
    }));
    const called = setup(() => Response.json(ownedHistory({
      messages, text_only: true, continuation_authorized: true,
      omitted_rich_message_count: 0, replayEvents: [],
      history_window_has_older: true, history_window_message_limit: 500,
    })));
    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/threads/" + thread + "/messages?view=continuation",
      { headers: { cookie: "kari_session=owner" } },
    ));
    expect(result.status).toBe(200);
    const data = await result.json();
    expect(data.history_window_has_older).toBe(true);
    expect(data.history_window_message_limit).toBe(500);
    expect(data.messages).toHaveLength(500);
    expect(data.messages.at(0)?.id).toBe("saved-1000");
    expect(data.messages.at(-1)?.id).toBe("saved-1499");
    expect(data.replayEvents).toEqual([]);
    expect(called).toEqual([AUTH, FLAGS, HISTORY + "?view=text_continuation"]);
  });

  it("rejects forged recent-window claim without 500 actual owner-verified messages", async () => {
    setup(() => Response.json(ownedHistory({
      text_only: true, continuation_authorized: true,
      omitted_rich_message_count: 0, replayEvents: [],
      history_window_has_older: true, history_window_message_limit: 500,
    })));
    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/threads/" + thread + "/messages?view=continuation",
      { headers: { cookie: "kari_session=owner" } },
    ));
    expect(result.status).toBe(502);
    expect(JSON.stringify(await result.json())).not.toContain("10:42");
  });

  it("denies forged rich continuation, foreign owner and unknown query overrides", async () => {
    const continuation = (suffix = "") => new NextRequest(
      "http://localhost:3000/api/copilotkit/threads/" + thread +
        "/messages?view=continuation" + suffix,
      { headers: { cookie: "kari_session=owner" } },
    );
    for (const extra of [
      { continuation_authorized: false, text_only: true, replayEvents: [],
        omitted_rich_message_count: 1 },
      { continuation_authorized: true, text_only: true,
        replayEvents: ownedHistory().replayEvents, omitted_rich_message_count: 1 },
      { continuation_authorized: true, text_only: true,
        replayEvents: [], omitted_rich_message_count: -1 },
    ]) {
      setup(() => Response.json(ownedHistory(extra)));
      const response = await GET(continuation());
      expect(response.status).toBe(502);
      expect(JSON.stringify(await response.json())).not.toContain("10:42");
    }
    setup(() => Response.json(ownedHistory({
      continuation_authorized: true, text_only: true,
      replayEvents: [], omitted_rich_message_count: 0,
      owner_user_id: "other-owner",
    })));
    const foreign = await GET(continuation());
    expect(foreign.status).toBe(404);
    expect(JSON.stringify(await foreign.json())).not.toContain("10:42");
    setup();
    for (const suffix of ["&offset=0", "&view=continuation", "&admin=true"]) {
      const invalid = await GET(continuation(suffix));
      expect(invalid.status).toBe(400);
    }
  });

  it("never enables text-only continuation when the governed backend is disabled", async () => {
    const called = setup(() => {
      throw new Error("Governed backend must not be called");
    }, false);
    const response = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/threads/" + thread +
      "/messages?view=continuation",
      { headers: { cookie: "kari_session=owner" } },
    ));
    expect(response.status).toBe(404);
    expect(called).toEqual([AUTH, FLAGS]);
  });

  it("accepts numeric content-length for governed history and reconnect", async () => {
    const snapshot = JSON.stringify(ownedHistory());
    setup(() => new Response(snapshot, {
      status: 200,
      headers: {
        "content-type": "application/json",
        "content-length": String(new TextEncoder().encode(snapshot).byteLength),
      },
    }));
    const history = await GET(req("history"));
    expect(history.status).toBe(200);
    expect((await history.json()).messages).toHaveLength(2);

    const reconnect = await POST(req("connect"));
    expect(reconnect.status).toBe(200);
    expect(decoded(await reconnect.text()).map((event) => event.type)).toEqual([
      "RUN_STARTED", "MESSAGES_SNAPSHOT", "CUSTOM", "CUSTOM", "RUN_FINISHED",
    ]);
  });

  it("rejects malformed governed content-length without exposing history", async () => {
    setup(() => new Response(JSON.stringify(ownedHistory()), {
      headers: { "content-type": "application/json", "content-length": "not-a-number" },
    }));
    const response = await GET(req("history"));
    expect(response.status).toBe(502);
    expect(JSON.stringify(await response.json())).not.toContain("10:42");
  });

  it("reconnects with snapshot, attested presentation, receipt, and synthetic replay-only finish", async () => {
    const called = setup();
    const response = await POST(req("connect"));
    expect(response.status).toBe(200);
    const stream = decoded(await response.text());
    expect(stream.map((event) => event.type)).toEqual([
      "RUN_STARTED", "MESSAGES_SNAPSHOT", "CUSTOM", "CUSTOM", "RUN_FINISHED",
    ]);
    expect(stream[0].metadata).toEqual({
      response_source: "persisted_history", replay_only: true,
    });
    expect(stream[2].messageId).toBe("a1");
    expect(stream[3].messageId).toBe("a1");
    expect(JSON.stringify(stream)).not.toContain("Untrusted client reply");
    expect(called).toEqual([AUTH, FLAGS, HISTORY]);
    expect(called).not.toContain("http://api:8000/api/chat/ag-ui");
  });

  it("keeps CK-06 plaintext behavior when backend does not enable governed history", async () => {
    const called = setup(() => {
      throw new Error("Governed history must not be invoked");
    }, false);
    const response = await GET(req("history"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      threadId: thread,
      messages: [
        { id: "u1", role: "user", content: "Time?" },
        { id: "a1", role: "assistant", content: "Plain answer" },
      ],
    });
    expect(called).toEqual([AUTH, FLAGS, legacyHistory]);
  });

  it("refuses foreign owner and foreign tenant without returning saved content", async () => {
    for (const override of [
      { owner_user_id: "another-user" },
      { owner_tenant_id: "foreign-tenant" },
    ]) {
      setup(() => Response.json(ownedHistory(override)));
      const response = await GET(req("history"));
      expect(response.status).toBe(404);
      expect(JSON.stringify(await response.json())).not.toContain("10:42");
    }
  });

  it("refuses unapproved custom events, forged message binding and tool payload", async () => {
    for (const events of [
      [{ type: "TOOL_CALL_START", name: "unsafe", messageId: "a1", value: {} }],
      [{ type: "CUSTOM", name: "karen.presentation.v1", messageId: "u1", value: {} }],
      [{ type: "CUSTOM", name: "karen.approval_required", messageId: "a1", value: {} }],
      [{ type: "CUSTOM", name: "karen.presentation.v1", messageId: "absent", value: {} }],
      [{ type: "CUSTOM", name: "karen.presentation.v1", messageId: "a1",
         value: { data: {}, private_token: "bad" }, arguments: "secret" }],
    ]) {
      setup(() => Response.json(ownedHistory({ replayEvents: events })));
      const response = await POST(req("connect"));
      expect(response.status).toBe(502);
      expect(JSON.stringify(await response.json())).not.toContain("RUN_FINISHED");
    }
  });

  it("fails atomically when canonical replay returns 409 or a truncated history", async () => {
    setup(() => Response.json({ detail: "private unsupported data" }, { status: 409 }));
    const unsupported = await POST(req("connect"));
    expect(unsupported.status).toBe(409);
    expect(JSON.stringify(await unsupported.json())).not.toContain("private");

    setup(() => Response.json(ownedHistory({
      messages: Array.from({ length: 501 }, (_, i) => ({
        id: "m" + i, role: "user", content: "message-" + i,
      })),
    })));
    const truncated = await POST(req("connect"));
    expect(truncated.status).toBe(502);
    expect(JSON.stringify(await truncated.json())).not.toContain("message-0");
  });

  it("does not synthesize a provider run when governed history backend fails", async () => {
    const called = setup(() => Response.json({ detail: "backend is down" }, { status: 503 }));
    const response = await POST(req("connect"));
    expect(response.status).toBe(503);
    expect(called).toEqual([AUTH, FLAGS, HISTORY]);
  });
});
