import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

import { GET } from "@/app/api/copilotkit/[[...slug]]/route";

const originalFetch = globalThis.fetch;
const thread = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const runId = "run_cursor";
const AUTH = "http://api:8000/api/auth/me";
const FLAGS = "http://api:8000/api/chat/ag-ui/capabilities";
const backend = "http://api:8000/api/chat/ag-ui/runs/" + thread +
  "/" + runId + "/events?after=0&limit=50";

function request(query = "?after=0&limit=50") {
  return new NextRequest(
    "http://localhost:3000/api/copilotkit/threads/" +
      thread + "/runs/" + runId + "/events" + query,
    { headers: { cookie: "kari_session=owner", "x-user-id": "forged" } },
  );
}

function observed(extra: Record<string, unknown> = {}) {
  return {
    threadId: thread,
    runId,
    owner_user_id: "owner",
    owner_tenant_id: "tenant-A",
    events: [
      { seq: 1, event: { type: "RUN_STARTED", threadId: thread, runId } },
      { seq: 2, event: { type: "TEXT_MESSAGE_CONTENT",
                        messageId: "assistant-run_cursor", delta: "Partial." } },
    ],
    nextCursor: 2,
    hasMore: false,
    runStatus: "interrupted",
    terminalConfirmed: false,
    journalTerminalObserved: false,
    continuationAvailable: false,
    responseSource: "observed_event_journal",
    ...extra,
  };
}

function setup(reply: () => Response = () => Response.json(observed()),
               enabled = true) {
  const calls: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toBe("kari_session=owner");
    expect(new Headers(init?.headers).has("x-user-id")).toBe(false);
    if (url === AUTH) return Response.json({
      user_id: "owner", tenant_id: "tenant-A", is_active: true,
    });
    if (url === FLAGS) return Response.json({
      enabled: true, governed_history: true,
      observed_event_journal: enabled,
    });
    if (url === backend) return reply();
    throw new Error("Unexpected backend request: " + url);
  }) as typeof fetch;
  return calls;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("CK-07E1 owner-scoped observed run cursor", () => {
  it("returns recorded partial text without invented resume, success or provider calls", async () => {
    const called = setup();
    const response = await GET(request());
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    const data = await response.json();
    expect(data.events.map((x: { seq: number }) => x.seq)).toEqual([1, 2]);
    expect(data.runStatus).toBe("interrupted");
    expect(data.terminalConfirmed).toBe(false);
    expect(data.journalTerminalObserved).toBe(false);
    expect(data.continuationAvailable).toBe(false);
    expect(data.events.map((x: { event: { type: string } }) => x.event.type))
      .not.toContain("RUN_FINISHED");
    expect(data).not.toHaveProperty("owner_user_id");
    expect(called).toEqual([AUTH, FLAGS, backend]);
  });

  it("does not request event history when the canonical backend flag is off", async () => {
    const called = setup(() => { throw new Error("Must not query events"); }, false);
    const response = await GET(request());
    expect(response.status).toBe(404);
    expect(called).toEqual([AUTH, FLAGS]);
  });

  it("rejects foreign principal and tenant even when backend returns data", async () => {
    for (const foreign of [
      { owner_user_id: "foreign" },
      { owner_tenant_id: "foreign" },
    ]) {
      setup(() => Response.json(observed(foreign)));
      const response = await GET(request());
      expect(response.status).toBe(404);
      expect(JSON.stringify(await response.json())).not.toContain("Partial.");
    }
  });

  it("rejects gaps and unsupported tool/event payloads without partial playback", async () => {
    const invalidEvents = [
      [{ seq: 2, event: { type: "TEXT_MESSAGE_CONTENT", delta: "partial" } }],
      [{ seq: 1, event: { type: "TOOL_CALL_START", toolCallId: "secret" } }],
      [{ seq: 1, event: { type: "CUSTOM", name: "karen.approval_required",
                           value: { tools: ["unsafe"] } } }],
      [{ seq: 1, event: { type: "RUN_FINISHED", threadId: thread, runId } }],
    ];
    for (const events of invalidEvents) {
      setup(() => Response.json(observed({
        events, nextCursor: events[events.length - 1].seq,
      })));
      const response = await GET(request());
      expect([409, 502]).toContain(response.status);
      expect(JSON.stringify(await response.json())).not.toContain("partial");
    }
  });

  it("rejects contradictory completed claims and missing journal provenance", async () => {
    for (const contradiction of [
      { runStatus: "interrupted", terminalConfirmed: true },
      { runStatus: "completed", terminalConfirmed: false },
      { journalTerminalObserved: true },
      { continuationAvailable: true },
      { responseSource: "untrusted_sdk_cache" },
    ]) {
      setup(() => Response.json(observed(contradiction)));
      expect((await GET(request())).status).toBe(502);
    }
  });

  it("validates cursor query before making the backend data request", async () => {
    for (const query of [
      "?after=-1", "?after=2049", "?limit=101", "?limit=0",
      "?after=0&after=1", "?limit=1&debug=true", "?after=2.5",
    ]) {
      const called = setup();
      const response = await GET(request(query));
      expect(response.status).toBe(422);
      expect(called).toEqual([AUTH, FLAGS]);
    }
  });

  it("does not follow redirects or forward failed backend history as a replay", async () => {
    const called = setup(() => new Response(null, {
      status: 302, headers: { location: "https://attacker.invalid/run" },
    }));
    const response = await GET(request());
    expect(response.status).toBe(503);
    expect(called).toEqual([AUTH, FLAGS, backend]);
  });
});
