// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const stubs = vi.hoisted(() => ({
  get: vi.fn(),
  useAuth: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: stubs.get },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  },
}));
vi.mock("@/lib/useAuth", () => ({ useAuth: stubs.useAuth }));

import CommsCenterPage from "./CommsCenterPage";

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

    expect(screen.getByRole("heading", { name: "Activity & Notifications" })).toBeTruthy();
    expect(container.querySelector('[data-testid="comms-center"] .karen-surface')).toBeTruthy();
    const nav = container.querySelector('[aria-label="Communications Center sections"]');
    expect(nav?.className).toContain("overflow-x-auto");
    expect(nav?.querySelectorAll('svg[aria-hidden="true"]').length).toBe(5);
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
      expect(screen.getByText(/Observability endpoint unavailable/)).toBeTruthy();
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

  it("fetches a fresh snapshot after an explicit Refresh click", async () => {
    stubs.get.mockResolvedValue(LIVE_SNAPSHOT);
    render(<CommsCenterPage />);

    await waitFor(() => {
      expect(screen.getByTestId("comms-metric-audit").textContent?.trim()).toBe("1");
    });
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(stubs.get).toHaveBeenCalledTimes(2));
  });
});
