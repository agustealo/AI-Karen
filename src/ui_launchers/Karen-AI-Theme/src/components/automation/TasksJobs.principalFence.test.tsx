import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  principal: { tenant_id: "tenant-A", user_id: "user-A" },
  authenticated: true,
  get: vi.fn(),
}));

vi.mock("@/lib/useAuth", () => ({
  default: () => ({
    isAuthenticated: mocks.authenticated,
    isLoading: false,
    user: mocks.principal,
  }),
}));

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: (...args: unknown[]) => mocks.get(...args),
    post: vi.fn(),
    delete: vi.fn(),
    put: vi.fn(),
  },
}));

import TasksPage from "./TasksPage";
import JobsPage from "./JobsPage";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.authenticated = true;
  mocks.principal = { tenant_id: "tenant-A", user_id: "user-A" };
});

afterEach(cleanup);

describe("KARI OS task and job principal isolation", () => {
  it("rejects delayed previous-principal task and catalog results", async () => {
    const oldTasks = deferred<Array<{ id: string; name: string }>>();
    const nextTasks = deferred<Array<{ id: string; name: string }>>();
    let reads = 0;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/tasks/") {
        reads += 1;
        return reads === 1 ? oldTasks.promise : nextTasks.promise;
      }
      if (path === "/api/agent-runtime/catalog") return Promise.resolve({ agents: [] });
      throw new Error("Unexpected task URL: " + path);
    });
    const view = render(<TasksPage />);
    await waitFor(() => expect(reads).toBe(1));

    mocks.principal = { tenant_id: "tenant-B", user_id: "user-B" };
    view.rerender(<TasksPage />);
    await waitFor(() => expect(reads).toBe(2));

    await act(async () => { oldTasks.resolve([{ id: "old", name: "Account A task" }]); });
    expect(screen.queryByText("Account A task")).toBeNull();
    await act(async () => { nextTasks.resolve([{ id: "new", name: "Account B task" }]); });
    expect(await screen.findByText("Account B task")).toBeTruthy();
    expect(screen.queryByText("Account A task")).toBeNull();
  });

  it("rejects delayed previous-principal jobs and task-selector results", async () => {
    const oldJobs = deferred<Array<{ id: string; name: string; description: string }>>();
    const nextJobs = deferred<Array<{ id: string; name: string; description: string }>>();
    const oldTasks = deferred<Array<{ id: string; name: string }>>();
    const nextTasks = deferred<Array<{ id: string; name: string }>>();
    let jobReads = 0;
    let taskReads = 0;
    mocks.get.mockImplementation((path: string) => {
      if (path === "/api/automation/jobs/") {
        jobReads += 1;
        return jobReads === 1 ? oldJobs.promise : nextJobs.promise;
      }
      if (path === "/api/tasks/") {
        taskReads += 1;
        return taskReads === 1 ? oldTasks.promise : nextTasks.promise;
      }
      throw new Error("Unexpected job URL: " + path);
    });
    const view = render(<JobsPage />);
    await waitFor(() => expect(jobReads).toBe(1));
    await waitFor(() => expect(taskReads).toBe(1));

    mocks.principal = { tenant_id: "tenant-B", user_id: "user-B" };
    view.rerender(<JobsPage />);
    await waitFor(() => expect(jobReads).toBe(2));
    await waitFor(() => expect(taskReads).toBe(2));

    await act(async () => {
      oldJobs.resolve([{ id: "old", name: "Account A job", description: "Old only" }]);
      oldTasks.resolve([{ id: "old", name: "Account A selector task" }]);
    });
    expect(screen.queryByText("Account A job")).toBeNull();
    expect(screen.queryByText("Account A selector task")).toBeNull();
    await act(async () => {
      nextJobs.resolve([{ id: "next", name: "Account B job", description: "Current only" }]);
      nextTasks.resolve([{ id: "next", name: "Account B selector task" }]);
    });
    expect(await screen.findByText("Account B job")).toBeTruthy();
    expect(screen.queryByText("Account A job")).toBeNull();
    expect(screen.queryByText("Account A selector task")).toBeNull();
  });
});
