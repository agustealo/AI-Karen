import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  fetchConversation: vi.fn(),
  agent: { threadId: "", setMessages: vi.fn() },
  isReady: true,
  agentOptions: [] as Array<{agentId: string;runtimeAgentId: string;threadId: string}>,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
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

describe("CopilotKit canonical conversation hydration", () => {
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
    expect(screen.getByRole("alert").textContent).toContain("interactive or structured content");
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
  });

  it("never mounts a text-only chat when verified rich playback events would be dropped", async () => {
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [{ id: "m1", role: "assistant", content: "Weather observed" }],
      replayEvents: [
        { type: "CUSTOM", name: "karen.presentation.v1", messageId: "m1",
          value: { component_type: "weather.observation" } },
      ],
    });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByRole("alert").textContent)
      .toContain("interactive or structured content");
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
