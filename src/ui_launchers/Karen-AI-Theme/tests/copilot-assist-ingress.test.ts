import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";

const proxy = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock("@/app/api/_lib/backend-proxy", () => ({
  proxyToBackend: proxy.send,
}));
import { POST } from "@/app/api/copilot/assist/route";

const url = "http://localhost:3000/api/copilot/assist";
const sameClientSuppliedPayload = JSON.stringify({
  user_id: "browser-claimed-user",
  session_id: "browser-claimed-session",
  message: "Review my project",
});

function assist(cookie: string): NextRequest {
  return new NextRequest(url, {
    method: "POST",
    headers: {
      cookie,
      "content-type": "application/json",
    },
    body: sameClientSuppliedPayload,
  });
}

describe("Legacy Copilot assist is thin, tenant-safe ingress", () => {
  beforeEach(() => proxy.send.mockReset());

  it("never coalesces identical client-controlled identities across authenticated callers", async () => {
    let releaseFirst!: (value: NextResponse) => void;
    const first = new Promise<NextResponse>((resolve) => { releaseFirst = resolve; });
    proxy.send
      .mockImplementationOnce(() => first)
      .mockImplementationOnce(async () => NextResponse.json({ answer: "caller B" }));

    const callerA = POST(assist("session=A"));
    const callerB = POST(assist("session=B"));

    const second = await callerB;
    expect(proxy.send).toHaveBeenCalledTimes(2);
    const [firstRequest] = proxy.send.mock.calls[0] as [NextRequest];
    const [secondRequest] = proxy.send.mock.calls[1] as [NextRequest];
    expect(firstRequest.headers.get("cookie")).toBe("session=A");
    expect(secondRequest.headers.get("cookie")).toBe("session=B");
    expect((await second.json()).answer).toBe("caller B");

    releaseFirst(NextResponse.json({ answer: "caller A" }));
    expect((await (await callerA).json()).answer).toBe("caller A");
  });

  it("never automatically retries an execution POST", async () => {
    proxy.send.mockResolvedValueOnce(NextResponse.json(
      { detail: "Backend unavailable" },
      { status: 503 },
    ));
    const response = await POST(assist("session=valid"));
    expect(response.status).toBe(503);
    expect(proxy.send).toHaveBeenCalledTimes(1);
    expect(proxy.send.mock.calls[0][1]).toBe("/api/copilot/assist");
    expect(proxy.send.mock.calls[0][2]).toEqual({
      longTimeout: true,
      retryAttempts: 1,
      retryOnStatusCodes: [],
    });
    expect((await response.json()).detail).toBe("Backend unavailable");
  });

  it("passes the incoming request unchanged to canonical proxy authentication", async () => {
    proxy.send.mockResolvedValueOnce(NextResponse.json({ detail: "Authentication required" }, { status: 401 }));
    const request = assist("session=expired");
    const response = await POST(request);
    expect(proxy.send.mock.calls[0][0]).toBe(request);
    expect(response.status).toBe(401);
  });
});
