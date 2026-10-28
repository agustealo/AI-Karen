import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  views: [] as Array<Record<string, unknown>>,
  agent: {
    messages: [] as Array<{ id: string; role: string; content: string }>,
    isRunning: false,
    threadId: "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0",
    addMessage: vi.fn(),
    subscribe: vi.fn(),
  },
  isReady: true,
  runAgent: vi.fn(),
  stopAgent: vi.fn(),
  clearDraft: vi.fn(),
  post: vi.fn(),
  get: vi.fn(),
  subscribe: vi.fn(),
  unsubscribe: vi.fn(),
  lifecycle: null as null | {
    onRunStartedEvent: (args: { event: { threadId: string; runId: string } }) => void;
    onRunFinalized: () => void;
    onRunFailed: () => void;
  },
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

vi.mock("@/lib/api", () => ({
  apiClient: { post: sdk.post, get: sdk.get },
}));

vi.mock("@/components/chat/assistant-ui/KarenLocalDictation", () => ({
  KarenLocalDictationCapture: () => <div data-testid="shared-local-dictation" />,
}));
vi.mock("@/components/chat/assistant-ui/KarenBrowserDictation", () => ({
  KarenBrowserDictationCapture: () => <div data-testid="shared-browser-dictation" />,
}));

vi.mock("@/components/chat/copilotkit/useKarenPersistedDraft", () => ({
  useKarenPersistedDraft: () => {
    const [draft, setDraft] = React.useState("");
    const text = React.useRef("");
    return {
      draft,
      setText: (value: string) => {
        if (value.length > 65536) return;
        text.current = value;
        setDraft(value);
      },
      readText: () => text.current,
      status: "ready",
      synced: true,
      clearBeforeSubmit: (...args: unknown[]) => sdk.clearDraft(...args),
      retry: vi.fn(),
      discardAndReload: vi.fn(),
    };
  },
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
  sdk.clearDraft.mockReset().mockResolvedValue(true);
  sdk.get.mockReset().mockResolvedValue({
    status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
  });
  sdk.post.mockReset().mockResolvedValue({
    status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
  });
  sdk.unsubscribe.mockReset();
  sdk.lifecycle = null;
  sdk.agent.subscribe.mockReset().mockImplementation((callbacks) => {
    sdk.lifecycle = callbacks;
    return { unsubscribe: sdk.unsubscribe };
  });
  vi.stubGlobal("crypto", { randomUUID: () => "2dab411c-640e-4206-909b-6783e32c7da0" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "clipboard");
  vi.restoreAllMocks();
});

function input() {
  const props = sdk.views.at(-1)?.input as Record<string, unknown> | undefined;
  expect(props).toBeDefined();
  return props as {
    onSubmitMessage: (text: string) => void;
    onStop: () => void;
    onChange: (text: string) => void;
    value: string;
  };
}

describe("CK-07E4: SDK-native view with explicitly controlled inference", () => {
  it("does not start a provider, append a message or overwrite saved history on mount", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    expect(screen.getByTestId("native-copilot-view")).toBeTruthy();
    expect(screen.getByTestId("shared-local-dictation")).toBeTruthy();
    expect(screen.getByTestId("shared-browser-dictation")).toBeTruthy();
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

  it("keeps an unsent native draft controlled and never starts inference while typing", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    expect(input().value).toBe("");
    act(() => input().onChange("private unsent draft"));
    expect(input().value).toBe("private unsent draft");
    expect(sdk.runAgent).not.toHaveBeenCalled();
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
  });

  it("refuses an oversized draft without adding a user message", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onChange("x".repeat(65537)));
    expect(input().value).toBe("");
    expect(screen.getByRole("alert").textContent).toContain("message length");
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
    expect(sdk.runAgent).not.toHaveBeenCalled();
  });

  it("starts a canonical CopilotKit run only after an explicit nonempty composer submission", async () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("  Send this question  ");
      input().onSubmitMessage("  Send this question  ");
    });
    await waitFor(() => expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1));
    expect(sdk.clearDraft).toHaveBeenCalledWith("Send this question");
    expect(sdk.agent.addMessage).toHaveBeenCalledWith({
      id: "2dab411c-640e-4206-909b-6783e32c7da0",
      role: "user",
      content: "Send this question",
    });
    await waitFor(() => expect(sdk.runAgent).toHaveBeenCalledTimes(1));
    expect(sdk.runAgent).toHaveBeenCalledWith({ agent: sdk.agent });
  });

  it("rejects rapid duplicate submits until the previous SDK run settles", async () => {
    let resolveRun!: () => void;
    sdk.runAgent.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveRun = resolve;
    }));
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Send once");
      input().onSubmitMessage("Send once");
      input().onSubmitMessage("Send twice");
    });
    await waitFor(() => expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(sdk.runAgent).toHaveBeenCalledTimes(1));
    await act(async () => resolveRun());
    expect(sdk.runAgent).toHaveBeenCalledTimes(1);
  });

  it("retains an unsent draft and unlocks submit when the SDK append fails synchronously", async () => {
    sdk.agent.addMessage.mockImplementationOnce(() => { throw new Error("private SDK failure"); });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Retain my question");
      input().onSubmitMessage("Retain my question");
    });
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("unsent draft was retained"));
    expect(input().value).toBe("Retain my question");
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(sdk.runAgent).not.toHaveBeenCalled();
    const retained = screen.getByRole("textbox", { name: "Unsent failed message" }) as HTMLTextAreaElement;
    expect(retained.readOnly).toBe(true);
    expect(retained.value).toBe("Retain my question");

    // No automatic retry while the failed submission remains unresolved.
    act(() => input().onSubmitMessage("Retry after recovery"));
    expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert").textContent).toContain("before sending another");

    // Explicitly resolving the failed copy unlocks deliberate retries.
    act(() => fireEvent.click(screen.getByRole("button", { name: "Dismiss failed message" })));
    expect(screen.queryByRole("textbox", { name: "Unsent failed message" })).toBeNull();
    act(() => {
      input().onChange("Retry after recovery");
      input().onSubmitMessage("Retry after recovery");
    });
    await waitFor(() => expect(sdk.agent.addMessage).toHaveBeenCalledTimes(2));
    expect(sdk.agent.addMessage).toHaveBeenLastCalledWith(expect.objectContaining({
      role: "user",
      content: "Retry after recovery",
    }));
  });

  it("preserves newer edits and a copyable failed submission when SDK append fails after clear", async () => {
    let confirmClear!: (result: boolean) => void;
    sdk.clearDraft.mockImplementationOnce(() => new Promise<boolean>(resolve => {
      confirmClear = resolve;
    }));
    sdk.agent.addMessage.mockImplementationOnce(() => {
      throw new Error("private SDK append failure");
    });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Original unsent message");
      input().onSubmitMessage("Original unsent message");
    });
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
    act(() => input().onChange("Newer unsent text"));
    await act(async () => confirmClear(true));
    await waitFor(() => expect(screen.getByTestId("karen-copilot-failed-submission"))
      .toBeTruthy());
    expect(input().value).toBe("Newer unsent text");
    const failedMessage = screen.getByRole("textbox", {
      name: "Unsent failed message",
    }) as HTMLTextAreaElement;
    expect(failedMessage.readOnly).toBe(true);
    expect(failedMessage.value).toBe("Original unsent message");
    expect((screen.getByRole("button", {
      name: "Restore to empty composer",
    }) as HTMLButtonElement).disabled).toBe(true);
    act(() => input().onSubmitMessage("Newer unsent text"));
    expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(sdk.runAgent).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).not.toContain("private");
  });

  it("provides explicit copy and accessible status for a failed native SDK submission", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true, value: { writeText },
    });
    sdk.agent.addMessage.mockImplementationOnce(() => { throw new Error("private SDK append"); });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("A valuable unsent message");
      input().onSubmitMessage("A valuable unsent message");
    });
    await waitFor(() => expect(screen.getByRole("button", {
      name: "Copy failed message",
    })).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByRole("button", {
      name: "Copy failed message",
    })));
    expect(writeText).toHaveBeenCalledWith("A valuable unsent message");
    expect(screen.getByTestId("karen-copilot-copy-feedback").textContent)
      .toContain("copied");
    expect(sdk.runAgent).not.toHaveBeenCalled();
  });

  it("keeps the failed text selectable and reports clipboard permission failure", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("private clipboard denial")) },
    });
    sdk.agent.addMessage.mockImplementationOnce(() => { throw new Error("append rejected"); });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Keep this text");
      input().onSubmitMessage("Keep this text");
    });
    await waitFor(() => expect(screen.getByRole("button", {
      name: "Copy failed message",
    })).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByRole("button", {
      name: "Copy failed message",
    })));
    expect(screen.getByTestId("karen-copilot-copy-feedback").textContent)
      .toContain("Select the unsent message");
    expect(screen.getByTestId("karen-copilot-copy-feedback").textContent)
      .not.toContain("private");
    expect((screen.getByRole("textbox", {
      name: "Unsent failed message",
    }) as HTMLTextAreaElement).value).toBe("Keep this text");
  });

  it("uses exact AG-UI run identity to request canonical cancellation before stopping transport", async () => {
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    expect(sdk.agent.subscribe).toHaveBeenCalledTimes(1);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: {
      threadId: THREAD, runId: "run-exact",
    } }));
    act(() => input().onStop());
    await waitFor(() => expect(sdk.post).toHaveBeenCalledWith(
      "/api/copilotkit/agent/default/stop/" + THREAD, { runId: "run-exact" },
    ));
    await waitFor(() => expect(sdk.stopAgent).toHaveBeenCalledWith({ agent: sdk.agent }));
    expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("confirmation is still pending");
    expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .not.toContain("confirmed this run was cancelled");
  });

  it("shows confirmed cancellation only when exact backend receipt confirms termination", async () => {
    sdk.post.mockResolvedValueOnce({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    });
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("confirmed this run was cancelled"));
    expect(sdk.stopAgent).toHaveBeenCalledTimes(1);
  });

  it("refuses thread-only or foreign-run stop without calling SDK or backend", () => {
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => input().onStop());
    expect(sdk.post).not.toHaveBeenCalled();
    expect(sdk.stopAgent).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("exact active run");
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: {
      threadId: "a7d4ed43-2c3a-4d91-afc4-82e5e4811c56", runId: "foreign",
    } }));
    act(() => input().onStop());
    expect(sdk.post).not.toHaveBeenCalled();
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: {
      threadId: THREAD, runId: "invalid space",
    } }));
    act(() => input().onStop());
    expect(sdk.post).not.toHaveBeenCalled();
  });

  it("does not call SDK stop or claim cancellation when the backend request fails", async () => {
    sdk.post.mockRejectedValueOnce(new Error("private service failure"));
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not verify the cancellation request"));
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(sdk.stopAgent).not.toHaveBeenCalled();
    expect(screen.queryByTestId("karen-copilot-stop-status")).toBeNull();
  });

  it("does not turn an unverified backend payload into a cancellation receipt", async () => {
    sdk.post.mockResolvedValueOnce({ status: "cancelled", cancellation_confirmed: true });
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not verify"));
    expect(sdk.stopAgent).not.toHaveBeenCalled();
    expect(screen.queryByTestId("karen-copilot-stop-status")).toBeNull();
  });

  it("coalesces repeated stop clicks while canonical cancellation is pending", async () => {
    let finish!: (receipt: unknown) => void;
    sdk.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => { input().onStop(); input().onStop(); });
    expect(sdk.post).toHaveBeenCalledTimes(1);
    await act(async () => finish({
      status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
    }));
    expect(sdk.stopAgent).toHaveBeenCalledTimes(1);
  });

  it("does not apply a late cancellation receipt to another run", async () => {
    let finish!: (receipt: unknown) => void;
    sdk.post.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    sdk.agent.isRunning = true;
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-old" } }));
    act(() => input().onStop());
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-new" } }));
    await act(async () => finish({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    }));
    expect(screen.queryByTestId("karen-copilot-stop-status")).toBeNull();
    expect(sdk.stopAgent).not.toHaveBeenCalled();
  });

  it("checks backend status read-only and only confirms a persisted terminal cancellation", async () => {
    sdk.agent.isRunning = true;
    sdk.get.mockResolvedValueOnce({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("button", {
      name: "Check cancellation status",
    })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Check cancellation status" }));
    await waitFor(() => expect(sdk.get).toHaveBeenCalledWith(
      "/api/copilotkit/agent/default/runs/" + THREAD + "/run-1/status",
    ));
    await waitFor(() => expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("confirmed this run was cancelled"));
    expect(screen.queryByRole("button", { name: "Check cancellation status" })).toBeNull();
    expect(sdk.post).toHaveBeenCalledTimes(1);
  });

  it("keeps pending stop pending until read-only backend confirms its terminal status", async () => {
    sdk.agent.isRunning = true;
    sdk.get.mockResolvedValueOnce({
      status: "cancelling", cancel_requested: true, cancellation_confirmed: false,
    });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("button", { name: "Check cancellation status" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Check cancellation status" }));
    await waitFor(() => expect(sdk.get).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("confirmation is still pending");
    expect(sdk.post).toHaveBeenCalledTimes(1);
  });

  it("rejects forged terminal claims and preserves the ability to check again", async () => {
    sdk.agent.isRunning = true;
    sdk.get.mockResolvedValueOnce({
      status: "completed", cancel_requested: false, cancellation_confirmed: true,
    });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("button", { name: "Check cancellation status" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Check cancellation status" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not verify the run"));
    expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .not.toContain("confirmed this run");
    expect(screen.getByRole("button", { name: "Check cancellation status" })).toBeTruthy();
  });

  it("distinguishes completed execution from a requested but unconfirmed stop", async () => {
    sdk.agent.isRunning = true;
    sdk.get.mockResolvedValueOnce({
      status: "completed", cancel_requested: false, cancellation_confirmed: false,
    });
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-1" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("button", { name: "Check cancellation status" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Check cancellation status" }));
    await waitFor(() => expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("ended without a confirmed stop"));
    expect(screen.queryByRole("button", { name: "Check cancellation status" })).toBeNull();
  });

  it("discards late status from an older run after a new RUN_STARTED", async () => {
    let finish!: (result: unknown) => void;
    sdk.agent.isRunning = true;
    sdk.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-old" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("button", { name: "Check cancellation status" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Check cancellation status" }));
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-new" } }));
    await act(async () => finish({
      status: "cancelled", cancel_requested: true, cancellation_confirmed: true,
    }));
    expect(screen.queryByTestId("karen-copilot-stop-status")).toBeNull();
  });

  it("reports local transport failure without downgrading canonical accepted cancellation", async () => {
    sdk.agent.isRunning = true;
    sdk.stopAgent.mockRejectedValueOnce(new Error("private cancellation error"));
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "run-exact" } }));
    act(() => input().onStop());
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("local streaming could not stop"));
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(screen.getByTestId("karen-copilot-stop-status").textContent)
      .toContain("confirmation is still pending");
  });

  it("blocks inference until canonical draft clearance is confirmed", async () => {
    sdk.clearDraft.mockResolvedValueOnce(false);
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Do not send without saved-clear receipt");
      input().onSubmitMessage("Do not send without saved-clear receipt");
    });
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("Draft clearance was not confirmed"));
    expect(sdk.agent.addMessage).not.toHaveBeenCalled();
    expect(sdk.runAgent).not.toHaveBeenCalled();
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
    expect(screen.getByRole("status").textContent)
      .toContain("Loading verified conversation and saved draft");
    expect(screen.queryByTestId("native-copilot-view")).toBeNull();
    expect(sdk.runAgent).not.toHaveBeenCalled();
  });

  it("reports a rejected model run but never fabricates an assistant completion", async () => {
    sdk.runAgent.mockRejectedValueOnce(new Error("private provider details"));
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => {
      input().onChange("Hello");
      input().onSubmitMessage("Hello");
    });
    await waitFor(() => expect(screen.getByRole("alert").textContent)
      .toContain("could not complete"));
    expect(screen.getByRole("alert").textContent).not.toContain("private");
    expect(sdk.agent.addMessage).toHaveBeenCalledTimes(1);
    expect(sdk.agent.messages).toHaveLength(2);
  });

  it("refuses cancellation for a non-running run even if a stale run ID exists", () => {
    render(<KarenCopilotControlledChat conversationId={THREAD} />);
    act(() => sdk.lifecycle?.onRunStartedEvent({ event: { threadId: THREAD, runId: "stale" } }));
    act(() => input().onStop());
    expect(sdk.post).not.toHaveBeenCalled();
    expect(sdk.stopAgent).not.toHaveBeenCalled();
  });
});
