import React from "react";
import { act, cleanup, fireEvent, render as renderWithTestingLibrary, screen, waitFor } from "@testing-library/react";
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

import AgentsPage, { isAgentRunRecord, isAgentRunsResponse, isRuntimeApproval, isRunTransitionsResponse, isRunParticipationResponse } from "@/components/automation/AgentsPage";

import { RuntimeApprovalProvider } from "@/components/approvals/RuntimeApprovalProvider";
import { isRunToolReceiptsResponse } from "@/components/automation/GovernedToolReceipts";

const render = (ui: React.ReactElement) => renderWithTestingLibrary(ui, { wrapper: RuntimeApprovalProvider });

const run = { run_id: "run-123456789", status: "running" };
const history = (runs: unknown[]) => ({ runs, total: runs.length, generated_at: "2026-11-25T00:00:00Z" });
const approval = { approval_id: "approval-A", workflow_kind: "runtime_approval", intent: "Review operation", risk_level: "high", status: "pending", reason_codes: [], expires_at: "2099-01-01T00:00:00Z" };
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
    expect(isRuntimeApproval({ ...approval, workflow_kind: undefined })).toBe(false);
    expect(isRuntimeApproval({ ...approval, workflow_kind: "unknown" })).toBe(false);
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

  it("discovers work after an initially empty history on visibility restoration", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    mocks.get.mockImplementation((path: string) => path === "/api/agent-runtime/my-runs"
      ? Promise.resolve(history(++reads === 1 ? [] : [run])) : fallback(path));
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      render(<AgentsPage />);
      await screen.findByText("No verified executions match this view.");
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await screen.findByRole("button", { name: /Execution run-1234/ });
      expect(reads).toBe(2);
    } finally {
      visibility.mockRestore();
    }
  });

  it("does not write a delayed previous-account context to the clipboard", async () => {
    const context = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    try {
      mocks.get.mockImplementation((path: string) => {
        if (path === "/api/agent-runtime/my-runs") return Promise.resolve(history(mocks.user.user_id === "user-A" ? [run] : []));
        if (path.endsWith("/" + run.run_id + "/context")) return context.promise;
        if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
        return fallback(path);
      });
      const view = render(<AgentsPage />);
      fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
      fireEvent.click(await screen.findByRole("button", { name: "Copy verified context for Karen" }));
      expect(mocks.get).toHaveBeenCalledWith("/api/agent-runtime/my-runs/" + run.run_id + "/context");
      mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
      view.rerender(<AgentsPage />);
      await screen.findByText("No verified executions match this view.");
      await act(async () => { context.resolve({ resource_type: "medusa_run", ...run }); });
      expect(writeText).not.toHaveBeenCalled();
    } finally {
      if (original) Object.defineProperty(navigator, "clipboard", original);
      else Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("preserves the decision lock across workspace unmount and return", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const decision = deferred<unknown>();
    let reads = 0;
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
      ? Promise.resolve(++reads === 1 ? [approval] : [{ ...approval, status: "approved" }]) : fallback(path));
    mocks.post.mockReturnValue(decision.promise);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    view.rerender(<p>Other workspace</p>);
    view.rerender(<AgentsPage />);
    const review = await screen.findByRole("button", { name: "Review approval" }) as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    fireEvent.click(review);
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(reads).toBe(1);
    await act(async () => { decision.resolve({ ...approval, status: "approved" }); });
    await screen.findByText("Decision recorded: approved. Karen must still revalidate and resume the original request.");
    expect(screen.queryByRole("button", { name: "Review approval" })).toBeNull();
    expect(reads).toBe(2);
  });

  it("routes specialized approvals and withholds generic decisions", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const consentId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/" ? Promise.resolve([
      { ...approval, approval_id: consentId, workflow_kind: "document_author_consent", intent: "writing_style.document_consent.issue" },
      { ...approval, approval_id: "plugin", workflow_kind: "plugin_lifecycle", intent: "plugin.lifecycle.enable" },
      { ...approval, approval_id: "unknown", workflow_kind: "unsupported_specialized", intent: "specialized workflow" },
      { ...approval, approval_id: "approved", status: "approved" },
      { ...approval, approval_id: "expired", expires_at: "2000-01-01T00:00:00Z" },
    ]) : fallback(path));
    render(<AgentsPage />);
    const link = await screen.findByRole("link", { name: "Review document author consent" });
    expect(link.getAttribute("href")).toBe("/approvals/document-consent/" + consentId);
    expect(screen.getByText(/Plugin lifecycle decisions require the governed plugin workflow/)).toBeTruthy();
    expect(screen.getByText(/No supported review workflow is available/)).toBeTruthy();
    expect(screen.getByText(/Authorization expired/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Review approval" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Review rejection" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("does not submit a second approval while the first decision is unresolved", async () => {
    const decision = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/" ? Promise.resolve([approval]) : fallback(path));
    mocks.post.mockReturnValue(decision.promise);
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    const confirm = screen.getByRole("button", { name: "Confirm approval" });
    act(() => {
      confirm.click();
      confirm.click();
    });
    expect(mocks.post).toHaveBeenCalledTimes(1);
    await act(async () => { decision.resolve({ ...approval, status: "approved" }); });
  });


  it("preserves verified history and selected details while a background refresh is pending", async () => {
    const nextHistory = deferred<unknown>();
    const nextDetail = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    let detailReads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => {
        if (path === "/api/agent-runtime/my-runs") return ++reads === 1 ? Promise.resolve(history([run])) : nextHistory.promise;
        if (path.endsWith("/" + run.run_id)) return ++detailReads === 1 ? Promise.resolve(run) : nextDetail.promise;
        return fallback(path);
      });
      render(<AgentsPage />);
      fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
      await screen.findByRole("heading", { name: "Execution details" });
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      expect(screen.getByRole("button", { name: /Execution run-1234/ })).toBeTruthy();
      expect(screen.getByRole("heading", { name: "Execution details" })).toBeTruthy();
      expect(screen.getByText(/Execution snapshot:.*Refreshing/)).toBeTruthy();
      await act(async () => { nextHistory.resolve(history([run])); });
      expect(screen.getByRole("heading", { name: "Execution details" })).toBeTruthy();
      expect(screen.getByText("Revalidating execution status…")).toBeTruthy();
      expect((screen.getByRole("button", { name: "Copy verified context for Karen" }) as HTMLButtonElement).disabled).toBe(true);
      await act(async () => { nextDetail.resolve({ ...run, status: "completed" }); });
      expect(await screen.findByText("Execution completed. A saved artifact is not implied by this status.")).toBeTruthy();
    } finally { visibility.mockRestore(); }
  });

  it("removes previously verified history and details when refresh fails", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => {
        if (path === "/api/agent-runtime/my-runs") return ++reads === 1 ? Promise.resolve(history([run])) : Promise.reject(new Error("Access unavailable"));
        if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
        return fallback(path);
      });
      render(<AgentsPage />);
      fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
      await screen.findByRole("heading", { name: "Execution details" });
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await screen.findByText("Execution history is unavailable. Refresh runtime to try again.");
      expect(screen.queryByRole("heading", { name: "Execution details" })).toBeNull();
      expect(screen.queryByRole("button", { name: /Execution run-1234/ })).toBeNull();
    } finally { visibility.mockRestore(); }
  });


  it("does not disclose transport errors from approval discovery", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
      ? Promise.reject(new Error("private transport detail")) : fallback(path));
    render(<AgentsPage />);
    await screen.findByText("Could not load approval requests.");
    expect(screen.queryByText("private transport detail")).toBeNull();
    expect(screen.queryByText(/No actionable approval requests/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Review approval" })).toBeNull();
  });

  it("requires a fresh confirmation after approval discovery refresh", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
      ? Promise.resolve([approval]) : fallback(path));
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    expect(screen.getByRole("button", { name: "Confirm approval" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh runtime" }));
    await screen.findByRole("button", { name: "Review approval" });
    expect(screen.queryByRole("button", { name: "Confirm approval" })).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("discovers approvals on visibility restoration even with empty run history", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
        ? Promise.resolve(++reads === 1 ? [] : [approval]) : fallback(path));
      render(<AgentsPage />);
      await screen.findByText(/You’re all caught up/);
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await screen.findByRole("button", { name: "Review approval" });
      expect(reads).toBe(2);
    } finally { visibility.mockRestore(); }
  });

  it("blocks uncertain approval retries until successful reconciliation", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const reconciliation = deferred<unknown>();
    let reads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
        ? (++reads === 1 ? Promise.resolve([approval]) : reconciliation.promise) : fallback(path));
      mocks.post.mockRejectedValue(new Error("Response lost"));
      render(<AgentsPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
      await screen.findByText("Decision outcome could not be verified. Refresh before attempting another decision.");
      const review = screen.getByRole("button", { name: "Review approval" }) as HTMLButtonElement;
      expect(review.disabled).toBe(true);
      fireEvent.click(review);
      expect(mocks.post).toHaveBeenCalledTimes(1);
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await act(async () => { reconciliation.resolve([approval]); });
      expect((await screen.findByRole("button", { name: "Review approval" }) as HTMLButtonElement).disabled).toBe(false);
      expect(screen.queryByText(/Decision outcome could not be verified/)).toBeNull();
    } finally { visibility.mockRestore(); }
  });

  it("does not start an approval discovery read during a pending decision", async () => {
    const decision = deferred<unknown>();
    const fallback = mocks.get.getMockImplementation()!;
    let reads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => path === "/api/approvals/"
        ? Promise.resolve(++reads === 1 ? [approval] : []) : fallback(path));
      mocks.post.mockReturnValue(decision.promise);
      render(<AgentsPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
      fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
      await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
      expect(reads).toBe(1);
      await act(async () => { decision.resolve({ ...approval, status: "approved" }); });
      await screen.findByText(/You’re all caught up/);
      expect(reads).toBe(2);
    } finally { visibility.mockRestore(); }
  });


  it("preserves history and blocks cancellation retries until a verified refresh", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const cancellableRun = { ...run, cancellable: true };
    const reconciliation = deferred<unknown>();
    let tenantReads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => {
        if (path === "/api/admin/agents/runs?include_terminal=true") return ++tenantReads === 1 ? Promise.resolve(history([cancellableRun])) : reconciliation.promise;
        if (path.endsWith("/" + run.run_id)) return Promise.resolve(cancellableRun);
        return fallback(path);
      });
      mocks.post.mockRejectedValue(new Error("Response lost"));
      render(<AgentsPage />);
      fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
      fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
      const cancel = await screen.findByRole("button", { name: "Request cancellation" });
      fireEvent.click(cancel);
      await screen.findByText("Cancellation outcome could not be verified. Refresh to inspect current execution status.");
      expect(screen.getByRole("button", { name: /Execution run-1234/ })).toBeTruthy();
      expect((cancel as HTMLButtonElement).disabled).toBe(true);
      fireEvent.click(cancel);
      expect(mocks.post).toHaveBeenCalledTimes(1);
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      expect((cancel as HTMLButtonElement).disabled).toBe(true);
      await act(async () => { reconciliation.resolve(history([cancellableRun])); });
      await waitFor(() => expect((screen.getByRole("button", { name: "Request cancellation" }) as HTMLButtonElement).disabled).toBe(false));
      expect(screen.queryByText(/Cancellation outcome could not be verified/)).toBeNull();
    } finally { visibility.mockRestore(); }
  });


  it("does not reconcile cancellation uncertainty with a read started before the lost response", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const cancellableRun = { ...run, cancellable: true };
    const staleRead = deferred<unknown>();
    const freshRead = deferred<unknown>();
    let rejectCancellation!: (reason: Error) => void;
    const cancellation = new Promise<unknown>((_resolve, reject) => { rejectCancellation = reject; });
    let tenantReads = 0;
    const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    try {
      mocks.get.mockImplementation((path: string) => {
        if (path === "/api/admin/agents/runs?include_terminal=true") {
          tenantReads += 1;
          return tenantReads === 1 ? Promise.resolve(history([cancellableRun])) : tenantReads === 2 ? staleRead.promise : freshRead.promise;
        }
        if (path.endsWith("/" + run.run_id)) return Promise.resolve(cancellableRun);
        return fallback(path);
      });
      mocks.post.mockReturnValue(cancellation);
      render(<AgentsPage />);
      fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
      fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
      const cancel = await screen.findByRole("button", { name: "Request cancellation" });
      fireEvent.click(cancel);
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      expect(tenantReads).toBe(2);
      await act(async () => { rejectCancellation(new Error("Response lost")); });
      await screen.findByText(/Cancellation outcome could not be verified/);
      await act(async () => { staleRead.resolve(history([cancellableRun])); });
      expect((screen.getByRole("button", { name: "Request cancellation" }) as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText(/Cancellation outcome could not be verified/)).toBeTruthy();
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      expect(tenantReads).toBe(3);
      await act(async () => { freshRead.resolve(history([cancellableRun])); });
      await waitFor(() => expect((screen.getByRole("button", { name: "Request cancellation" }) as HTMLButtonElement).disabled).toBe(false));
      expect(screen.queryByText(/Cancellation outcome could not be verified/)).toBeNull();
      expect(mocks.post).toHaveBeenCalledTimes(1);
    } finally { visibility.mockRestore(); }
  });


  it("searches verified history locally and preserves selection outside the filters", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const completed = { run_id: "finished-987654", status: "completed" };
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/agent-runtime/my-runs") return Promise.resolve(history([run, completed]));
      if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
      return fallback(path);
    });
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByRole("heading", { name: "Execution details" });
    const reads = mocks.get.mock.calls.length;
    fireEvent.change(screen.getByRole("searchbox", { name: "Search visible executions" }), { target: { value: "FINISHED" } });
    expect(screen.queryByRole("button", { name: /Execution run-1234/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Execution finished/ })).toBeTruthy();
    expect(screen.getByText(/Selected execution is outside current filters/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Execution details" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "In progress" }));
    expect(screen.getByText("No visible executions match your search.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Reset search" }));
    expect(screen.getByRole("button", { name: /Execution run-1234/ }).getAttribute("aria-pressed")).toBe("true");
    expect(mocks.get.mock.calls.length).toBe(reads);
  });

  it("uses the canonical chat navigation for mission initiation", async () => {
    const onAskKaren = vi.fn();
    render(<AgentsPage onAskKaren={onAskKaren} />);
    await screen.findByText("No verified executions match this view.");
    fireEvent.click(screen.getByRole("button", { name: "Ask Karen" }));
    expect(onAskKaren).toHaveBeenCalledTimes(1);
    expect(mocks.post).not.toHaveBeenCalled();
  });


  it("provides a single authorized cancellation surface and real navigation targets", async () => {
    const fallback = mocks.get.getMockImplementation()!;
    const adminRun = { ...run, cancellable: true, user_id: "owner-evidence", policy_decision_id: "policy-evidence" };
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/admin/agents/runs?include_terminal=true") return Promise.resolve(history([adminRun]));
      if (path.endsWith("/" + run.run_id)) return Promise.resolve(adminRun);
      return fallback(path);
    });
    render(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    expect(screen.queryByText("Administrative execution diagnostics")).toBeNull();
    for (const name of ["Mission history", "Approvals", "Specialists", "Diagnostics"]) {
      const link = screen.getByRole("link", { name });
      const target = link.getAttribute("href");
      expect(target?.startsWith("#")).toBe(true);
      expect(document.getElementById(target!.slice(1))).not.toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByRole("button", { name: "Request cancellation" });
    expect(screen.getAllByRole("button", { name: "Request cancellation" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    fireEvent.click(screen.getByText("Technical details"));
    expect(screen.getByText("owner-evidence")).toBeTruthy();
    expect(screen.getByText("policy-evidence")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "My work" }));
    await screen.findByText("No verified executions match this view.");
    expect(screen.queryByText("owner-evidence")).toBeNull();
    expect(screen.queryByRole("button", { name: "Request cancellation" })).toBeNull();
  });


  it("retains an objective when no ready conversation accepts the handoff", async () => {
    render(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    const objective = screen.getByRole("textbox", { name: "Mission objective" }) as HTMLTextAreaElement;
    fireEvent.change(objective, { target: { value: "Prepare a verified report" } });
    fireEvent.click(screen.getByRole("button", { name: "Review objective" }));
    expect(screen.getByText(/Karen could not prepare the objective.*Your text is retained/).getAttribute("role")).toBe("alert");
    expect(objective.value).toBe("Prepare a verified report");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("hands off only reviewable user content and clears only after acknowledgement", async () => {
    const received = vi.fn();
    const listener = (event: Event) => {
      received((event as CustomEvent).detail);
      event.preventDefault();
    };
    window.addEventListener("karen:inject-message", listener);
    try {
      render(<AgentsPage />);
      await screen.findByText("No verified executions match this view.");
      const objective = screen.getByRole("textbox", { name: "Mission objective" }) as HTMLTextAreaElement;
      fireEvent.change(objective, { target: { value: "  Prepare a verified report  " } });
      fireEvent.click(screen.getByRole("button", { name: "Review objective" }));
      expect(received).toHaveBeenCalledTimes(1);
      expect(received).toHaveBeenCalledWith({ role: "user", content: "Prepare a verified report", autoSubmit: false });
      expect(objective.value).toBe("");
      fireEvent.click(screen.getByRole("button", { name: "Review objective" }));
      expect(received).toHaveBeenCalledTimes(1);
      expect(mocks.post).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("karen:inject-message", listener);
    }
  });

  it("does not retain personal objectives across execution scope or principal changes", async () => {
    const view = render(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    fireEvent.change(screen.getByRole("textbox", { name: "Mission objective" }), { target: { value: "Private objective" } });
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    expect(screen.queryByRole("textbox", { name: "Mission objective" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "My work" }));
    await screen.findByText("No verified executions match this view.");
    const input = screen.getByRole("textbox", { name: "Mission objective" }) as HTMLTextAreaElement;
    expect(input.value).toBe("");
    fireEvent.change(input, { target: { value: "Another private objective" } });
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
    view.rerender(<AgentsPage />);
    await screen.findByText("No verified executions match this view.");
    expect((screen.getByRole("textbox", { name: "Mission objective" }) as HTMLTextAreaElement).value).toBe("");
    expect(mocks.post).not.toHaveBeenCalled();
  });

});

 describe("ARM-05 recorded execution evidence", () => {
  it("separates execution completion from reported task outcome and uses recorded duration", async () => {
    const record = { ...run, status: "completed", outcome_status: "failed", started_at: "2026-11-25T00:00:00Z", completed_at: "2026-11-25T00:01:05Z" };
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => path === "/api/agent-runtime/my-runs" ? Promise.resolve(history([record])) : path.endsWith("/" + run.run_id) ? Promise.resolve(record) : fallback(path));
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Reported task outcome");
    expect(screen.getByText("failed", { exact: true })).toBeTruthy();
    expect(screen.getByText("1m 5s")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Recorded lifecycle timestamps" })).toBeTruthy();
    expect(screen.queryByText("Cancellation requested", { exact: true })).toBeNull();
  });
});


describe("ARM-05 durable transition timeline", () => {
  const event = { transition_id: "9007199254740995", from_status: null, to_status: "created", event_at: "2026-11-25T00:00:00Z", source: "migration_backfill" };
  const receipt = { run_id: run.run_id, transitions: [event], truncated: true, response_source: "postgres_durable_run_ledger" };
  const endpoint = "/api/agent-runtime/my-runs/" + run.run_id + "/transitions";
  function installTimeline(read: () => Promise<unknown>) {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/agent-runtime/my-runs" || path === "/api/admin/agents/runs?include_terminal=true") return Promise.resolve(history([run]));
      if (path === endpoint) return read();
      if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
      return fallback(path);
    });
  }
  it("validates provenance, identifiers, bounds and required fields", () => {
    expect(isRunTransitionsResponse(receipt)).toBe(true);
    for (const invalid of [
      { ...receipt, transitions: [event, event] },
      { ...receipt, transitions: [{ ...event, transition_id: 1 }] },
      { ...receipt, transitions: [{ ...event, source: "unknown" }] },
      { ...receipt, transitions: [{ ...event, to_status: "invented" }] },
      { ...receipt, transitions: [{ ...event, event_at: "invalid" }] },
      { ...receipt, transitions: [{ ...event, from_status: undefined }] },
      { ...receipt, transitions: [] },
      { ...receipt, transitions: Array.from({ length: 251 }, (_, i) => ({ ...event, transition_id: String(i + 1) })) },
      { ...receipt, response_source: "worker_local_execution" },
    ]) expect(isRunTransitionsResponse(invalid)).toBe(false);
  });
  it("displays recorded provenance and truncation instead of simulated progress", async () => {
    installTimeline(async () => receipt);
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Migration backfill (not an observed live event)");
    expect(screen.getByText(/earlier history is omitted/)).toBeTruthy();
    expect(mocks.get).toHaveBeenCalledWith(endpoint);
  });
  it("distinguishes verified empty history from a failed or mismatched response", async () => {
    let response: unknown = { ...receipt, transitions: [], truncated: false };
    installTimeline(async () => response);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("No durable transitions were recorded.");
    response = { ...receipt, run_id: "different-run" };
    view.unmount();
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText(/Recorded transition history is unavailable/);
    expect(screen.queryByText("No durable transitions were recorded.")).toBeNull();
  });
  it("does not request personal timeline in tenant administration", async () => {
    installTimeline(async () => receipt);
    render(<AgentsPage />);
    await screen.findByRole("button", { name: /Execution run-1234/ });
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Reported task outcome");
    expect(mocks.get).not.toHaveBeenCalledWith(endpoint);
    expect(screen.queryByRole("region", { name: "Recorded execution timeline" })).toBeNull();
  });
  it("discards delayed evidence after principal changes", async () => {
    const pending = deferred<unknown>();
    installTimeline(() => pending.promise);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Loading recorded transitions…");
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
    view.rerender(<AgentsPage />);
    await act(async () => { pending.resolve(receipt); });
    expect(screen.queryByText("Migration backfill (not an observed live event)")).toBeNull();
    expect(screen.queryByRole("region", { name: "Recorded execution timeline" })).toBeNull();
  });
});


describe("ARM-05C recorded specialist participation", () => {
  const endpoint = "/api/agent-runtime/my-runs/" + run.run_id + "/participation";
  const entry = { receipt_id: "11111111-1111-5111-8111-111111111111", step_id: "step-a", specialist_id: "researcher", phase: "started", observed_at: "2026-11-26T00:00:00.123456+00:00" };
  const interrupted = { ...entry, receipt_id: "22222222-2222-5222-8222-222222222222", phase: "interrupted" };
  const evidence = { run_id: run.run_id, evidence_status: "recorded", receipts: [entry, interrupted], truncated: true, response_source: "postgres_outcome_records" };

  function installParticipation(read: () => Promise<unknown>) {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/agent-runtime/my-runs" || path === "/api/admin/agents/runs?include_terminal=true") return Promise.resolve(history([run]));
      if (path === endpoint) return read();
      if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
      return fallback(path);
    });
  }

  it("validates scope shape, provenance, timestamps, phase consistency and bounded receipts", () => {
    expect(isRunParticipationResponse(evidence)).toBe(true);
    expect(isRunParticipationResponse({ ...evidence, evidence_status: "empty", receipts: [], truncated: false })).toBe(true);
    for (const invalid of [
      { ...evidence, evidence_status: "empty" },
      { ...evidence, receipts: [] },
      { ...evidence, response_source: "worker_local_execution" },
      { ...evidence, receipts: [entry, entry] },
      { ...evidence, receipts: [{ ...entry, receipt_id: "invalid" }] },
      { ...evidence, receipts: [{ ...entry, phase: "running" }] },
      { ...evidence, receipts: [{ ...entry, observed_at: "2026-11-26T00:00:00" }] },
      { ...evidence, receipts: [{ ...entry, specialist_id: "x".repeat(257) }] },
      { ...evidence, receipts: [entry, { ...interrupted, specialist_id: "other" }] },
      { ...evidence, receipts: [entry, { ...interrupted, phase: "skipped" }] },
      { ...evidence, receipts: [interrupted, { ...entry, phase: "completed" }] },
      { ...evidence, receipts: Array.from({ length: 101 }, () => entry) },
    ]) expect(isRunParticipationResponse(invalid)).toBe(false);
  });

  it("renders recorded entry, interruption, truncation and provenance without claiming completion", async () => {
    installParticipation(async () => evidence);
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("researcher · Invocation interrupted");
    expect(screen.getByText("researcher · Method entered")).toBeTruthy();
    expect(screen.getByText(/earlier receipts are omitted/)).toBeTruthy();
    expect(screen.getByText(/without a recorded terminal observation/)).toBeTruthy();
    expect(screen.queryByText("researcher · Invocation returned")).toBeNull();
    expect(mocks.get).toHaveBeenCalledWith(endpoint);
  });

  it("distinguishes a successful empty read from rejected or mismatched evidence", async () => {
    let response: unknown = { ...evidence, evidence_status: "empty", receipts: [], truncated: false };
    installParticipation(async () => response);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText(/No durable specialist participation was recorded/);
    response = { ...evidence, run_id: "other-run" };
    view.unmount();
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText(/Specialist participation evidence is unavailable/);
    expect(screen.queryByText(/No durable specialist participation was recorded/)).toBeNull();
  });

  it("clears old participation after a rejected refresh and recovers only from a fresh verified read", async () => {
    const empty = { ...evidence, evidence_status: "empty", receipts: [], truncated: false };
    const recovered = { ...evidence, truncated: false };
    let rejectOutage!: (error: Error) => void;
    const failingRead = () => new Promise<never>((_resolve, reject) => { rejectOutage = reject; });
    let reads = 0;
    installParticipation(() => {
      reads += 1;
      if (reads === 1) return Promise.resolve(evidence);
      if (reads === 2) return failingRead();
      if (reads === 3) return Promise.resolve(empty);
      return Promise.resolve(recovered);
    });
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("researcher · Invocation interrupted");

    const refresh = async () => {
      const button = screen.getByRole("button", { name: "Refresh runtime" }) as HTMLButtonElement;
      await waitFor(() => expect(button.disabled).toBe(false));
      fireEvent.click(button);
    };
    await refresh();
    await screen.findByText("Loading recorded participation…");
    expect(screen.queryByText("researcher · Invocation interrupted")).toBeNull();
    await act(async () => { rejectOutage(new Error("private database diagnostic")); });
    await screen.findByText("Specialist participation evidence is unavailable. Refresh runtime to retry.");
    expect(screen.queryByText(/No durable specialist participation was recorded/)).toBeNull();
    expect(screen.queryByText("private database diagnostic")).toBeNull();
    expect(screen.queryByText("researcher · Invocation interrupted")).toBeNull();

    await refresh();
    await screen.findByText(/No durable specialist participation was recorded/);
    expect(screen.queryByText(/Specialist participation evidence is unavailable/)).toBeNull();
    expect(screen.queryByText("researcher · Invocation interrupted")).toBeNull();

    await refresh();
    await screen.findByText("researcher · Invocation interrupted");
    expect(screen.queryByText(/No durable specialist participation was recorded/)).toBeNull();
    expect(screen.queryByText(/Specialist participation evidence is unavailable/)).toBeNull();
    expect(screen.queryByText(/earlier receipts are omitted/)).toBeNull();
    expect(reads).toBe(4);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("does not allow an older pending participation read to overwrite a newer refresh", async () => {
    const stale = deferred<unknown>();
    const fresh = { ...evidence, evidence_status: "empty", receipts: [], truncated: false };
    let reads = 0;
    installParticipation(() => ++reads === 1 ? stale.promise : Promise.resolve(fresh));
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Loading recorded participation…");
    expect(reads).toBe(1);
    const refresh = screen.getByRole("button", { name: "Refresh runtime" }) as HTMLButtonElement;
    await waitFor(() => expect(refresh.disabled).toBe(false));
    fireEvent.click(refresh);
    await screen.findByText(/No durable specialist participation was recorded/);
    expect(reads).toBe(2);
    await act(async () => { stale.resolve(evidence); });
    expect(screen.getByText(/No durable specialist participation was recorded/)).toBeTruthy();
    expect(screen.queryByText("researcher · Invocation interrupted")).toBeNull();
    expect(screen.queryByText(/earlier receipts are omitted/)).toBeNull();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("does not use the owner-only endpoint in tenant administration", async () => {
    installParticipation(async () => evidence);
    render(<AgentsPage />);
    await screen.findByRole("button", { name: /Execution run-1234/ });
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Reported task outcome");
    expect(mocks.get).not.toHaveBeenCalledWith(endpoint);
    expect(screen.queryByRole("region", { name: "Recorded specialist participation" })).toBeNull();
  });

  it("discards a delayed prior-principal receipt", async () => {
    const pending = deferred<unknown>();
    installParticipation(() => pending.promise);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Loading recorded participation…");
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: [] };
    view.rerender(<AgentsPage />);
    await act(async () => { pending.resolve(evidence); });
    expect(screen.queryByText("researcher · Invocation interrupted")).toBeNull();
    expect(screen.queryByRole("region", { name: "Recorded specialist participation" })).toBeNull();
  });
});


describe("ARM-05C.8D recorded governed tool evidence", () => {
  const endpoint = "/api/agent-runtime/my-runs/" + run.run_id + "/tool-receipts";
  const makeRow = (index: number) => {
    const tool_call_id = "00000000-0000-4000-8000-" + index.toString(16).padStart(12, "0");
    return {
      tool_call_id, receipt_id: "out_tool_" + tool_call_id.replace(/-/g, ""),
      tool_name: "web_search", tool_version: "1", agent_id: "researcher",
      step_id: "step-a", policy_decision_id: "policy-a", success: true,
      error_type: null, result_sha256: "a".repeat(64), recorded_at: "2026-11-26T00:00:00.123456+00:00",
      execution_scope: "tool_runtime_acknowledgment", independently_verified: false,
    };
  };
  const row = makeRow(1);
  const failure = { ...makeRow(2), tool_name: "lookup", success: false, error_type: "Timeout", result_sha256: null };
  const evidence = { run_id: run.run_id, evidence_status: "recorded", receipts: [row, failure],
    window_limit_reached: false, response_source: "postgres_outcome_records" };
  const empty = { ...evidence, evidence_status: "empty", receipts: [] };
  const full = { ...evidence, receipts: Array.from({ length: 100 }, (_, index) => makeRow(index + 1)),
    window_limit_reached: true };

  function install(read: () => Promise<unknown>) {
    const fallback = mocks.get.getMockImplementation()!;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/agent-runtime/my-runs" || path === "/api/admin/agents/runs?include_terminal=true") return Promise.resolve(history([run]));
      if (path === endpoint) return read();
      if (path.endsWith("/" + run.run_id)) return Promise.resolve(run);
      return fallback(path);
    });
  }

  it("admits only exact bounded owner-run acknowledgment contracts", () => {
    for (const valid of [evidence, empty, full]) expect(isRunToolReceiptsResponse(valid)).toBe(true);
    for (const invalid of [
      { ...evidence, payload: "private" }, { ...evidence, response_source: "worker" },
      { ...evidence, evidence_status: "empty" }, { ...empty, window_limit_reached: true },
      { ...full, window_limit_reached: false }, { ...full, receipts: [...full.receipts, makeRow(101)] },
      { ...evidence, receipts: [row, row] }, { ...evidence, receipts: [{ ...row, payload: "private" }] },
      { ...evidence, receipts: [{ ...row, receipt_id: "foreign" }] },
      { ...evidence, receipts: [{ ...row, tool_call_id: row.tool_call_id + "\n" }] },
      { ...evidence, receipts: [{ ...row, agent_id: null }] },
      { ...evidence, receipts: [{ ...row, success: "true" }] },
      { ...evidence, receipts: [{ ...row, error_type: "contradiction" }] },
      { ...evidence, receipts: [{ ...row, independently_verified: true }] },
      { ...evidence, receipts: [{ ...row, result_sha256: "x".repeat(64) }] },
      { ...evidence, receipts: [{ ...row, recorded_at: "2026-11-26T00:00:00" }] },
      { ...evidence, receipts: [{ ...row, recorded_at: row.recorded_at + "\n" }] },
    ]) expect(isRunToolReceiptsResponse(invalid)).toBe(false);
  });

  it("renders actual success and failure acknowledgments without claiming external success", async () => {
    install(async () => evidence);
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("web_search: Runtime acknowledged success");
    expect(screen.getByText("lookup: Runtime reported failure")).toBeTruthy();
    expect(screen.getByText("Error: Timeout")).toBeTruthy();
    expect(screen.getByText(/not independently confirmed external outcomes/)).toBeTruthy();
    expect(screen.getByText(/Result digest:/)).toBeTruthy();
    expect(mocks.get).toHaveBeenCalledWith(endpoint);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("labels a saturated bounded window without claiming complete evidence", async () => {
    install(async () => full);
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Receipt window limit reached; additional receipts may exist.");
    expect(screen.getAllByText("web_search: Runtime acknowledged success")).toHaveLength(100);
  });

  it("distinguishes empty, mismatched and failed evidence reads and removes stale receipts on refresh", async () => {
    let reads = 0;
    install(async () => {
      reads++;
      if (reads === 1) return evidence;
      if (reads === 2) throw new Error("private database diagnostic");
      if (reads === 3) return { ...evidence, run_id: "foreign" };
      return empty;
    });
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("web_search: Runtime acknowledged success");
    const refresh = async () => {
      const button = screen.getByRole("button", { name: "Refresh runtime" }) as HTMLButtonElement;
      await waitFor(() => expect(button.disabled).toBe(false));
      fireEvent.click(button);
    };
    for (let index = 2; index <= 3; index++) {
      await refresh();
      await waitFor(() => expect(reads).toBe(index));
      await screen.findByText("Governed tool evidence is unavailable. Refresh runtime to retry.");
      expect(screen.queryByText("private database diagnostic")).toBeNull();
      expect(screen.queryByText("web_search: Runtime acknowledged success")).toBeNull();
      expect(screen.queryByText(/No durable governed tool receipts were recorded/)).toBeNull();
    }
    await refresh();
    await screen.findByText(/No durable governed tool receipts were recorded/);
    expect(screen.queryByText(/Governed tool evidence is unavailable/)).toBeNull();
  });

  it("ignores delayed evidence from a prior refresh", async () => {
    const stale = deferred<unknown>();
    let reads = 0;
    install(() => ++reads === 1 ? stale.promise : Promise.resolve(empty));
    render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Loading governed tool receipts…");
    const refresh = screen.getByRole("button", { name: "Refresh runtime" }) as HTMLButtonElement;
    await waitFor(() => expect(refresh.disabled).toBe(false));
    fireEvent.click(refresh);
    await screen.findByText(/No durable governed tool receipts were recorded/);
    await act(async () => { stale.resolve(evidence); });
    expect(screen.queryByText("web_search: Runtime acknowledged success")).toBeNull();
    expect(screen.getByText(/No durable governed tool receipts were recorded/)).toBeTruthy();
  });

  it("discards delayed prior-principal evidence and never queries tenant administration", async () => {
    const pending = deferred<unknown>();
    install(() => pending.promise);
    const view = render(<AgentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Loading governed tool receipts…");
    mocks.user = { tenant_id: "tenant-B", user_id: "user-B", roles: ["admin"] };
    view.rerender(<AgentsPage />);
    await act(async () => { pending.resolve(evidence); });
    expect(screen.queryByText("web_search: Runtime acknowledged success")).toBeNull();
    expect(screen.queryByRole("region", { name: "Recorded governed tool receipts" })).toBeNull();
    mocks.get.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Tenant administration" }));
    fireEvent.click(await screen.findByRole("button", { name: /Execution run-1234/ }));
    await screen.findByText("Reported task outcome");
    expect(mocks.get).not.toHaveBeenCalledWith(endpoint);
    expect(screen.queryByRole("region", { name: "Recorded governed tool receipts" })).toBeNull();
  });
});
