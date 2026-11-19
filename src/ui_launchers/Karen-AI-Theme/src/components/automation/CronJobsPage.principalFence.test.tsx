import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  currentUser: { tenant_id: "tenant-A", user_id: "user-A" },
  authenticated: true,
  get: vi.fn(),
}));

vi.mock("@/lib/useAuth", () => ({
  default: () => ({
    isAuthenticated: mocks.authenticated,
    isLoading: false,
    user: mocks.currentUser,
  }),
}));

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  apiClient: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

import CronJobsPage from "./CronJobsPage";

interface TestSchedule {
  id: string;
  name: string;
  schedule: string;
  target_id: string;
  type: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  taskName: string;
}

function schedule(name: string): TestSchedule[] {
  return [{
    id: name,
    name,
    schedule: "0 9 * * *",
    target_id: name,
    type: "Task",
    enabled: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    taskName: name,
  }];
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.authenticated = true;
  mocks.currentUser = { tenant_id: "tenant-A", user_id: "user-A" };
});

afterEach(cleanup);

describe("Cron schedule principal isolation", () => {
  it("does not reuse or render a prior principal's delayed schedule response", async () => {
    const first = deferred<TestSchedule[]>();
    const second = deferred<TestSchedule[]>();
    let scheduleReads = 0;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/automation/cron") {
        scheduleReads += 1;
        return scheduleReads === 1 ? first.promise : second.promise;
      }
      if (path === "/api/tasks" || path === "/api/automation/jobs") {
        return Promise.resolve([]);
      }
      throw new Error("Unexpected URL " + path);
    });

    const view = render(<CronJobsPage />);
    await waitFor(() => expect(scheduleReads).toBe(1));

    mocks.currentUser = { tenant_id: "tenant-B", user_id: "user-B" };
    view.rerender(<CronJobsPage />);
    await waitFor(() => expect(scheduleReads).toBe(2));

    await act(async () => { first.resolve(schedule("previous-principal-schedule")); });
    expect(screen.queryByText("previous-principal-schedule")).toBeNull();
    expect(screen.getByText("Loading scheduled jobs from backend...")).toBeTruthy();

    await act(async () => { second.resolve(schedule("current-principal-schedule")); });
    expect(await screen.findByText("current-principal-schedule")).toBeTruthy();
    expect(screen.queryByText("previous-principal-schedule")).toBeNull();
  });

  it("never reports a signed-out schedule list as verified empty", async () => {
    mocks.authenticated = false;
    mocks.get.mockImplementation(() => {
      throw new Error("An unauthenticated page must not load workflow data");
    });
    render(<CronJobsPage />);
    expect(await screen.findByText("Sign in to view scheduled jobs.")).toBeTruthy();
    expect(screen.queryByText("No cron jobs configured yet.")).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
