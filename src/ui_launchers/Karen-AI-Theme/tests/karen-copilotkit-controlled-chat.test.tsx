import React from "react";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  views: [] as Array<Record<string, unknown>>,
  agent: {
    messages: [] as Array<{ id: string; role: string; content: string }>,
    isRunning: false,
    threadId: "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0",
    addMessage: vi.fn(),
  },
  isReady: true,
  runAgent: vi.fn(),
  stopAgent: vi.fn(),
  useAgentOptions: [] as Array<Record<string, unknown>>,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatView: (props: Record<string, unknown>) => {
    sdk.views.push(props);
    return <div data-testid="native-copilot-view" />;
  },
  useAgent: (props: Record<string, unknown>) => {
    sdk.useAgentOptions.push(props);
    return { agent: sdk.agent, isReady: sdk.isReady };
  },
  useCopilotKit: () => ({
    copilotkit: { runAgent: sdk.runAgent, stopAgent: sdk.stopAgent },
  }),
}));

vi.mock("@/components/chat/copilotkit/KarenCopilotVerifiedHistory", () => ({
  KarenCopilotAssistantSlot: () => null,
}));

vi.mock("@/components/chat/copilotkit/KarenCopilotHistoryGate", () => ({
  karenScopedAgentId: (id: string) => "karen-" + id,
}));

import { KarenCopilotControlledChat } from "@/components/chat/copilotkit/KarenCopilotControlledChat";

const THREAD = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";

beforeEach(() => {
  sdk.views.length = 0;
  sdk.useAgentOptions.length = 0;
  sdk.isReady = true;
  sdk.agent.isRunning = false;
  sdk.agent.threadId = THREAD;
  sdk.agent.messages = [
    { id: "saved-user", role: "user", content: "Saved question" },
    { id: "saved-assistant", role: "assistant", content: "Saved answer" },
  ];
  sdk.agent.addMessage.mockReset();
  sdk.runAgent.mockReset().mockResolvedValue(undefined);
  sdk.stopAgent.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal("crypto", { randomUUID: () => "2dab411c-640e-4206-909b-6783e32c7da0" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function input() {
  const props = sdk.views.at(-1)?.input as Record<string, unknown> | undefined;
  expect(props).toBeDefined();
  return props as {
    onSubmitMessage: (text: string) => void;
    onStop: () => void;
  };
}

describe("CK-07E4: SDK-native view with explicitly controlled inference", () => {
  it("does not start a provider, append a message or overwrite saved history on mount", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    expect(screen.getByTestId("native-copilot-view")).toBeTruthy();
    expect(sdk.useAgentOptions).toEqual([{
      agentId: "karen-" + THREAD,
      runtimeAgentId: "default",
      threadId: THREAD,
    }]);
    expect(sdk.runAgent).not.toHaveBeenCalled();
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
    expect(sdk.views.at(-1)?.messages).toEqual(sdk.agent.messages);
    expect(sdk.views.at(-1)?.isRunning).toBe(false);
    expect(sdk.views.at(-1)?.autoScroll).toBe(true);
    expect((sdk.views.at(-1)?.messageView as Record<string, unknown>).assistantMessage)
      .toBeDefined();
  });

  it("starts a canonical CopilotKit run only after an explicit nonempty composer submission", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onSubmitMessage("  Send this question  "));
    expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(sdk.agent.addMessage).toHaveBeenCalledWith({
      id: "2dab411c-640e-4206-909b-6783e32c7da0",
      role: "user",
      content: "Send this question",
    });
    expect(sdk.runAgent).toHaveBeenCalledTimes(1);
    expect(sdk.runAgent).toHaveBeenCalledWith({ agent: sdk.agent });
  });

  it("never triggers inference for blank, oversized, running, or foreign-thread input", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onSubmitMessage("  "));
    act(() => input().onSubmitMessage("x".repeat(65537)));
    sdk.agent.isRunning = true;
    act(() => input().onSubmitMessage("While running"));
    sdk.agent.isRunning = false;
    sdk.agent.threadId = "a7d4ed43-2c3a-4d91-afc4-82e5e4811c56";
    act(() => input().onSubmitMessage("Wrong thread"));
    expect(sdk.runAgent).not.toHaveBeenCalled();
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent)
      .toContain("verified conversation");
  });

  it("does not mount an input or request a run before the agent is ready", () => {
    sdk.isReady = false;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    expect(screen.getByRole("status").textContent).toContain("Connecting");
    expect(screen.queryByTestId("native-copilot-view")).toBeNull();
    expect(sdk.runAgent).not.toHaveBeenCalled();
  });

  it("reports a rejected model run but never fabricates an assistant completion", async () => {
    sdk.runAgent.mockRejectedValueOnce(new Error("private provider details"));
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onSubmitMessage("Hello"));
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not complete"));
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(sdk.agent.messages).toHaveLength(2);
  });

  it("routes stop through the SDK only for an observed active run", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onStop());
    expect(sdk.stopAgent).not.toHaveBeenCalled();
    sdk.agent.isRunning = true;
    act(() => input().onStop());
    expect(sdk.stopAgent).toHaveBeenCalledTimes(1);
    expect(sdk.stopAgent).toHaveBeenCalledWith({ agent: sdk.agent });
  });
});
