import React from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  put: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiClient: backend,
  ApiError: class ApiError extends Error {
    status: number;
    details: unknown;
    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
      this.details = null;
    }
  },
}));

import {
  SessionProvider,
  useSession,
  type SessionDeletionOutcome,
} from "@/components/chat/SessionProvider";

const FIRST = "b62e6b63-bd18-45d5-81bb-107c6bebc3c0";
const created = "2026-10-31T12:00:00.000Z";
const firstConversation = {
  id: FIRST,
  title: "Existing conversation",
  created_at: created,
  updated_at: created,
  session_id: FIRST,
  messages: [],
};
const staleList = {
  conversations: [{ ...firstConversation, message_count: 0 }],
  total_count: 1,
  has_more: false,
};

let provider: ReturnType<typeof useSession> | null = null;
function Probe() {
  provider = useSession();
  return <output data-testid="session-id">{provider.currentSession?.id ?? "none"}</output>;
}

beforeEach(() => {
  provider = null;
  window.localStorage.clear();
  backend.get.mockReset().mockImplementation(async (path: string) => {
    if (path === `/api/conversations/${FIRST}`) return firstConversation;
    if (path === "/api/conversations") return staleList;
    throw new Error(`Unexpected GET ${path}`);
  });
  backend.post.mockReset().mockRejectedValue(new Error("Replacement unavailable"));
  backend.delete.mockReset().mockResolvedValue({});
  backend.put.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("canonical SessionProvider deletion outcomes", () => {
  it("keeps server-deleted conversations absent despite stale history and reports failed replacement", async () => {
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));

    let outcome: SessionDeletionOutcome | undefined;
    await act(async () => {
      outcome = await provider!.deleteSessionWithOutcome(FIRST);
    });

    expect(backend.delete).toHaveBeenCalledWith(`/api/conversations/${FIRST}`);
    expect(outcome).toEqual({
      deleted: true,
      replacementCreated: false,
      historyRefreshed: true,
    });
    expect(provider?.currentSession).toBeNull();
    expect(provider?.sessions.some(session => session.id === FIRST)).toBe(false);
    expect(provider?.error).toContain("Conversation deleted");
    expect(window.localStorage.getItem("karen.active_session_id")).toBeNull();
  });

  it("does not replace the last verified conversation after an unverified navigation", async () => {
    const missing = "73935a82-bdf1-4d43-97a1-2b7c708b549d";
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));

    backend.get.mockImplementation(async (path: string) => {
      if (path === `/api/conversations/${missing}`) {
        throw new Error("Temporary backend outage");
      }
      if (path === "/api/conversations") return staleList;
      if (path === `/api/conversations/${FIRST}`) return firstConversation;
      throw new Error(`Unexpected GET ${path}`);
    });

    let verified: boolean | undefined;
    await act(async () => {
      verified = await provider!.loadSession(missing);
    });

    expect(verified).toBe(false);
    expect(provider?.currentSession?.id).toBe(FIRST);
    expect(backend.post).not.toHaveBeenCalled();
    expect(provider?.error).toContain("last verified conversation");
  });

  it("reports a refresh outage separately from a server-confirmed deletion", async () => {
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));
    backend.get.mockImplementation(async (path: string) => {
      if (path === "/api/conversations") throw new Error("History service unavailable");
      if (path === `/api/conversations/${FIRST}`) return firstConversation;
      throw new Error(`Unexpected GET ${path}`);
    });

    let outcome: SessionDeletionOutcome | undefined;
    await act(async () => {
      outcome = await provider!.deleteSessionWithOutcome(FIRST);
    });

    expect(outcome).toEqual({
      deleted: true,
      replacementCreated: false,
      historyRefreshed: false,
    });
    expect(provider?.currentSession).toBeNull();
    expect(provider?.sessions.some(session => session.id === FIRST)).toBe(false);
    expect(provider?.error).toContain("Conversation deleted");
  });

  it("never claims successful deletion when the server rejects the delete", async () => {
    backend.delete.mockRejectedValue(new Error("Server rejected deletion"));
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));

    let outcome: SessionDeletionOutcome | undefined;
    await act(async () => {
      outcome = await provider!.deleteSessionWithOutcome(FIRST);
    });

    expect(outcome).toEqual({
      deleted: false,
      replacementCreated: null,
      historyRefreshed: null,
    });
    expect(provider?.currentSession?.id).toBe(FIRST);
    expect(provider?.sessions.some(session => session.id === FIRST)).toBe(true);
  });
});
