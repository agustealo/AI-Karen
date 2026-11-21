import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/chat/ag-ui/pins/mutations/route";

const nativeFetch = globalThis.fetch;
const pinId = "88888888-8888-4888-8888-888888888888";
const idempotencyKey = "99999999-9999-4999-8999-999999999999";
const source = {
  conversation_id: "44444444-4444-4444-8444-444444444444",
  assistant_message_id: "22222222-2222-5222-8222-222222222222",
  presentation_id: "card-from-authorized-run",
  evidence_ref: "verified-evidence",
};

function request(
  body: unknown,
  path = "/api/chat/ag-ui/pins/mutations",
  contentType = "application/json",
): NextRequest {
  return new NextRequest("http://localhost:3000" + path, {
    method: "POST",
    headers: {
      "Content-Type": contentType,
      Authorization: "Bearer signed-session",
      Cookie: "kari_session=opaque-session; _vercel_jwt=frontend-secret",
    },
    body: JSON.stringify(body),
  });
}

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("KAREN single-shot authenticated presentation pin mutation ingress", () => {
  it.each([
    { operation: "pin", idempotency_key: idempotencyKey, source },
    { operation: "pin", idempotency_key: idempotencyKey, source, position: 1 },
    { operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId },
    {
      operation: "reorder", idempotency_key: idempotencyKey,
      pin_id: pinId, expected_revision: 3, position: 5,
    },
  ])("passes a valid $operation request only to the canonical mutation backend", async (body) => {
    const receipt = {
      schema_version: 1,
      committed: true,
      receipt: {
        receipt_id: "receipt-1",
        operation: body.operation,
        pin_id: pinId,
      },
    };
    const fetchSpy = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), {
      status: 200,
      headers: {
        "content-type": "application/json",
        "cache-control": "public, max-age=3600",
        "x-correlation-id": "runtime-correlation",
      },
    }));
    vi.stubGlobal("fetch", fetchSpy);
    const response = await POST(request(body));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(receipt);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-correlation-id")).toBe("runtime-correlation");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/api/chat/ag-ui/pins/mutations");
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    expect(init.redirect).toBe("manual");
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBe("Bearer signed-session");
    expect(headers.get("cookie")).toContain("kari_session=opaque-session");
    expect(headers.get("cookie")).not.toContain("_vercel_jwt");
    expect(JSON.parse(init.body as string)).toEqual(body);
  });

  it.each([401, 403, 404, 409, 422, 503])(
    "returns backend status %i and its denial without inventing a receipt or retry",
    async (status) => {
      const backend = { detail: "Canonical mutation rejected" };
      const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify(backend), {
        status,
        headers: { "content-type": "application/json" },
      }));
      vi.stubGlobal("fetch", spy);
      const response = await POST(request({ operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId }));
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("private, no-store");
      expect(await response.json()).toEqual(backend);
      expect(spy).toHaveBeenCalledTimes(1);
    },
  );

  it("rejects backend redirect with one fetch and no cross-origin credential leak", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(null, {
      status: 307,
      headers: { location: "https://untrusted.example/collect" },
    }));
    vi.stubGlobal("fetch", spy);
    const response = await POST(request({ operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId }));
    expect(response.status).toBe(502);
    expect((await response.json()).error_code).toBe("BACKEND_REDIRECT_REJECTED");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("never resends a POST after an uncertain upstream transport failure", async () => {
    const spy = vi.fn().mockRejectedValue(new Error("ECONNRESET"));
    vi.stubGlobal("fetch", spy);
    const response = await POST(request({ operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId }));
    expect(response.status).toBe(502);
    expect((await response.json()).error_code).toBe("BACKEND_UPSTREAM_UNAVAILABLE");
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ operation: "pin", idempotency_key: idempotencyKey }, 422],
    [{ operation: "pin", idempotency_key: idempotencyKey, source, tenant_id: pinId }, 422],
    [{ operation: "pin", idempotency_key: idempotencyKey, source: { ...source, user_id: pinId } }, 422],
    [{ operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId, expected_revision: 2 }, 422],
    [{ operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId, receipt: {} }, 422],
    [{ operation: "reorder", idempotency_key: idempotencyKey, pin_id: pinId, position: 1 }, 422],
    [{ operation: "reorder", idempotency_key: idempotencyKey, pin_id: pinId, expected_revision: 0, position: 1 }, 422],
    [{ operation: "reorder", idempotency_key: idempotencyKey, pin_id: pinId, expected_revision: 1, position: 100 }, 422],
    [{ operation: "unpin", idempotency_key: "not-a-uuid", pin_id: pinId }, 422],
  ])("fails closed on invalid or authority-bearing request before any backend write", async (body, status) => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const response = await POST(request(body));
    expect(response.status).toBe(status);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(spy).not.toHaveBeenCalled();
  });

  it("rejects query, non-JSON, malformed JSON and oversized payloads before forwarding", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const valid = { operation: "unpin", idempotency_key: idempotencyKey, pin_id: pinId };
    expect((await POST(request(valid, "/api/chat/ag-ui/pins/mutations?tenant_id=forged"))).status).toBe(422);
    expect((await POST(request(valid, "/api/chat/ag-ui/pins/mutations", "text/plain"))).status).toBe(415);
    const broken = new NextRequest("http://localhost:3000/api/chat/ag-ui/pins/mutations", {
      method: "POST", headers: { "content-type": "application/json" }, body: "{broken",
    });
    expect((await POST(broken)).status).toBe(400);
    const huge = { ...valid, padding: "x".repeat(5000) };
    expect((await POST(request(huge))).status).toBe(413);
    expect(spy).not.toHaveBeenCalled();
  });
});
