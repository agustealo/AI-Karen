import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const originalFetch = globalThis.fetch;
const backend = "https://canonical-backend.example";

function configured(target = backend): void {
  vi.stubEnv("VERCEL", "1");
  vi.stubEnv("VERCEL_ENV", "preview");
  vi.stubEnv("KAREN_BACKEND_URL", target);
  vi.stubEnv("BACKEND_URL", "https://legacy-backend.example");
  vi.resetModules();
}

function agUiRequest(): NextRequest {
  return new NextRequest("https://frontend.example/api/chat/ag-ui", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      threadId: "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0",
      runId: "run-once",
      state: {},
      messages: [{ id: "message-1", role: "user", content: "Hello" }],
      tools: [],
      context: [],
    }),
  });
}

function copilotRequest(): NextRequest {
  return new NextRequest("https://frontend.example/api/copilotkit/info", {
    headers: { cookie: "kari_session=private-session" },
  });
}

function legacyRequest(): NextRequest {
  return new NextRequest("https://frontend.example/api/copilot/assist/stream", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer private-session-token",
      cookie: "kari_session=private-session",
      "x-vercel-protection-bypass": "vercel-private-bypass",
    },
    body: JSON.stringify({ message: "Execute exactly once" }),
  });
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("canonical consumer ingress configuration and execution safety", () => {
  it.each(["", "http://api:8000", "http://localhost:8000", "http://backend.example"])(
    "AG-UI fails closed on invalid Vercel backend %s before starting inference",
    async (target) => {
      configured(target);
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      const { POST } = await import("@/app/api/chat/ag-ui/route");

      const result = await POST(agUiRequest());
      expect(result.status).toBe(503);
      expect(result.headers.get("cache-control")).toBe("no-store");
      expect(await result.json()).toMatchObject({
        error_code: "BACKEND_TARGET_NOT_CONFIGURED",
      });
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("CopilotKit refuses to discover or start an agent with no configured backend", async () => {
    configured("");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { GET } = await import("@/app/api/copilotkit/[[...slug]]/route");

    const response = await GET(copilotRequest());
    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toMatchObject({
      error_code: "BACKEND_TARGET_NOT_CONFIGURED",
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("legacy Copilot streaming cannot attempt a fallback host when unconfigured", async () => {
    configured("");
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { POST } = await import("@/app/api/copilot/assist/stream/route");

    const response = await POST(legacyRequest());
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      error_code: "BACKEND_TARGET_NOT_CONFIGURED",
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("legacy Copilot streaming makes exactly one authorized request and strips frontend credentials", async () => {
    configured();
    const outbound = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response('data: {"type":"RUN_FINISHED"}\\n\\n', {
        status: 200,
        headers: {
          "content-type": "text/event-stream",
          "x-correlation-id": "corr-123",
        },
      }));
    vi.stubGlobal("fetch", outbound);
    const { POST } = await import("@/app/api/copilot/assist/stream/route");

    const response = await POST(legacyRequest());
    expect(response.status).toBe(200);
    expect(await response.text()).toContain("RUN_FINISHED");
    expect(response.headers.get("x-correlation-id")).toBe("corr-123");
    expect(outbound).toHaveBeenCalledTimes(1);
    const [destination, init] = outbound.mock.calls[0];
    expect(destination).toBe(backend + "/api/copilot/assist/stream");
    expect((init as RequestInit).redirect).toBe("manual");
    const sent = new Headers((init as RequestInit).headers);
    expect(sent.get("authorization")).toBe("Bearer private-session-token");
    expect(sent.get("cookie")).toBe("kari_session=private-session");
    expect(sent.has("x-vercel-protection-bypass")).toBe(false);
  });

  it("never replays a POST after a redirect or exposes a cross-host Location header", async () => {
    configured();
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, {
      status: 307,
      headers: { location: "https://other-backend.example/private" },
    }));
    vi.stubGlobal("fetch", fetchSpy);
    const { POST } = await import("@/app/api/copilot/assist/stream/route");

    const result = await POST(legacyRequest());
    expect(result.status).toBe(502);
    expect(await result.json()).toMatchObject({
      error_code: "COPILOT_STREAM_UPSTREAM_REDIRECT",
    });
    expect(result.headers.get("location")).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("redacts provider error bodies and does not retry an uncertain POST", async () => {
    configured();
    const fetchSpy = vi.fn().mockResolvedValue(new Response(
      "secret-token-and-private-provider-body", { status: 503 },
    ));
    vi.stubGlobal("fetch", fetchSpy);
    const { POST } = await import("@/app/api/copilot/assist/stream/route");

    const result = await POST(legacyRequest());
    expect(result.status).toBe(503);
    const answer = await result.text();
    expect(answer).toContain("COPILOT_STREAM_UPSTREAM_REJECTED");
    expect(answer).not.toContain("secret-token");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("redacts transport error messages, URLs and credentials", async () => {
    configured();
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchSpy = vi.fn().mockRejectedValue(
      new TypeError("secret-token from https://canonical-backend.example/private"),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const { POST } = await import("@/app/api/copilot/assist/stream/route");

    const result = await POST(legacyRequest());
    expect(result.status).toBe(502);
    expect((await result.json()).error_code).toBe("COPILOT_STREAM_UNAVAILABLE");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(consoleSpy.mock.calls)).not.toContain("secret-token");
    expect(JSON.stringify(consoleSpy.mock.calls)).not.toContain(backend);
  });
});
