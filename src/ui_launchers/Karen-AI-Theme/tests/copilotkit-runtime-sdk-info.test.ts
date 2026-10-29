import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/app/api/_lib/backend-proxy", () => ({
  getBackendBaseUrl: () => "http://api:8000",
}));

// Do not mock CopilotRuntime, createCopilotRuntimeHandler, or HttpAgent here.
// This exercises the pinned actual SDK's multi-route discovery contract.
import { GET } from "@/app/api/copilotkit/[[...slug]]/route";

const nativeFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = nativeFetch;
  vi.restoreAllMocks();
});

describe("CopilotKit pinned SDK discovery", () => {
  it("registers Karen's real SDK agent behind current backend authentication", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "http://api:8000/api/auth/me") {
        return Response.json({
          user_id: "user-123",
          tenant_id: "tenant-456",
          is_active: true,
        });
      }
      if (String(input) === "http://api:8000/api/chat/ag-ui/capabilities") {
        return Response.json({ enabled: true });
      }
      throw new Error("Unexpected SDK network destination: " + String(input));
    });
    globalThis.fetch = fetchMock as typeof fetch;

    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/info",
      { headers: { cookie: "kari_session=authenticated" } },
    ));

    expect(result.status).toBe(200);
    expect(result.headers.get("content-type")).toContain("application/json");
    const info: unknown = await result.json();
    expect(JSON.stringify(info)).toContain("default");
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "http://api:8000/api/auth/me",
      "http://api:8000/api/chat/ag-ui/capabilities",
    ]);
  });

  it("rejects unauthenticated SDK discovery before any runtime work", async () => {
    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as typeof fetch;
    const result = await GET(new NextRequest(
      "http://localhost:3000/api/copilotkit/info",
    ));
    expect(result.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
