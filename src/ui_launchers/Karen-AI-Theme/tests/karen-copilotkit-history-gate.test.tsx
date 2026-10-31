import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  fetchConversation: vi.fn(),
  agent: { threadId: "", setMessages: vi.fn(), subscribe: vi.fn() },
  callbacks: null as null | { onRunFinalized: () => void; onRunFailed: () => void },
  unsubscribe: vi.fn(),
  isReady: true,
  agentOptions: [] as Array<{agentId: string;runtimeAgentId: string;threadId: string}>,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatAssistantMessage: () => null,
  useAgent: (options: {agentId: string;runtimeAgentId: string;threadId: string}) => {
    backend.agentOptions.push(options);
    return { agent: backend.agent, isReady: backend.isReady };
  },
}));

vi.mock("@/lib/api", () => ({
  apiClient: { get: backend.fetchConversation },
}));

import {
  KarenCopilotHistoryGate,
  useKarenScopedAgent,
  karenScopedAgentId,
  toCopilotTextMessages,
} from "@/components/chat/copilotkit/KarenCopilotHistoryGate";

const CONVERSATION_A = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const CONVERSATION_B = "bd1d23c2-bbd7-4d31-987a-cf81025ebafd";

beforeEach(() => {
  backend.isReady = true;
  backend.agentOptions.length = 0;
  backend.agent.threadId = "";
  backend.fetchConversation.mockReset();
  backend.agent.setMessages.mockReset();
  backend.callbacks = null;
  backend.unsubscribe.mockReset();
  backend.agent.subscribe.mockReset().mockImplementation((callbacks) => {
    backend.callbacks = callbacks;
    return { unsubscribe: backend.unsubscribe };
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function guardedHistory(id = CONVERSATION_A) {
  return (
    <KarenCopilotHistoryGate conversationId={id}>
      <div data-testid="agent-chat">Chat is ready</div>
    </KarenCopilotHistoryGate>
  );
}

function SharedAgentConsumer() {
  const { agent, isReady } = useKarenScopedAgent();
  return <div data-testid="shared-agent-consumer">{isReady && agent === backend.agent ? "same-agent" : "unavailable"}</div>;
}

describe("CopilotKit canonical conversation hydration", () => {
  it("registers one SDK agent when history hydration and the controlled view share the scope", async () => {
    backend.fetchConversation.mockResolvedValue({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "assistant", content: "Saved response" }],
    });
    render(
      <KarenCopilotHistoryGate conversationId={CONVERSATION_A}>
        <SharedAgentConsumer />
      </KarenCopilotHistoryGate>,
    );
    await waitFor(() => expect(screen.getByTestId("shared-agent-consumer").textContent).toBe("same-agent"));
    expect(backend.agentOptions).toEqual([{
      agentId: "karen-" + CONVERSATION_A,
      runtimeAgentId: "default",
      threadId: CONVERSATION_A,
    }]);
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
  });


  it("allocates distinct local agent identities for different conversations", () => {
    expect(karenScopedAgentId(CONVERSATION_A)).not.toBe(karenScopedAgentId(CONVERSATION_B));
  });

  it("preserves exact message IDs and refuses to silently omit unsupported roles", () => {
    expect(toCopilotTextMessages([
      { id: "user-a", role: "user", content: "Question" },
      { id: "assistant-a", role: "assistant", content: "Response" },
    ])).toEqual([
      { id: "user-a", role: "user", content: "Question" },
      { id: "assistant-a", role: "assistant", content: "Response" },
    ]);
    expect(() => toCopilotTextMessages([
      { id: "user-a", role: "user", content: "Question" },
      { id: "system-a", role: "system", content: "Unrendered hidden content" },
    ])).toThrow("invalid message");
  });

  it("refuses a malformed canonical text message, rather than creating invented content", () => {
    expect(() => toCopilotTextMessages([
      { id: "", role: "assistant", content: "Text" },
    ])).toThrow("invalid message");
    expect(() => toCopilotTextMessages(null as never)).toThrow("unavailable");
  });

  it("hydrates the signed-in user's owned conversation before mounting chat", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [
        { id: "m1", role: "user", content: "Hello" },
        { id: "m2", role: "assistant", content: "Karen response" },
      ],
    });
    render(guardedHistory());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.fetchConversation).toHaveBeenCalledWith("/api/copilotkit/threads/" + CONVERSATION_A + "/messages");
    expect(backend.agentOptions.at(-1)).toEqual({
      agentId: "karen-" + CONVERSATION_A,
      runtimeAgentId: "default",
      threadId: CONVERSATION_A,
    });
    expect(backend.agent.threadId).toBe("");
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "m1", role: "user", content: "Hello" },
      { id: "m2", role: "assistant", content: "Karen response" },
    ]);
  });

  it("does not mount a chat when canonical history returns another conversation", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_B,
      messages: [{ id: "m1", role: "user", content: "Private" }],
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
  });

  it("fails closed on repository errors or missing message collections", async () => {
    backend.fetchConversation.mockRejectedValueOnce(new Error("tenant secret"));
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).not.toContain("tenant secret");
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    cleanup();

    backend.fetchConversation.mockResolvedValueOnce({ threadId: CONVERSATION_A });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
  });

  it("rechecks ownership after remount even for the same cached UUID", async () => {
    backend.fetchConversation
      .mockResolvedValueOnce({ threadId: CONVERSATION_A, messages: [{ id: "m1", role: "user", content: "Earlier owner" }] })
      .mockRejectedValueOnce(new Error("owner mismatch"));
    const initial = render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    initial.unmount();

    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);
    expect(backend.fetchConversation).toHaveBeenNthCalledWith(
      2, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages",
    );
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
  });

  it("warns about unsupported rich replay without showing a partial transcript", async () => {
    backend.fetchConversation.mockRejectedValueOnce(
      Object.assign(new Error("unsupported presentation"), { status: 409 }),
    );
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("cannot faithfully restore");
    expect(screen.getByRole("alert").textContent).toContain("No partial conversation was opened");
    expect(screen.getByRole("alert").textContent).not.toContain("existing conversation view");
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
  });

  it("recovers from a transient history outage only after a new authenticated read", async () => {
    backend.fetchConversation
      .mockRejectedValueOnce(new Error("private storage error"))
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A,
        messages: [{ id: "m1", role: "assistant", content: "Verified after recovery" }],
        replayEvents: [],
      });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(backend.agent.subscribe).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Retry verified conversation" }));
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "m1", role: "assistant", content: "Verified after recovery" },
    ]);
    // Failed initial history cannot install an SDK run subscription.
    expect(backend.agent.subscribe).toHaveBeenCalledTimes(1);
    expect(backend.unsubscribe).not.toHaveBeenCalled();
  });

  it("does not reopen failed rich replay unless a subsequent read attests all content", async () => {
    backend.fetchConversation
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A,
        messages: [{ id: "m1", role: "assistant", content: "Unsupported" }],
        replayEvents: [{ type: "CUSTOM", name: "unknown.evidence",
          messageId: "m1", value: {} }],
      })
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A,
        messages: [{ id: "m2", role: "user", content: "Valid canonical history" }],
        replayEvents: [],
      });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Retry verified conversation" }));
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "m2", role: "user", content: "Valid canonical history" },
    ]);
  });

  it("hydrates a verified saved presentation without omitting the assistant text", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "assistant", content: "The time was observed" }],
      replayEvents: [{
        type: "CUSTOM", name: "karen.presentation.v1", messageId: "m1",
        value: {
          schema_version: 1, presentation_id: "time-m1",
          component_type: "time.observation", evidence_ref: "clock-verified",
          data: { formatted: "2026-10-26 08:34", timezone: "America/Detroit" },
        },
      }],
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "m1", role: "assistant", content: "The time was observed" },
    ]);
  });

  it("refuses invalid saved rich evidence before mutating the SDK agent", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "assistant", content: "Unverified weather" }],
      replayEvents: [
        { type: "CUSTOM", name: "karen.presentation.v1", messageId: "m1",
          value: { component_type: "weather.observation" } },
      ],
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(screen.queryByTestId("agent-chat")).toBeNull();
  });

  it("accepts an explicitly empty verified replay array for text-only conversations", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "user", content: "Plain question" }],
      replayEvents: [],
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "m1", role: "user", content: "Plain question" },
    ]);
  });

  it("rejects duplicate IDs and invalid replay metadata without modifying an agent", async () => {
    expect(() => toCopilotTextMessages([
      { id: "same", role: "user", content: "Question" },
      { id: "same", role: "assistant", content: "Answer" },
    ])).toThrow("invalid message");
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "assistant", content: "Answer" }],
      replayEvents: { type: "CUSTOM", private: "invalid" },
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(screen.queryByTestId("agent-chat")).toBeNull();
  });

  it("rereads canonical saved evidence after SDK run finalizes instead of trusting streaming metadata", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "u1", role: "user", content: "Before" }],
      replayEvents: [],
    }).mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [
        { id: "u1", role: "user", content: "Before" },
        { id: "a2", role: "assistant", content: "Verified after commit" },
      ],
      replayEvents: [{
        type: "CUSTOM", name: "karen.execution_receipt.v1",
        messageId: "a2",
        value: { actual_provider: "local", actual_model: "verified",
          response_source: "local_inference" },
      }],
    });
    const view = render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    expect(backend.agent.subscribe).toHaveBeenCalledTimes(1);
    expect(backend.fetchConversation).toHaveBeenCalledTimes(1);
    act(() => backend.callbacks?.onRunFinalized());
    await waitFor(() => expect(backend.agent.setMessages).toHaveBeenCalledTimes(2));
    expect(backend.agent.setMessages).toHaveBeenLastCalledWith([
      { id: "u1", role: "user", content: "Before" },
      { id: "a2", role: "assistant", content: "Verified after commit" },
    ]);
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);
    view.unmount();
    expect(backend.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("coalesces a second SDK completion during a pending canonical refresh", async () => {
    let resolvePending!: (value: unknown) => void;
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "u1", role: "user", content: "Initial" }],
      replayEvents: [],
    }).mockImplementationOnce(() => new Promise(resolve => {
      resolvePending = resolve;
    })).mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [
        { id: "u1", role: "user", content: "Initial" },
        { id: "a3", role: "assistant", content: "Latest saved completion" },
      ],
      replayEvents: [],
    });
    render(guardedHistory());
    await waitFor(() => expect(backend.agent.subscribe).toHaveBeenCalledTimes(1));
    act(() => backend.callbacks?.onRunFinalized());
    await waitFor(() => expect(backend.fetchConversation).toHaveBeenCalledTimes(2));
    act(() => {
      backend.callbacks?.onRunFinalized();
      backend.callbacks?.onRunFailed();
    });
    // Repeated notifications during one pending read are collapsed.
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);

    await act(async () => resolvePending({
      threadId: CONVERSATION_A,
      messages: [
        { id: "u1", role: "user", content: "Initial" },
        { id: "a2", role: "assistant", content: "Stale intermediate reply" },
      ],
      replayEvents: [],
    }));
    await waitFor(() => expect(backend.fetchConversation).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(backend.agent.setMessages).toHaveBeenCalledTimes(2));
    expect(backend.agent.setMessages).toHaveBeenLastCalledWith([
      { id: "u1", role: "user", content: "Initial" },
      { id: "a3", role: "assistant", content: "Latest saved completion" },
    ]);
    expect(backend.agent.setMessages).not.toHaveBeenCalledWith(
      expect.arrayContaining([{ id: "a2", role: "assistant", content: "Stale intermediate reply" }]),
    );
  });

  it("fails closed when a queued newest read cannot attest saved history", async () => {
    let resolvePending!: (value: unknown) => void;
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "u1", role: "user", content: "Initial" }],
      replayEvents: [],
    }).mockImplementationOnce(() => new Promise(resolve => {
      resolvePending = resolve;
    })).mockRejectedValueOnce(new Error("private unavailable history"));
    render(guardedHistory());
    await waitFor(() => expect(backend.agent.subscribe).toHaveBeenCalledTimes(1));
    act(() => backend.callbacks?.onRunFinalized());
    await waitFor(() => expect(backend.fetchConversation).toHaveBeenCalledTimes(2));
    act(() => backend.callbacks?.onRunFinalized());
    await act(async () => resolvePending({
      threadId: CONVERSATION_A,
      messages: [{ id: "a2", role: "assistant", content: "Not the latest" }],
      replayEvents: [],
    }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
    expect(backend.fetchConversation).toHaveBeenCalledTimes(3);
  });

  it("does not fabricate a saved reply if the post-run attestation fails", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "u1", role: "user", content: "Before" }],
      replayEvents: [],
    }).mockRejectedValueOnce(
      Object.assign(new Error("unsupported content"), { status: 409 }),
    );
    render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    act(() => backend.callbacks?.onRunFinalized());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).toHaveBeenCalledTimes(1);
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);
  });

  it("ignores an obsolete conversation snapshot after switching threads", async () => {
    let finishA!: (value: unknown) => void;
    backend.fetchConversation
      .mockImplementationOnce(() => new Promise((resolve) => { finishA = resolve; }))
      .mockResolvedValueOnce({
        threadId: CONVERSATION_B,
        messages: [{ id: "b1", role: "assistant", content: "B only" }],
      });
    const view = render(guardedHistory(CONVERSATION_A));
    view.rerender(guardedHistory(CONVERSATION_B));
    await waitFor(() => expect(screen.getByTestId("agent-chat")).toBeTruthy());
    finishA({
      threadId: CONVERSATION_A,
      messages: [{ id: "a1", role: "assistant", content: "Old private history" }],
    });
    await waitFor(() => expect(backend.agent.setMessages).toHaveBeenCalledTimes(1));
    expect(backend.agent.setMessages).toHaveBeenCalledWith([
      { id: "b1", role: "assistant", content: "B only" },
    ]);
  });
});
