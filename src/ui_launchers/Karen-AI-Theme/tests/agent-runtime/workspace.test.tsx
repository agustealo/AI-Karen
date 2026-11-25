import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  user: { tenant_id: "tenant-A", user_id: "user-A", roles: ["admin"] },
  authenticated: true,
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/lib/useAuth", () => ({
  default: () => ({ user: mocks.user, isAuthenticated: mocks.authenticated, isLoading: false }),
}));
vi.mock("@/lib/api", () => ({
  apiClient: { get: (...args: unknown[]) => mocks.get(...args), post: (...args: unknown[]) => mocks.post(...args) },
}));

import AgentsPage, { isAgentRunRecord, isAgentRunsResponse, isRuntimeApproval } from "@/components/automation/AgentsPage";

const run = { run_id: "run-123456789", status: "running" };
const history = (runs: unknown[]) => ({ runs, total: runs.length, generated_at: "2026-11-25T00:00:00Z" });
const approval = { approval_id: "approval-A", intent: "Review operation", risk_level: "high", status: "pending", reason_codes: [], expires_at: "2099-01-01T00:00:00Z" };
const catalog = { agents: [], total: 0, eligibility_verified: false, selection_authority: "cortex_runtime_policy", execution_authority: "chat_runtime", orchestrator: "agent_medusa" };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.user = { tenant_id: "tenant-A", user_id: "user-A", roles: ["admin"] };
  mocks.authenticated = true;
  mocks.get.mockImplementation(async (path: string) => {
    if (path === "/api/agent-runtime/catalog") return catalog;
    if (path === "/api/approvals/") return [];
    if (path === "/api/agent-runtime/my-runs" || path === "/api/admin/agents/runs?include_terminal=true") return history([]);
    throw new Error("Unexpected path: " + path);
  });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("runtime projection validation", () => {
  it("accepts genuine empty and populated histories but rejects malformed or duplicate records", () => {
    expect(isAgentRunsResponse(history([]))).toBe(true);
    expect(isAgentRunsResponse(history([run]))).toBe(true);
    expect(isAgentRunsResponse(history([run, run]))).toBe(false);
    expect(isAgentRunsResponse({ ...history([]), total: 1 })).toBe(false);
    expect(isAgentRunsResponse({ ...history([]), generated_at: "invalid" })).toBe(false);
    expect(isAgentRunRecord({ ...run, cancellable: "true" })).toBe(false);
    expect(isAgentRunRecord({ ...run, status: null })).toBe(false);
    expect(isRuntimeApproval(approval)).toBe(true);
    expect(isRuntimeApproval({ ...approval, expires_at: "invalid" })).toBe(false);
    expect(isRuntimeApproval({ ...approval, reason_codes: [42] })).toBe(false);
  });

  it("opens personal scope for admins and loads tenant scope only after explicit selection", async () => {
    render(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    expect(mocks.get).not.toHaveBeenCalledWith("/api/admin/agents/runs?include_terminal=true");
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/admin/agents/runs?include_terminal=true"));
    expect(screen.getByText("Tenant execution workspace")).toBeTruthy();
  });

  it("rejects malformed history without rendering a verified empty state", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/agent-runtime/my-runs" ? Promise.resolve({ runs: null }) : fallback(path));
    render(<AgentsPage />);
    await screen.findByText("Execution history is unavailable. Refresh runtime to try again.");
    expect(screen.queryByText("No verified executions match this view.")).toBeNull();
  });

  it("does not show a mismatched run detail as verified", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/agent-runtime/my-runs" ? Promise.resolve(history([run])) : path.endsWith("/" + run.run_id) ? Promise.resolve({ ...run, run_id: "wrong" }) : fallback(path));
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Execution details do not match the requested run.");
    expect(screen.queryByRole("heading", { name: "Execution details" })).toBeNull();
  });

  it("does not render a delayed previous-account history", async () => {
    const old = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    mocks.get.mockImplementation((path: string) => path === "/api/agent-runtime/my-runs" ? (++reads === 1 ? old.promise : Promise.resolve(history([]))) : fallback(path));
    const view = render(<AgentsPage />);
    await waitFor(() => expect(reads).toBe(1));
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
    view.rerender(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    await act(async () => { old.resolve(history([run])); });
    expect(screen.queryByRole("button", { name: /Execution run-1234/ })).toBeNull();
  });

  it("blocks an old approval completion from starting a new read after account change", async () => {
    const decision = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/" ? Promise.resolve(++reads === 1 ? [approval] : []) : fallback(path));
    mocks.post.mockReturnValue(decision.promise);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(mocks.post).toHaveBeenCalledTimes(1);
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
    view.rerender(<AgentsPage />);
    await screen.findByText(/You’re all caught up/);
    await act(async () => { decision.resolve({ ...approval, status: "approved" }); });
    expect(reads).toBe(2);
    expect(screen.queryByText(/Decision recorded:/)).toBeNull();
  });
});
