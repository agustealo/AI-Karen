import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET } from "@/app/api/chat/ag-ui/pins/route";

const nativeFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function request(path = "/api/chat/ag-ui/pins") {
  return new NextRequest("http://localhost:3000" + path, {
    headers: {
      Authorization: "Bearer signed-session",
      Cookie: "kari_session=opaque-session; _vercel_jwt=frontend-secret",
    },
  });
}

describe("KAREN authenticated presentation pin readback proxy", () => {
  it("forwards only to the canonical readback and preserves verified backend data", async () => {
    const authoritative = {
      schema_version: 1,
      read_only: true,
      pins: [{
        pin_id: "88888888-8888-4888-8888-888888888888",
        position: 0,
        revision: 1,
        source: {
          conversation_id: "44444444-4444-4444-8444-444444444444",
          assistant_message_id: "22222222-2222-5222-8222-222222222222",
          presentation_id: "verified-card",
          evidence_ref: "verified-evidence",
          component_type: "weather",
          schema_version: 1,
        },
      }],
    };
    const fetchSpy = vi.fn().mockResolvedValue(new Response(
      JSON.stringify(authoritative),
      { status: 200, headers: { "content-type": "application/json", "cache-control": "public, max-age=3600" } },
    ));
    vi.stubGlobal("fetch", fetchSpy);

    const response = await GET(request());
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(await response.json()).toEqual(authoritative);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/api/chat/ag-ui/pins");
    expect(init.method).toBe("GET");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer signed-session");
    expect(headers.get("cookie")).toContain("kari_session=opaque-session");
    expect(headers.get("cookie")).not.toContain("_vercel_jwt");
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("manual");
  });

  it.each([401, 403, 404, 503])(
    "propagates canonical denial or unavailable status %i without fabricated pins",
    async (status) => {
      const fetchSpy = vi.fn().mockResolvedValue(new Response(
        JSON.stringify({ detail: "Pin readback unavailable" }),
        { status, headers: { "content-type": "application/json" } },
      ));
      vi.stubGlobal("fetch", fetchSpy);
      const response = await GET(request());
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toEqual({ detail: "Pin readback unavailable" });
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    },
  );

  it("rejects query variants before forwarding tenant-sensitive reads", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const response = await GET(request("/api/chat/ag-ui/pins?tenant_id=other"));
    expect(response.status).toBe(422);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not follow redirects or retry unknown readback responses", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response(null, {
      status: 307,
      headers: { location: "https://untrusted.example/collect" },
    }));
    vi.stubGlobal("fetch", fetchSpy);
    const response = await GET(request());
    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect((await response.json()).error_code).toBe("BACKEND_REDIRECT_REJECTED");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });
});
