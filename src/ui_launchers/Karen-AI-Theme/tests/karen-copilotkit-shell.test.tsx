import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  provider: [] as Array<Record<string, unknown>>,
  controlled: [] as Array<Record<string, unknown>>,
  persona: [] as Array<Record<string, unknown>>,
  providerMounts: 0,
  providerUnmounts: 0,
  auth: {
    user: {
      user_id: "11111111-1111-4111-8111-111111111111",
      tenant_id: "22222222-2222-4222-8222-222222222222",
    },
    isAuthenticated: true,
    isLoading: false,
  },
}));

vi.mock("@/lib/useAuth", () => ({
  useAuth: () => sdk.auth,
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: (props: Record<string, unknown>) => {
    React.useEffect(() => {
      sdk.providerMounts += 1;
      return () => { sdk.providerUnmounts += 1; };
    }, []);
    sdk.provider.push(props);
    return <div data-testid="copilot-provider">{props.children as React.ReactNode}</div>;
  },
}));

vi.mock("@/components/chat/KarenPersonaSelector", () => ({
  KarenPersonaSelector: (props: Record<string, unknown>) => {
    sdk.persona.push(props);
    return <div data-testid="backend-governed-persona" />;
  },
}));

vi.mock("@/components/chat/copilotkit/KarenCopilotVerifiedRail", () => ({
  KarenCopilotVerifiedRail: () => <aside data-testid="verified-context-rail" />,
}));

