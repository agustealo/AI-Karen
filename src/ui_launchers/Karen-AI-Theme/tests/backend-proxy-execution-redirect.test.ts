import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { proxyToBackend } from "@/app/api/_lib/backend-proxy";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("Canonical backend proxy execution redirects", () => {
  it("does not repeat an execution POST after an upstream 307 redirect", async () => {
    const fetchSpy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response("Execution was not completed", {
        status: 307,
        headers: { location: "/api/copilot/other" },
      }),
    );
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/copilot/assist", {
      method: "POST",
      headers: { cookie: "session=caller-A", "content-type": "application/json" },
      body: JSON.stringify({ user_id: "untrusted", message: "Execute once" }),
    });
    const result = await proxyToBackend(request, "/api/copilot/assist", {
      retryAttempts: 1,
      retryOnStatusCodes: [],
      followRedirects: false,
    });

    expect(result.status).toBe(307);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.redirect).toBe("manual");
    expect(new Headers(init?.headers).get("cookie")).toBe("session=caller-A");
    // Internal Docker URL and redirect targets are never exposed to clients.
    expect(result.headers.get("location")).toBeNull();
  });

  it("preserves existing redirect behavior for ordinary non-execution requests", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response("", {
        status: 301,
        headers: { location: "/api/public/info" },
      }))
      .mockResolvedValueOnce(new Response("OK", { status: 200 }));
    globalThis.fetch = fetchSpy as typeof fetch;

    const request = new NextRequest("http://localhost:3000/api/public/info");
    const response = await proxyToBackend(request, "/api/public/info", {
      retryAttempts: 1,
    });

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("OK");
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
