import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  currentSession: null as null | { id: string; title: string },
  workspaceRunId: null as string | null,
  strictInitialSession: false,
  sessions: [] as Array<{ id: string; title: string }>,
  isLoadingSessions: false,
  error: null as string | null,
  createNewSession: vi.fn(),
  loadSession: vi.fn(),
  mounts: [] as string[],
  modelProps: [] as Array<{preferredProvider: string | null; preferredModel: string | null; workspaceRunId: string | null}>,
  onModelChange: null as null | ((value: {provider: string; model: string} | null) => void),
  onBusyChange: null as null | ((busy: boolean) => void),
}));

vi.mock("@/components/chat/SessionProvider", () => ({
  useSession: () => ({
    currentSession: state.currentSession,
    workspaceRunId: state.workspaceRunId,
    strictInitialSession: state.strictInitialSession,
    sessions: state.sessions,
    isLoadingSessions: state.isLoadingSessions,
    error: state.error,
    createNewSession: state.createNewSession,
    loadSession: state.loadSession,
  }),
}));

vi.mock("@/components/chat/KarenComposerRuntimeCatalog", () => ({
  KarenComposerRuntimeCatalog: ({ onSelectionChange }: { onSelectionChange: (selection: { provider: string; model: string } | null) => void }) => (
    <button type="button" onClick={() => { state.onModelChange = onSelectionChange; onSelectionChange({ provider: "local", model: "selected-model" }); }}>Choose available model</button>
  ),
}));

vi.mock("@/components/chat/copilotkit/KarenCopilotChat", () => ({
  KarenCopilotChat: ({ conversationId, preferredProvider, preferredModel, workspaceRunId, onBusyChange }: { conversationId: string; preferredProvider: string | null; preferredModel: string | null; workspaceRunId: string | null; onBusyChange: (busy: boolean) => void }) => {
    state.mounts.push(conversationId);
    state.modelProps.push({ preferredProvider, preferredModel, workspaceRunId });
    state.onBusyChange = onBusyChange;
    return <div data-testid="owned-copilot-chat">{conversationId}</div>;
  },
}));

import { KarenCopilotConsumerChat } from "@/components/chat/copilotkit/KarenCopilotConsumerChat";

const FIRST = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0";
const SECOND = "7aaebd2c-1b53-4f55-9e34-2c4593b477c5";

