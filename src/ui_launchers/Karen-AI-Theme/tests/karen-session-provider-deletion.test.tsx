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

import { ApiError } from "@/lib/api";

import {
  SessionProvider,
  useSession,
  fetchConversationBootstrap,
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
  it("reauthorizes a conversation after an account transition instead of serving module cache", async () => {
    const firstRead = await fetchConversationBootstrap(FIRST);
    expect(firstRead.id).toBe(FIRST);
    const previousGetCount = backend.get.mock.calls.length;

    // A second principal is not authorized for the first principal's thread.
    backend.get.mockRejectedValue(new Error("Forbidden for current principal"));
    await expect(fetchConversationBootstrap(FIRST)).rejects.toThrow(
      "Forbidden for current principal",
    );
    expect(backend.get).toHaveBeenCalledTimes(previousGetCount + 1);
  });

  it("bootstraps each new provider mount even when the same session was just mounted", async () => {
    const first = render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));
    first.unmount();
    provider = null;

    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));
    expect(backend.get).toHaveBeenCalledWith("/api/conversations");
  });

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
    const loadCountBefore = backend.get.mock.calls.filter(
      ([path]) => path === `/api/conversations/${FIRST}`,
    ).length;
    let reopened: boolean | undefined;
    await act(async () => {
      reopened = await provider!.loadSession(FIRST);
    });
    expect(reopened).toBe(false);
    expect(provider?.currentSession).toBeNull();
    expect(provider?.error).toContain("deleted");
    expect(backend.get.mock.calls.filter(
      ([path]) => path === `/api/conversations/${FIRST}`,
    )).toHaveLength(loadCountBefore);
  });

  it("rejects mismatched server conversation identity without switching threads", async () => {
    const requested = "1778439a-3ca2-462a-8ed6-5566b1960bc7";
    const unrelated = "be41b2f8-60a8-470b-b868-824d9ca24c01";
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));
    backend.get.mockImplementation(async (path: string) => {
      if (path === `/api/conversations/${requested}`) {
        return { ...firstConversation, id: unrelated, session_id: unrelated };
      }
      if (path === `/api/conversations/${FIRST}`) return firstConversation;
      if (path === "/api/conversations") return staleList;
      throw new Error(`Unexpected GET ${path}`);
    });
    let verified: boolean | undefined;
    await act(async () => { verified = await provider!.loadSession(requested); });
    expect(verified).toBe(false);
    expect(provider?.currentSession?.id).toBe(FIRST);
    expect(window.localStorage.getItem("karen.active_session_id")).toBe(FIRST);
  });

  it("accepts a legacy session alias only when the returned session_id matches", async () => {
    const legacy = "d565c10d-3caf-486d-85ac-ff21bda19c52";
    const canonical = "f0dfb9fd-7950-4e12-8fb1-8cf8252a57a8";
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));
    backend.get.mockImplementation(async (path: string) => {
      if (path === `/api/conversations/${legacy}`) throw new ApiError("Not found", 404);
      if (path === `/api/conversations/by-session/${legacy}`) {
        return { ...firstConversation, id: canonical, session_id: legacy };
      }
      if (path === `/api/conversations/${FIRST}`) return firstConversation;
      if (path === "/api/conversations") return staleList;
      throw new Error(`Unexpected GET ${path}`);
    });
    let verified: boolean | undefined;
    await act(async () => { verified = await provider!.loadSession(legacy); });
    expect(verified).toBe(true);
    expect(provider?.currentSession?.id).toBe(canonical);
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

  it("does not resurrect an in-flight conversation load after deletion", async () => {
    const other = "39cf16e6-3488-4891-bcc0-1d1b80b497f0";
    render(
      <SessionProvider initialSessionId={FIRST}>
        <Probe />
      </SessionProvider>,
    );
    await waitFor(() => expect(provider?.currentSession?.id).toBe(FIRST));

    let finishLoad!: (value: typeof firstConversation) => void;
    let started!: () => void;
    const requestStarted = new Promise<void>(resolve => { started = resolve; });
    const pendingResponse = new Promise<typeof firstConversation>(resolve => { finishLoad = resolve; });
    backend.get.mockImplementation(async (path: string) => {
      if (path === `/api/conversations/${other}`) {
        started();
        return pendingResponse;
      }
      if (path === "/api/conversations") return staleList;
      if (path === `/api/conversations/${FIRST}`) return firstConversation;
      throw new Error(`Unexpected GET ${path}`);
    });

    let loading!: Promise<boolean>;
    act(() => {
      loading = provider!.loadSession(other);
    });
    await requestStarted;
    let deletion: SessionDeletionOutcome | undefined;
    await act(async () => {
      deletion = await provider!.deleteSessionWithOutcome(other);
    });
    expect(deletion?.deleted).toBe(true);

    let accepted: boolean | undefined;
    await act(async () => {
      finishLoad({ ...firstConversation, id: other, session_id: other });
      accepted = await loading;
    });
    expect(accepted).toBe(false);
    expect(provider?.currentSession?.id).toBe(FIRST);
    expect(provider?.sessions.some(session => session.id === other)).toBe(false);
    expect(provider?.error).toContain("deleted");
    const previousGets = backend.get.mock.calls.filter(
      ([path]) => path === `/api/conversations/${other}`,
    ).length;
    await fetchConversationBootstrap(other);
    expect(backend.get.mock.calls.filter(
      ([path]) => path === `/api/conversations/${other}`,
    )).toHaveLength(previousGets + 1);
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