vi.mock("@/components/chat/copilotkit/KarenCopilotControlledChat", () => ({
  KarenCopilotControlledChat: (props: Record<string, unknown>) => {
    sdk.controlled.push(props);
    return <div data-testid="copilot-controlled-chat" />;
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
  sdk.controlled.length = 0;
  sdk.persona.length = 0;
  sdk.providerMounts = 0;
  sdk.providerUnmounts = 0;
  sdk.auth.user = {
    user_id: "11111111-1111-4111-8111-111111111111",
    tenant_id: "22222222-2222-4222-8222-222222222222",
  };
  sdk.auth.isAuthenticated = true;
  sdk.auth.isLoading = false;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Karen CopilotKit chat compatibility shell", () => {
  it("binds the current canonical conversation UUID to CopilotKit's thread", () => {
    render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(screen.getByTestId("copilot-controlled-chat")).toBeTruthy();
    expect(screen.getByTestId("karen-copilot-persona-footer")).toBeTruthy();
    expect(screen.getByTestId("backend-governed-persona")).toBeTruthy();
    expect(screen.getByTestId("verified-context-rail")).toBeTruthy();
    expect(sdk.controlled[0].conversationId).toBe(CONVERSATION);
    expect(sdk.provider[0].runtimeUrl).toBe("/api/copilotkit");
    expect(sdk.provider[0].enableInspector).toBe(false);
    expect(sdk.provider[0].properties).toBeUndefined();
  });

  it("forwards only the canonical session handoff to the persona footer", async () => {
    const startNewConversation = vi.fn().mockResolvedValue(undefined);
    render(<KarenCopilotChat conversationId={CONVERSATION}
      onStartNewConversation={startNewConversation} />);
    expect(sdk.persona).toHaveLength(1);
    expect(sdk.persona[0].onStartNewConversation).toBe(startNewConversation);
    expect(startNewConversation).not.toHaveBeenCalled();
    await (sdk.persona[0].onStartNewConversation as () => Promise<void>)();
    expect(startNewConversation).toHaveBeenCalledTimes(1);
  });

  it("does not invent a new-conversation authority when the callback is unavailable", () => {
    render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.persona).toHaveLength(1);
    expect(sdk.persona[0].onStartNewConversation).toBeUndefined();
  });

  it("uses the pinned native outbound messageFilter without truncating the visible SDK transcript", () => {
    const view = render(<KarenCopilotChat conversationId={CONVERSATION} />);
    const filter = sdk.provider[0].messageFilter as
      | ((messages: Array<{ id: string; role: string; content: string }>) =>
          Array<{ id: string; role: string; content: string }>)
      | undefined;
    expect(filter).toBeTypeOf("function");
    const history = Array.from({ length: 503 }, (_, index) => ({
      id: "saved-" + index,
      role: index % 2 === 0 ? "user" : "assistant",
      content: "Persisted conversation turn " + index,
    }));
    history.push({ id: "new-user", role: "user", content: "Continue this saved conversation" });
    const snapshot = history.map((message) => ({ ...message }));
    expect(filter!(history)).toEqual([history[503]]);
    expect(history).toEqual(snapshot);
    expect(filter!([])).toEqual([]);
    // Stable provider prop does not reset with preference updates or remount
    // the thread. SDK messageFilter changes the wire request, not chat UI.
    view.rerender(
      <KarenCopilotChat conversationId={CONVERSATION}
        preferredProvider="local" preferredModel="selected-model" />,
    );
    expect(sdk.provider.at(-1)?.messageFilter).toBe(filter);
    expect(sdk.providerMounts).toBe(1);
    expect(sdk.providerUnmounts).toBe(0);
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
    expect(sdk.controlled[0].conversationId).toBe(CONVERSATION);
  });

  it("forwards the canonical workspace run reference without changing the selected model", () => {
    render(<KarenCopilotChat conversationId={CONVERSATION} workspaceRunId="run_approved_17" />);
    expect(sdk.provider[0].properties).toEqual({ workspace_run_id: "run_approved_17" });
    expect(sdk.controlled[0].conversationId).toBe(CONVERSATION);
  });

  it("rejects malformed workspace run references before mounting the SDK", () => {
    render(<KarenCopilotChat conversationId={CONVERSATION} workspaceRunId="../bad" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.provider).toHaveLength(0);
  });

  it("updates idle provider preferences without remounting the owned SDK thread", () => {
    const view = render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.providerMounts).toBe(1);
    expect(sdk.providerUnmounts).toBe(0);
    expect(sdk.provider.at(-1)?.properties).toBeUndefined();

    view.rerender(
      <KarenCopilotChat
        conversationId={CONVERSATION}
        preferredProvider="local"
        preferredModel="selected-model"
      />,
    );
    expect(sdk.provider.at(-1)?.properties).toEqual({
      preferred_llm_provider: "local",
      preferred_model: "selected-model",
    });
    expect(sdk.providerMounts).toBe(1);
    expect(sdk.providerUnmounts).toBe(0);
    expect(sdk.controlled.at(-1)?.conversationId).toBe(CONVERSATION);

    view.rerender(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.provider.at(-1)?.properties).toBeUndefined();
    expect(sdk.providerMounts).toBe(1);
    expect(sdk.providerUnmounts).toBe(0);
  });

  it("never mounts a provider when authentication is unresolved or invalidated", () => {
    sdk.auth.isLoading = true;
    const view = render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(screen.queryByTestId("copilot-provider")).toBeNull();
    expect(sdk.providerMounts).toBe(0);
    sdk.auth.isLoading = false;
    sdk.auth.isAuthenticated = true;
    view.rerender(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.providerMounts).toBe(1);
    sdk.auth.isAuthenticated = false;
    view.rerender(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(screen.queryByTestId("copilot-provider")).toBeNull();
    expect(sdk.providerUnmounts).toBe(1);
  });

  it("unmounts the private SDK agent on tenant or principal switch even if thread ID matches", () => {
    const view = render(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.providerMounts).toBe(1);
    sdk.auth.user = {
      user_id: "33333333-3333-4333-8333-333333333333",
      tenant_id: "22222222-2222-4222-8222-222222222222",
    };
    view.rerender(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.providerUnmounts).toBe(1);
    expect(sdk.providerMounts).toBe(2);
    sdk.auth.user = {
      user_id: "33333333-3333-4333-8333-333333333333",
      tenant_id: "44444444-4444-4444-8444-444444444444",
    };
    view.rerender(<KarenCopilotChat conversationId={CONVERSATION} />);
    expect(sdk.providerUnmounts).toBe(2);
    expect(sdk.providerMounts).toBe(3);
  });

  it("does not mount an agent with an unverified conversation", () => {
    render(<KarenCopilotChat conversationId="not-an-owned-uuid" />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.provider).toHaveLength(0);
    expect(sdk.controlled).toHaveLength(0);
  });

  it("rejects unpaired or oversized model hints without starting an agent", () => {
    render(<KarenCopilotChat
      conversationId={CONVERSATION}
      preferredProvider="local"
      preferredModel={null}
    />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.controlled).toHaveLength(0);
    cleanup();
    render(<KarenCopilotChat
      conversationId={CONVERSATION}
      preferredProvider="local"
      preferredModel={"x".repeat(201)}
    />);
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(sdk.controlled).toHaveLength(0);
  });
});
