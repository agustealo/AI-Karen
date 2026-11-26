// @vitest-environment jsdom
import React from "react";
import { act, cleanup, fireEvent, render as renderWithTestingLibrary, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const stubs = vi.hoisted(() => ({
  get: vi.fn(),
  approvalGet: vi.fn(),
  approvalPost: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: stubs.get },
  apiClient: { get: stubs.approvalGet, post: stubs.approvalPost },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));
vi.mock("@/lib/useAuth", () => ({ useAuth: stubs.useAuth, default: stubs.useAuth }));

import CommsCenterPage from "./CommsCenterPage";
import { RuntimeApprovalProvider } from "@/components/approvals/RuntimeApprovalProvider";
import { ApprovalReviewPanel } from "@/components/approvals/ApprovalReviewPanel";

const render = (ui: React.ReactElement) => renderWithTestingLibrary(ui, { wrapper: RuntimeApprovalProvider });

const FIRST_PRINCIPAL = { tenant_id: "tenant-one", user_id: "user-one" };

const LIVE_SNAPSHOT = {
  generated_at: "2026-11-18T16:00:00Z",
  audit: {
    recent_events: [
      { message: "Verified backend audit receipt", event_type: "system.audit", timestamp: "2026-11-18T15:59:00Z" },
    ],
    event_counts: { "system.audit": 1 },
  },
  training: { event_counts: { accepted: 2 }, security_events: [] },
  memory: {
    available: true,
    pending_writebacks: 0,
    active_shard_links: 3,
    feedback_metrics: {},
    service_metrics: {},
  },
  alerts: [
    { id: "alert-1", title: "Verified backend alert", description: "Live event", type: "info", timestamp: "2026-11-18T15:58:00Z" },
  ],
};

beforeEach(() => {
  stubs.get.mockReset();
  stubs.approvalGet.mockReset().mockResolvedValue([]);
  stubs.approvalPost.mockReset();
  stubs.useAuth.mockReset();
  stubs.useAuth.mockReturnValue({
    isLoading: false,
    isAuthenticated: true,
    user: FIRST_PRINCIPAL,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Communications Center's canonical visual and authority contract", () => {
  it("uses the shared depth system, accessible icons and responsive navigation", async () => {
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    const { container } = render(<CommsCenterPage />);

    expect(screen.getByRole("heading", { name: "Your communications & activity" })).toBeTruthy();
    expect(container.querySelector('[data-testid="comms-center"] .karen-surface')).toBeTruthy();
    expect(container.querySelector('[data-testid="comms-center"][data-kari-root]')).toBeTruthy();
    expect(container.querySelector('[data-testid="comms-center"] .kari-display')).toBeTruthy();
    const nav = container.querySelector('[aria-label="Communications Center sections"]');
    expect(nav?.className).toContain("overflow-x-auto");
    expect(nav?.querySelectorAll('svg[aria-hidden="true"]').length).toBe(7);
    expect(screen.getByRole("tab", { name: "Inbox" })).toBeTruthy();
    expect(screen.queryByText("svgOverview")).toBeNull();

    await waitFor(() => {
      expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("1");
    });
    expect(screen.getByTestId("comms-metric-alerts").textContent?.trim()).toBe("1");
    expect(screen.getByTestId("comms-metric-writebacks").textContent?.trim()).toBe("0");
    expect(screen.getByTestId("comms-metric-training").textContent?.trim()).toBe("2");
    expect(screen.getByText("Verified backend audit receipt")).toBeTruthy();
    expect(screen.getByText("Verified backend alert")).toBeTruthy();
    expect(stubs.get).toHaveBeenCalledWith("/api/communications-center/observability");
  });

  it("shows unavailable instead of invented zeroes after a network failure", async () => {
    stubs.get.mockRejectedValue(new Error("Observability endpoint unavailable"));
    render(<CommsCenterPage />);

    await waitFor(() => {
      expect(screen.getByText(/Live observability is unavailable/)).toBeTruthy();
      expect(screen.queryByText(/Observability endpoint unavailable/)).toBeNull();
    });
    expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("—");
    expect(screen.getByTestId("comms-metric-writebacks").textContent?.trim()).toBe("—");
    expect(screen.getByText("Audit activity not available")).toBeTruthy();
    expect(screen.queryByText("Verified backend audit receipt")).toBeNull();
  });

  it("rejects an incomplete backend contract", async () => {
    stubs.get.mockResolvedValue({ audit: { recent_events: [] } });
    render(<CommsCenterPage />);

    await waitFor(() => {
      expect(screen.getByText(/did not match the backend contract/)).toBeTruthy();
    });
    expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("—");
  });

  it("does not render a previous account's telemetry after principal change", async () => {
    stubs.get.mockResolvedValueOnce(LIVE_SNAPSHOT);
    stubs.get.mockImplementationOnce(() => new Promise(() => {}));
    const { rerender } = render(<CommsCenterPage />);

    await waitFor(() => {
      expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("1");
    });
    stubs.useAuth.mockReturnValue({
      isLoading: false,
      isAuthenticated: true,
      user: { tenant_id: "tenant-two", user_id: "user-two" },
    });
    rerender(<CommsCenterPage />);
    expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("—");
    expect(screen.queryByText("Verified backend audit receipt")).toBeNull();
  });

  it("never converts missing scoped queue metrics to healthy zeroes", async () => {
    stubs.get.mockResolvedValue({
      ...LIVE_SNAPSHOT,
      memory: { ...LIVE_SNAPSHOT.memory, available: false, pending_writebacks: 0, active_shard_links: 0 },
    });
    render(<CommsCenterPage />);
    await waitFor(() => {
      expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("1");
    });
    expect(screen.getByTestId("comms-metric-writebacks").textContent?.trim()).toBe("—");
    // Exercise the Radix keyboard activation contract in jsdom. Synthetic
    // pointer events do not implement the full browser PointerEvent contract.
    const observabilityTab = screen.getByRole("tab", { name: "Observability" });
    observabilityTab.focus();
    fireEvent.keyDown(observabilityTab, { key: "Enter", code: "Enter" });
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Observability" }).getAttribute("data-state")).toBe("active");
      expect(screen.getByTestId("comms-observability-pending").textContent?.trim()).toBe("—");
      expect(screen.getByTestId("comms-observability-shards").textContent?.trim()).toBe("—");
    });
    expect(screen.getByText("Account-scoped queue metrics")).toBeTruthy();
    expect(screen.getByText("Not verified")).toBeTruthy();
  });

  it("shows only owner-verified execution receipts from canonical Medusa history", async () => {
    stubs.get.mockImplementation(async (path: string) => {
      if (path === "/api/communications-center/observability") return LIVE_SNAPSHOT;
      if (path === "/api/agent-runtime/my-runs") return {
        runs: [{ run_id: "owned-run-001", user_id: "user-one", tenant_id: "tenant-one", status: "completed", started_at: "2026-11-18T15:00:00Z" }],
        total: 1, generated_at: "2026-11-18T16:00:00Z",
      };
      throw new Error("Unexpected endpoint");
    });
    render(<CommsCenterPage />);

    await waitFor(() => expect(screen.getByText("Execution owned-ru")).toBeTruthy());
    expect(screen.getByTestId("comms-owned-run-count").textContent).toContain("1 recorded");
    expect(stubs.get).toHaveBeenCalledWith("/api/agent-runtime/my-runs");
    expect(stubs.get).not.toHaveBeenCalledWith("/api/agent-runs/");
    expect(screen.getByText(/does not imply an independently verified result/)).toBeTruthy();
  });

  it("denies an entire malformed run response containing another owner's execution", async () => {
    stubs.get.mockImplementation(async (path: string) => {
      if (path === "/api/communications-center/observability") return LIVE_SNAPSHOT;
      return {
        runs: [
          { run_id: "my-safe-run", user_id: "user-one", tenant_id: "tenant-one", status: "completed" },
          { run_id: "other-user-secret-run", user_id: "user-two", tenant_id: "tenant-one", status: "completed" },
        ],
        total: 2, generated_at: "2026-11-18T16:00:00Z",
      };
    });
    render(<CommsCenterPage />);
    await waitFor(() => expect(screen.getByText("Owner-verified agent execution history is unavailable.")).toBeTruthy());
    expect(screen.getByTestId("comms-owned-run-count").textContent).toContain("Unverified");
    expect(screen.queryByText(/my-safe-run/)).toBeNull();
    expect(screen.queryByText(/other-user-secret-run/)).toBeNull();
  });

  it("rejects a foreign tenant even when the user identifier matches", async () => {
    stubs.get.mockImplementation(async (path: string) => {
      if (path === "/api/communications-center/observability") return LIVE_SNAPSHOT;
      if (path === "/api/agent-runtime/my-runs") return {
        runs: [
          { run_id: "valid-same-user-run", user_id: "user-one", tenant_id: "tenant-one", status: "completed" },
          { run_id: "cross-tenant-sensitive-run", user_id: "user-one", tenant_id: "tenant-two", status: "completed" },
        ],
        total: 2, generated_at: "2026-11-18T16:00:00Z",
      };
      throw new Error("Unexpected API request");
    });
    render(<CommsCenterPage />);
    await waitFor(() => expect(screen.getByText("Owner-verified agent execution history is unavailable.")).toBeTruthy());
    expect(screen.getByTestId("comms-owned-run-count").textContent).toContain("Unverified");
    expect(screen.queryByText(/Execution valid-sa/)).toBeNull();
    expect(screen.queryByText(/Execution cross-te/)).toBeNull();
  });

  it("does not display the previous account's execution history after identity changes", async () => {
    let finishSecondRequest!: (value: unknown) => void;
    stubs.get.mockImplementation((path: string) => {
      if (path === "/api/communications-center/observability") return Promise.resolve(LIVE_SNAPSHOT);
      if (stubs.useAuth().user.user_id === "user-one") return Promise.resolve({
        runs: [{ run_id: "private-owner-run", user_id: "user-one", tenant_id: "tenant-one", status: "running" }],
        total: 1, generated_at: "2026-11-18T16:00:00Z",
      });
      return new Promise((resolve) => { finishSecondRequest = resolve; });
    });
    const { rerender } = render(<CommsCenterPage />);
    await waitFor(() => expect(screen.getByText("Execution private-")).toBeTruthy());
    stubs.useAuth.mockReturnValue({
      isLoading: false, isAuthenticated: true,
      user: { tenant_id: "tenant-two", user_id: "user-two" },
    });
    rerender(<CommsCenterPage />);
    expect(screen.queryByText("Execution private-")).toBeNull();
    expect(screen.getByTestId("comms-owned-run-count").textContent).toContain("Unverified");
    expect(finishSecondRequest).toBeTypeOf("function");
  });

  it("projects returned execution and warning counts and delegates actions to existing workspaces", async () => {
    const onOpenAgents = vi.fn();
    const onOpenTasks = vi.fn();
    const onOpenChat = vi.fn();
    stubs.get.mockImplementation(async (path: string) => {
      if (path === "/api/communications-center/observability") return {
        ...LIVE_SNAPSHOT,
        alerts: [...LIVE_SNAPSHOT.alerts, { id: "warning-1", title: "Scoped warning", description: "Verified warning", type: "warning", timestamp: "2026-11-18T15:58:00Z" }],
      };
      if (path === "/api/agent-runtime/my-runs") return {
        runs: ["failed", "orphaned", "queued", "cancelling", "completed"].map((status, index) => ({
          run_id: "owned-" + index, user_id: "user-one", tenant_id: "tenant-one", status,
        })),
        total: 20, generated_at: "2026-11-18T16:00:00Z",
      };
      throw new Error("Unexpected endpoint");
    });
    render(<CommsCenterPage {...{ onOpenAgents, onOpenTasks, onOpenChat }} />);
    await waitFor(() => {
      expect(screen.getByTestId("comms-attention-runs").textContent?.trim()).toBe("2");
      expect(screen.getByTestId("comms-active-runs").textContent?.trim()).toBe("2");
      expect(screen.getByTestId("comms-warning-count").textContent?.trim()).toBe("1");
    });
    expect(screen.getByText(/returned records only, not a complete inbox/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open approval workspace" }));
    fireEvent.click(screen.getByRole("button", { name: "Inspect executions" }));
    fireEvent.click(screen.getByRole("button", { name: "Open my tasks" }));
    fireEvent.click(screen.getByRole("button", { name: "Return to Karen" }));
    expect(onOpenAgents).toHaveBeenCalledTimes(2);
    expect(onOpenTasks).toHaveBeenCalledTimes(1);
    expect(onOpenChat).toHaveBeenCalledTimes(1);
  });

  it("conceals snapshots and disables navigation during authentication revalidation or loss", async () => {
    stubs.get.mockImplementation(async (path: string) => {
      if (path === "/api/communications-center/observability") return LIVE_SNAPSHOT;
      return { runs: [{ run_id: "private-run", user_id: "user-one", tenant_id: "tenant-one", status: "failed" }], total: 1, generated_at: "2026-11-18T16:00:00Z" };
    });
    const onOpenAgents = vi.fn();
    const { rerender } = render(<CommsCenterPage onOpenAgents={onOpenAgents} />);
    await waitFor(() => expect(screen.getByTestId("comms-attention-runs").textContent?.trim()).toBe("1"));
    stubs.useAuth.mockReturnValue({ isLoading: true, isAuthenticated: true, user: FIRST_PRINCIPAL });
    rerender(<CommsCenterPage onOpenAgents={onOpenAgents} />);
    expect(screen.getByTestId("comms-attention-runs").textContent?.trim()).toBe("—");
    expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("—");
    expect(screen.queryByText("Verified backend audit receipt")).toBeNull();
    // Revalidation of the same identity must wait for new authorized records.
    stubs.get.mockImplementation(() => new Promise(() => {}));
    stubs.useAuth.mockReturnValue({ isLoading: false, isAuthenticated: true, user: FIRST_PRINCIPAL });
    rerender(<CommsCenterPage onOpenAgents={onOpenAgents} />);
    expect(screen.getByTestId("comms-attention-runs").textContent?.trim()).toBe("—");
    expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("—");
    expect(screen.queryByText("Verified backend audit receipt")).toBeNull();
    stubs.useAuth.mockReturnValue({ isLoading: false, isAuthenticated: false, user: FIRST_PRINCIPAL });
    rerender(<CommsCenterPage onOpenAgents={onOpenAgents} />);
    expect(screen.getByTestId("comms-attention-runs").textContent?.trim()).toBe("—");
    expect((screen.getByRole("button", { name: "Open approval workspace" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText("Verified backend audit receipt")).toBeNull();
  });

  it("reviews and records a decision inside Communications through the canonical provider", async () => {
    const approval = { approval_id: "approval-1", workflow_kind: "runtime_approval", intent: "Review verified operation", risk_level: "high", status: "pending", reason_codes: [], expires_at: "2099-01-01T00:00:00Z", conversation_id: "conversation-1" };
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    stubs.approvalGet.mockResolvedValueOnce([approval]).mockResolvedValue([{ ...approval, status: "approved" }]);
    stubs.approvalPost.mockResolvedValue({ ...approval, status: "approved" });
    const onOpenConversation = vi.fn().mockResolvedValue(undefined);
    render(<CommsCenterPage onOpenConversation={onOpenConversation} />);
    await waitFor(() => expect(screen.getByTestId("comms-pending-decisions").textContent).toContain("1 pending"));
    fireEvent.click(screen.getByRole("button", { name: "Review decisions" }));
    const inbox = screen.getByTestId("comms-decisions-inbox");
    fireEvent.click(within(inbox).getByRole("button", { name: "Open original conversation" }));
    expect(onOpenConversation).toHaveBeenCalledExactlyOnceWith("conversation-1");
    fireEvent.click(within(inbox).getByRole("button", { name: "Review approval" }));
    expect(stubs.approvalPost).not.toHaveBeenCalled();
    fireEvent.click(within(inbox).getByRole("button", { name: "Confirm approval" }));
    await within(inbox).findByText(/Decision recorded: approved/);
    expect(stubs.approvalPost).toHaveBeenCalledExactlyOnceWith("/api/approvals/approval-1/decision", { decision: "approved" });
    await waitFor(() => expect(within(inbox).queryByRole("button", { name: "Review approval" })).toBeNull());
    expect(within(inbox).getByText("Decision recorded. Execution is not implied.")).toBeTruthy();
  });

  it("keeps one decision lock and reconciles an uncertain outcome across review surfaces", async () => {
    const approval = { approval_id: "approval-1", workflow_kind: "runtime_approval", intent: "Review verified operation", risk_level: "high", status: "pending", reason_codes: [], expires_at: "2099-01-01T00:00:00Z" };
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    stubs.approvalGet.mockResolvedValue([approval]);
    let rejectDecision!: (error: Error) => void;
    stubs.approvalPost.mockReturnValue(new Promise((_resolve, reject) => { rejectDecision = reject; }));
    const view = render(<CommsCenterPage />);
    fireEvent.click(screen.getByRole("button", { name: "Review decisions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Review approval" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));
    view.rerender(<ApprovalReviewPanel id="mission-approvals" testId="agent-runtime-approvals" isAuthenticated showRefresh />);
    const review = await screen.findByRole("button", { name: "Review approval" }) as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    fireEvent.click(review);
    expect(stubs.approvalPost).toHaveBeenCalledTimes(1);
    expect(stubs.approvalGet).toHaveBeenCalledTimes(1);
    await act(async () => { rejectDecision(new Error("Lost response")); });
    expect(screen.getByText(/Decision outcome could not be verified/)).toBeTruthy();
    view.rerender(<CommsCenterPage />);
    fireEvent.click(screen.getByRole("button", { name: "Review decisions" }));
    const inbox = screen.getByTestId("comms-decisions-inbox");
    expect((within(inbox).getByRole("button", { name: "Review approval" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(inbox).getByRole("button", { name: "Refresh decisions" }));
    await waitFor(() => expect((within(inbox).getByRole("button", { name: "Review approval" }) as HTMLButtonElement).disabled).toBe(false));
    expect(stubs.approvalGet).toHaveBeenCalledTimes(2);
    expect(stubs.approvalPost).toHaveBeenCalledTimes(1);
  });

  it("fails closed on an unverified approval list", async () => {
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    stubs.approvalGet.mockResolvedValue([{ approval_id: "private", intent: "Unverified operation" }]);
    render(<CommsCenterPage />);
    fireEvent.click(screen.getByRole("button", { name: "Review decisions" }));
    await screen.findByText("Could not load approval requests.");
    expect(screen.queryByText("Unverified operation")).toBeNull();
    expect(screen.queryByText(/No actionable approval requests/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Review approval" })).toBeNull();
  });

  it("fetches a fresh snapshot after an explicit Refresh click", async () => {
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    render(<CommsCenterPage />);

    await waitFor(() => {
      expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("1");
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      const observabilityRequests = stubs.get.mock.calls.filter(
        ([path]) => path === "/api/communications-center/observability",
      );
      expect(observabilityRequests).toHaveLength(2);
    });
  });
});
