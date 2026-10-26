import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  provider: [] as Array<Record<string, unknown>>,
  chat: [] as Array<Record<string, unknown>>,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatAssistantMessage: () => null,
  CopilotKitProvider: (props: Record<string, unknown>) => {
    sdk.provider.push(props);
    return <div data-testid="copilot-provider">{props.children as React.ReactNode}</div>;
  },
  CopilotChat: (props: Record<string, unknown>) => {
    sdk.chat.push(props);
    return <div data-testid="copilot-chat" />;
  },
}));

// The shell tests only verify provider/thread/model binding. The separate
// history-gate suite covers canonical message loading and access failures.
vi.mock("@/components/chat/copilotkit/KarenCopilotHistoryGate", () => ({
  KarenCopilotHistoryGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  karenScopedAgentId: (conversationId: string) => "karen-" + conversationId,
}));

import { KarenCopilotChat } from "@/components/chat/copilotkit/KarenCopilotChat";

const CONVERSATION = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";

beforeEach(() => {
  sdk.provider.length = 0;
  sdk.chat.length = 0;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Karen CopilotKit chat compatibility shell", () => {
  it("binds the current canonical conversation UUID to CopilotKit's thread", () => {
    render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(screen.getByTestId("copilot-chat")).toBeTruthy();
    expect(sdk.chat[0].threadId).toBe(CONVERSATION);
    expect(sdk.chat[0].agentId).toBe("karen-" + CONVERSATION);
    const messageView = sdk.chat[0].messageView as Record<string, unknown>;
    expect(typeof messageView.assistantMessage).toBe("function");
    expect(sdk.provider[0].runtimeUrl).toBe("/api/copilotkit");
    expect(sdk.provider[0].properties).toBeUndefined();
  });

  it("forwards only bounded paired model preferences, not execution authority", () => {
    render(
      <KarenCopilotChat
        conversationId={CONVERSATION}
        preferredProvider="local"
        preferredModel="selected-model"
      />,
    );
    expect(sdk.provider[0].properties).toEqual({
      preferred_llm_provider: "local",
      preferred_model: "selected-model",
    });
    expect(sdk.chat[0].threadId).toBe(CONVERSATION);
  });

  it("does not mount an agent with an unverified conversation", () => {
    render(<KarenCopilotChat conversationId="not-an-owned-uuid" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.provider).toHaveLength(0);
    expect(sdk.chat).toHaveLength(0);
  });

  it("rejects unpaired or oversized model hints without starting an agent", () => {
    render(<KarenCopilotChat
      conversationId={CONVERSATION}
      preferredProvider="local"
      preferredModel={null}
    />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.chat).toHaveLength(0);
    cleanup();
    render(<KarenCopilotChat
      conversationId={CONVERSATION}
      preferredProvider="local"
      preferredModel={"x".repeat(201)}
    />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.chat).toHaveLength(0);
  });
});
