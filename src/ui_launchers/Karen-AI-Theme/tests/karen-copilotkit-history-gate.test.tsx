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
  formatRecoveredConversationText,
} from "@/components/chat/copilotkit/KarenCopilotHistoryGate";
import { KarenCopilotAssistantMessage, parseKarenVerifiedHistory } from "@/components/chat/copilotkit/KarenCopilotVerifiedHistory";

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
  return <div data-testid="shared-agent-consumer">{isReady && Object.is(agent, backend.agent) ? "same-agent" : "unavailable"}</div>;
}

describe("CopilotKit canonical conversation hydration", () => {
  it("restores healthy and degraded execution receipts without falsifying their boolean status", () => {
    const messages = [{ id: "answer-1", role: "assistant" }];
    const baseReceipt = {
      actual_provider: "local",
      actual_model: "verified-model",
      response_source: "local_inference",
      runtime_engine: "vllm",
      fallback_level: 0,
    };
    const event = (value: Record<string, unknown>) => [{
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "answer-1",
      value,
    }];

    for (const degraded_mode of [false, true]) {
      const value = { ...baseReceipt, degraded_mode };
      expect(parseKarenVerifiedHistory(event(value), messages).get("answer-1"))
        .toEqual([{ type: "receipt", value }]);
    }
    const automatic = {
      ...baseReceipt,
      degraded_mode: false,
      requested_provider: null,
      requested_model: null,
      runtime_engine: null,
      degradation_reason: null,
      fallback_level: null,
    };
    expect(parseKarenVerifiedHistory(event(automatic), messages).get("answer-1"))
      .toEqual([{ type: "receipt", value: automatic }]);
    expect(() => parseKarenVerifiedHistory(
      event({ ...automatic, actual_model: null }), messages,
    )).toThrow("Unsupported verified execution receipt");
    expect(() => parseKarenVerifiedHistory(
      event({ ...baseReceipt, degraded_mode: "false" }), messages,
    )).toThrow("Unsupported verified execution receipt");
    expect(() => parseKarenVerifiedHistory(
      event({ ...baseReceipt, fallback_level: -1 }), messages,
    )).toThrow("Unsupported verified execution receipt");
  });


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
    expect(backend.agentOptions.length).toBeGreaterThan(0);
    expect(backend.agentOptions.every((options) =>
      options.agentId === "karen-" + CONVERSATION_A &&
      options.runtimeAgentId === "default" &&
      options.threadId === CONVERSATION_A,
    )).toBe(true);
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

  it.each([502, 503])(
    "preserves owner-verified read-only text when complete rich replay returns %i",
    async (status) => {
      backend.fetchConversation
        .mockRejectedValueOnce(Object.assign(new Error("unavailable full replay"), { status }))
        .mockResolvedValueOnce({
          threadId: CONVERSATION_A, read_only: true, text_only: true,
          omitted_entries: 0, page_offset: 0, has_more: false,
          next_offset: null, conversation_updated_at: "2026-11-05T22:00:00Z",
          messages: [{ id: "a1", role: "assistant", content: "Recovered original text" }],
        });
      render(guardedHistory());
      await waitFor(() => expect(screen.getByText("Recovered original text")).toBeTruthy());
      expect(screen.getByRole("alert").textContent).toContain("No partial conversation was opened");
      expect(backend.fetchConversation).toHaveBeenNthCalledWith(
        2, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages?view=transcript",
      );
      expect(screen.queryByTestId("agent-chat")).toBeNull();
      expect(backend.agent.setMessages).not.toHaveBeenCalled();
      expect(backend.agent.subscribe).not.toHaveBeenCalled();
    },
  );

  it("recovers the complete authorized text view from an unsupported rich replay without mounting SDK chat", async () => {
    backend.fetchConversation
      .mockRejectedValueOnce(
        Object.assign(new Error("unsupported presentation"), { status: 409 }),
      )
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        omitted_entries: 1,
        messages: [
          { id: "u1", role: "user", content: "What time is it?" },
          { id: "a1", role: "assistant", content: "<script>Saved text only</script>" },
        ],
      });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByTestId("karen-read-only-transcript")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("cannot faithfully restore");
    expect(screen.getByRole("alert").textContent).toContain("No partial conversation was opened");
    expect(screen.getByRole("region", { name: "Recovered read-only text transcript" })).toBeTruthy();
    expect(screen.getByText("What time is it?")).toBeTruthy();
    expect(screen.getByText("<script>Saved text only</script>")).toBeTruthy();
    expect(screen.queryByText("private tool output")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(/1 non-chat entries were withheld/)).toBeTruthy();
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(backend.agent.subscribe).not.toHaveBeenCalled();
    expect(backend.fetchConversation).toHaveBeenNthCalledWith(
      2, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages?view=transcript",
    );
  });


  it("formats authorized recovery text literally without invented tool or rich metadata", () => {
    expect(formatRecoveredConversationText([
      { id: "u1", role: "user", content: "Hi <script>alert(1)</script>" },
      { id: "a1", role: "assistant", content: "Verified response" },
    ])).toBe("You:\nHi <script>alert(1)</script>\n\nKaren:\nVerified response");
  });

  it("copies the full independently verified text without mounting SDK chat or running an agent", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true, value: { writeText },
    });
    try {
      backend.fetchConversation
        .mockRejectedValueOnce(Object.assign(new Error("unsupported"), { status: 409 }))
        .mockResolvedValueOnce({
          threadId: CONVERSATION_A, read_only: true, text_only: true,
          omitted_entries: 2,
          messages: [
            { id: "u1", role: "user", content: "Original request" },
            { id: "a1", role: "assistant", content: "Saved response <script>literal text</script>" },
          ],
        });
      render(guardedHistory());
      await waitFor(() => expect(screen.getByTestId("karen-read-only-transcript")).toBeTruthy());
      expect(writeText).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Copy verified conversation text" }));
      await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
      expect(writeText).toHaveBeenCalledWith(
        "You:\nOriginal request\n\nKaren:\nSaved response <script>literal text</script>",
      );
      await waitFor(() => expect(screen.getByTestId("karen-recovered-copy-status").textContent)
        .toContain("copied"));
      expect(screen.getByText(/2 non-chat entries were withheld/)).toBeTruthy();
      expect(backend.agent.setMessages).not.toHaveBeenCalled();
      expect(backend.agent.subscribe).not.toHaveBeenCalled();
    } finally {
      if (original) {
        Object.defineProperty(navigator, "clipboard", original);
      } else {
        Reflect.deleteProperty(navigator, "clipboard");
      }
    }
  });

  it("does not claim a copied recovery when clipboard permission fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("private clipboard denial"));
    const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", {
      configurable: true, value: { writeText },
    });
    try {
      backend.fetchConversation
        .mockRejectedValueOnce(Object.assign(new Error("unsupported"), { status: 409 }))
        .mockResolvedValueOnce({
          threadId: CONVERSATION_A, read_only: true, text_only: true,
          omitted_entries: 0,
          messages: [{ id: "a1", role: "assistant", content: "Saved answer" }],
        });
      render(guardedHistory());
      await waitFor(() => expect(screen.getByTestId("karen-read-only-transcript")).toBeTruthy());
      fireEvent.click(screen.getByRole("button", { name: "Copy verified conversation text" }));
      await waitFor(() => expect(screen.getByTestId("karen-recovered-copy-status").textContent)
        .toContain("could not be confirmed"));
      expect(screen.getByTestId("karen-recovered-copy-status").textContent)
        .not.toContain("private clipboard denial");
      expect(backend.agent.setMessages).not.toHaveBeenCalled();
    } finally {
      if (original) {
        Object.defineProperty(navigator, "clipboard", original);
      } else {
        Reflect.deleteProperty(navigator, "clipboard");
      }
    }
  });

  it("starts a fresh conversation only after an explicit user action and never hydrates unverified SDK history", async () => {
    const startNew = vi.fn().mockResolvedValue(undefined);
    backend.fetchConversation
      .mockRejectedValueOnce(Object.assign(new Error("unsupported"), { status: 409 }))
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        omitted_entries: 1,
        messages: [{ id: "a1", role: "assistant", content: "Verified text" }],
      });
    render(
      <KarenCopilotHistoryGate conversationId={CONVERSATION_A}
        onStartNewConversation={startNew}>
        <div data-testid="agent-chat">Chat is ready</div>
      </KarenCopilotHistoryGate>,
    );
    await waitFor(() => expect(screen.getByTestId("karen-read-only-transcript")).toBeTruthy());
    expect(startNew).not.toHaveBeenCalled();
    expect(screen.queryByTestId("agent-chat")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start a new conversation" }));
    expect(startNew).toHaveBeenCalledTimes(1);
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(backend.agent.subscribe).not.toHaveBeenCalled();
  });

  it("navigates independently authenticated transcript pages without SDK hydration or model inference", async () => {
    const revision = "2026-11-05T22:00:00Z";
    backend.fetchConversation
      .mockRejectedValueOnce(Object.assign(new Error("rich content unsupported"), { status: 409 }))
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        conversation_updated_at: revision, page_offset: 0, has_more: true,
        next_offset: 500, omitted_entries: 2,
        messages: [{ id: "first", role: "user", content: "Beginning of conversation" }],
      })
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        conversation_updated_at: revision, page_offset: 500, has_more: false,
        next_offset: null, omitted_entries: 0,
        messages: [{ id: "last", role: "assistant", content: "After 500 entries" }],
      })
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        conversation_updated_at: revision, page_offset: 0, has_more: true,
        next_offset: 500, omitted_entries: 2,
        messages: [{ id: "first", role: "user", content: "Beginning of conversation" }],
      });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByText("Beginning of conversation")).toBeTruthy());
    expect(screen.queryByText("After 500 entries")).toBeNull();
    expect(screen.getByRole("button", { name: "Copy this verified transcript page" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next 500 saved entries" }));
    await waitFor(() => expect(screen.getByText("After 500 entries")).toBeTruthy());
    expect(screen.queryByText("Beginning of conversation")).toBeNull();
    expect(screen.getByText(/Saved entry page 2/)).toBeTruthy();
    expect(backend.fetchConversation).toHaveBeenNthCalledWith(
      3, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages?view=transcript&offset=500",
    );
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await waitFor(() => expect(screen.getByText("Beginning of conversation")).toBeTruthy());
    expect(backend.fetchConversation).toHaveBeenNthCalledWith(
      4, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages?view=transcript&offset=0",
    );
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
    expect(backend.agent.subscribe).not.toHaveBeenCalled();
    expect(screen.queryByTestId("agent-chat")).toBeNull();
  });

  it("rejects a stale transcript page after canonical revision changes", async () => {
    backend.fetchConversation
      .mockRejectedValueOnce(Object.assign(new Error("rich content unsupported"), { status: 409 }))
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        conversation_updated_at: "revision-1", page_offset: 0, has_more: true,
        next_offset: 500, omitted_entries: 0,
        messages: [{ id: "a1", role: "assistant", content: "Safe first page" }],
      })
      .mockResolvedValueOnce({
        threadId: CONVERSATION_A, read_only: true, text_only: true,
        conversation_updated_at: "revision-2", page_offset: 500, has_more: false,
        next_offset: null, omitted_entries: 0,
        messages: [{ id: "a2", role: "assistant", content: "Changed conversation" }],
      });
    render(guardedHistory());
    await waitFor(() => expect(screen.getByText("Safe first page")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Next 500 saved entries" }));
    await waitFor(() => expect(screen.getByTestId("karen-recovered-page-status").textContent)
      .toContain("could not be verified"));
    expect(screen.getByText("Safe first page")).toBeTruthy();
    expect(screen.queryByText("Changed conversation")).toBeNull();
    expect(backend.agent.setMessages).not.toHaveBeenCalled();
  });

  it("never displays a transcript unless the independent recovery read attests owner, mode and message shape", async () => {
    for (const forged of [
      { threadId: CONVERSATION_B, read_only: true, text_only: true, omitted_entries: 0,
        messages: [{ id: "a1", role: "assistant", content: "Foreign private answer" }] },
      { threadId: CONVERSATION_A, read_only: false, text_only: true, omitted_entries: 0,
        messages: [{ id: "a1", role: "assistant", content: "Wrong mode" }] },
      { threadId: CONVERSATION_A, read_only: true, text_only: true, omitted_entries: 0,
        messages: [{ id: "a1", role: "assistant", content: "One" },
          { id: "a1", role: "assistant", content: "Two" }] },
    ]) {
      backend.fetchConversation
        .mockRejectedValueOnce(Object.assign(new Error("rich incompatible"), { status: 409 }))
        .mockResolvedValueOnce(forged);
      const view = render(guardedHistory());
      await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
      await waitFor(() => expect(backend.fetchConversation).toHaveBeenCalledTimes(2));
      expect(screen.queryByTestId("agent-chat")).toBeNull();
      expect(screen.queryByTestId("karen-read-only-transcript")).toBeNull();
      expect(backend.agent.setMessages).not.toHaveBeenCalled();
      view.unmount();
      backend.fetchConversation.mockReset();
    }
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
      .mockRejectedValueOnce(new Error("canonical recovery temporarily unavailable"))
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

  it("renders the first verified presentation immediately after one completed prompt", async () => {
    const firstMessage = "a-first";
    const presentation = {
      schema_version: 1, presentation_id: "first-prompt-clock",
      component_type: "time.observation", evidence_ref: "request-first:clock",
      data: { formatted: "2026-11-04 17:42", timezone: "America/Detroit" },
    };
    backend.fetchConversation.mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [],
      replayEvents: [],
    }).mockResolvedValueOnce({
      threadId: CONVERSATION_A,
      messages: [
        { id: "u-first", role: "user", content: "time" },
        { id: firstMessage, role: "assistant", content: "It is 5:42 PM." },
      ],
      replayEvents: [{
        type: "CUSTOM", name: "karen.presentation.v1",
        messageId: firstMessage, value: presentation,
      }],
    });
    render(
      <KarenCopilotHistoryGate conversationId={CONVERSATION_A}>
        <KarenCopilotAssistantMessage message={{
          id: firstMessage, role: "assistant", content: "It is 5:42 PM.",
        } as never} />
      </KarenCopilotHistoryGate>,
    );
    await waitFor(() => expect(backend.agent.subscribe).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("karen-time-presentation")).toBeNull();

    // One actual SDK run finishes, then a single authenticated canonical
    // read enables the saved UI without requiring another model prompt.
    act(() => backend.callbacks?.onRunFinalized());
    await waitFor(() => expect(screen.getByTestId("karen-time-presentation")).toBeTruthy());
    expect(screen.getByTestId("karen-time-presentation").textContent).toContain("5:42 PM");
    expect(backend.fetchConversation).toHaveBeenCalledTimes(2);
    expect(backend.agent.setMessages).toHaveBeenLastCalledWith([
      { id: "u-first", role: "user", content: "time" },
      { id: firstMessage, role: "assistant", content: "It is 5:42 PM." },
    ]);
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
    // Rich replay failure may attempt an independent owner-verified text
    // recovery, but never mutate the SDK or fabricate a completed reply.
    expect(backend.fetchConversation).toHaveBeenCalledTimes(3);
    expect(backend.fetchConversation).toHaveBeenNthCalledWith(
      3, "/api/copilotkit/threads/" + CONVERSATION_A + "/messages?view=transcript",
    );
    expect(screen.queryByTestId("karen-read-only-transcript")).toBeNull();
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