beforeEach(() => {
  state.currentSession = null;
  state.workspaceRunId = null;
  state.strictInitialSession = false;
  state.sessions = [];
  state.isLoadingSessions = false;
  state.error = null;
  state.mounts.length = 0;
  state.modelProps.length = 0;
  state.onModelChange = null;
  state.onBusyChange = null;
  state.createNewSession.mockReset().mockResolvedValue(undefined);
  state.loadSession.mockReset().mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CopilotKit consumer session adapter", () => {
  it("does not mount an SDK chat while canonical sessions load", () => {
    state.isLoadingSessions = true;
    render(<KarenCopilotConsumerChat />);
    expect(screen.getByRole("status").textContent).toContain("Loading conversations");
    expect(screen.queryByTestId("owned-copilot-chat")).toBeNull();
    expect(state.mounts).toHaveLength(0);
  });

  it("requires a durable new session instead of inventing a local thread", async () => {
    render(<KarenCopilotConsumerChat />);
    expect(screen.queryByTestId("owned-copilot-chat")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(state.createNewSession).toHaveBeenCalledTimes(1));
    expect(state.mounts).toHaveLength(0);
  });

  it("never creates a replacement when the pinned conversation cannot be verified", () => {
    state.strictInitialSession = true;
    state.error = "The requested conversation could not be verified.";
    render(<KarenCopilotConsumerChat />);
    expect(screen.getByRole("alert").textContent).toContain("could not be verified");
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
    expect(state.createNewSession).not.toHaveBeenCalled();
    expect(state.mounts).toHaveLength(0);
  });

  it("fails closed on an unavailable strict acceptance conversation without offering a replacement", () => {
    state.strictInitialSession = true;
    state.error = "The requested conversation could not be verified. No replacement conversation was created.";
    render(<KarenCopilotConsumerChat />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("No replacement conversation was created.");
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
    expect(screen.queryByTestId("owned-copilot-chat")).toBeNull();
    expect(state.createNewSession).not.toHaveBeenCalled();
    expect(state.loadSession).not.toHaveBeenCalled();
    expect(state.mounts).toHaveLength(0);
  });

  it("locks navigation to an already verified strictly pinned conversation", () => {
    state.strictInitialSession = true;
    state.currentSession = { id: FIRST, title: "Pinned conversation" };
    state.sessions = [
      { id: FIRST, title: "Pinned conversation" },
      { id: SECOND, title: "Another owned conversation" },
    ];
    render(<KarenCopilotConsumerChat />);
    expect(screen.getByTestId("owned-copilot-chat").textContent).toBe(FIRST);
    expect(screen.queryByRole("button", { name: "Find conversations" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
    expect(screen.queryByRole("searchbox", { name: "Find a conversation" })).toBeNull();
    expect(state.createNewSession).not.toHaveBeenCalled();
    expect(state.loadSession).not.toHaveBeenCalled();
  });

  it("binds the authorized selected session and searches owned titles only", async () => {
    state.currentSession = { id: FIRST, title: "Project Alpha" };
    state.sessions = [
      { id: FIRST, title: "Project Alpha" },
      { id: SECOND, title: "Research Beta" },
    ];
    render(<KarenCopilotConsumerChat />);
    expect(screen.getByTestId("owned-copilot-chat").textContent).toBe(FIRST);
    fireEvent.click(screen.getByRole("button", { name: "Find conversations" }));
    const search = screen.getByRole("searchbox", { name: "Find a conversation" });
    fireEvent.change(search, { target: { value: "beta" } });
    expect(screen.queryByRole("button", { name: "Project Alpha" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Research Beta" }));
    await waitFor(() => expect(state.loadSession).toHaveBeenCalledWith(SECOND));
    expect(screen.queryByRole("searchbox")).toBeNull();
    // No optimistic local session switch: SessionProvider decides the identity.
    expect(screen.getByTestId("owned-copilot-chat").textContent).toBe(FIRST);
  });

  it("uses the existing backend catalog to request a model without choosing runtime execution", () => {
    state.currentSession = { id: FIRST, title: "Project Alpha" };
    state.sessions = [{ id: FIRST, title: "Project Alpha" }];
    render(<KarenCopilotConsumerChat />);
    expect(state.modelProps.at(-1)).toEqual({ preferredProvider: null, preferredModel: null, workspaceRunId: null });
    fireEvent.click(screen.getByText("Model preferences"));
    fireEvent.click(screen.getByRole("button", { name: "Choose available model" }));
    expect(state.modelProps.at(-1)).toEqual({
      preferredProvider: "local", preferredModel: "selected-model", workspaceRunId: null,
    });
  });

  it("freezes model preferences during an in-flight turn", () => {
    state.currentSession = { id: FIRST, title: "Project Alpha" };
    state.sessions = [{ id: FIRST, title: "Project Alpha" }];
    render(<KarenCopilotConsumerChat />);
    fireEvent.click(screen.getByText("Model preferences"));
    fireEvent.click(screen.getByRole("button", { name: "Choose available model" }));
    const busy = state.onBusyChange;
    const change = state.onModelChange;
    if (!busy || !change) throw new Error("Missing canonical callbacks");
    act(() => busy(true));
    expect(screen.getByRole("status").textContent).toContain("Model changes are unavailable");
    act(() => change(null));
    expect(state.modelProps.at(-1)).toEqual({
      preferredProvider: "local", preferredModel: "selected-model", workspaceRunId: null,
    });
    act(() => busy(false));
    act(() => change(null));
    expect(state.modelProps.at(-1)).toEqual({
      preferredProvider: null, preferredModel: null, workspaceRunId: null,
    });
  });

  it("preserves the canonical Agent Runtime handoff in its owned conversation", () => {
    state.currentSession = { id: FIRST, title: "Agent Runtime" };
    state.sessions = [{ id: FIRST, title: "Agent Runtime" }];
    state.workspaceRunId = "run_approved_17";
    render(<KarenCopilotConsumerChat />);
    expect(state.modelProps.at(-1)?.workspaceRunId).toBe("run_approved_17");
  });

  it("blocks conversation changes while an owned CopilotKit run is active", () => {
    state.currentSession = { id: FIRST, title: "Original" };
    state.sessions = [
      { id: FIRST, title: "Original" },
      { id: SECOND, title: "Other" },
    ];
    render(<KarenCopilotConsumerChat />);
    const busy = state.onBusyChange;
    if (!busy) throw new Error("Missing run-state callback");
    act(() => busy(true));
    const history = screen.getByRole("button", { name: "Find conversations" });
    const create = screen.getByRole("button", { name: "New conversation" });
    expect(history.hasAttribute("disabled")).toBe(true);
    expect(create.hasAttribute("disabled")).toBe(true);
    fireEvent.click(history);
    fireEvent.click(create);
    expect(state.createNewSession).not.toHaveBeenCalled();
    expect(state.loadSession).not.toHaveBeenCalled();
    expect(screen.getByTestId("owned-copilot-chat").textContent).toBe(FIRST);
    act(() => busy(false));
    expect(history.hasAttribute("disabled")).toBe(false);
    expect(create.hasAttribute("disabled")).toBe(false);
  });

  it("reports a failed session switch without mounting an unverified thread", async () => {
    state.currentSession = { id: FIRST, title: "Original" };
    state.sessions = [
      { id: FIRST, title: "Original" },
      { id: SECOND, title: "Restricted" },
    ];
    state.loadSession.mockRejectedValue(new Error("unauthorized"));
    render(<KarenCopilotConsumerChat />);
    fireEvent.click(screen.getByRole("button", { name: "Find conversations" }));
    fireEvent.click(screen.getByRole("button", { name: "Restricted" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("could not be saved")
    );
    expect(screen.getByTestId("owned-copilot-chat").textContent).toBe(FIRST);
  });

  it("does not issue duplicate creates while the canonical store is pending", async () => {
    let resolve!: () => void;
    state.createNewSession.mockImplementation(() => new Promise<void>(r => { resolve = r; }));
    render(<KarenCopilotConsumerChat />);
    const button = screen.getByRole("button", { name: "New conversation" });
    fireEvent.click(button);
    expect(button.hasAttribute("disabled")).toBe(true);
    fireEvent.click(button);
    expect(state.createNewSession).toHaveBeenCalledTimes(1);
    resolve();
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  });
});
