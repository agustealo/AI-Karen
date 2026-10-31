import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatAssistantMessage: () => <div />,
}));

vi.mock("@/components/chat/ConversationContextRail", () => ({
  default: ({ metadata, agentSteps }: {
    metadata: Record<string, unknown>; agentSteps: unknown[];
  }) => (
    <aside data-testid="canonical-conversation-rail">
      <span>{String(metadata.actual_model)}</span>
      <span data-testid="observed-steps">{agentSteps.length}</span>
    </aside>
  ),
}));

import {
  KarenVerifiedHistoryProvider,
  parseKarenVerifiedHistory,
} from "@/components/chat/copilotkit/KarenCopilotVerifiedHistory";
import { KarenCopilotVerifiedRail } from "@/components/chat/copilotkit/KarenCopilotVerifiedRail";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const messages = [
  { id: "user-1", role: "user" },
  { id: "assistant-1", role: "assistant" },
];

describe("CopilotKit canonical intelligence rail", () => {
  it("shows an explicit absence instead of inventing activity when no receipt was saved", () => {
    render(
      <KarenVerifiedHistoryProvider parts={parseKarenVerifiedHistory([], messages)}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByTestId("karen-copilot-rail-unverified")).toHaveLength(2);
    expect(screen.getByTestId("karen-copilot-mobile-intelligence")).toBeTruthy();
    expect(screen.queryByTestId("canonical-conversation-rail")).toBeNull();
    expect(screen.getAllByText(/No backend-verified execution receipt/)).toHaveLength(2);
  });

  it("renders the existing intelligence rail only from a verified saved receipt", () => {
    const parts = parseKarenVerifiedHistory([
      {
        type: "CUSTOM",
        name: "karen.execution_receipt.v1",
        messageId: "assistant-1",
        value: {
          actual_provider: "local",
          actual_model: "verified-runtime-model",
          response_source: "local_inference",
          fallback_level: 0,
        },
      },
    ], messages);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByTestId("canonical-conversation-rail")).toHaveLength(2);
    expect(screen.getAllByText("verified-runtime-model")).toHaveLength(2);
    expect(screen.getAllByTestId("observed-steps").every(node => node.textContent === "0")).toBe(true);
    expect(screen.queryByTestId("karen-copilot-rail-unverified")).toBeNull();
  });

  it("rejects duplicate or malformed canonical message identities before event replay", () => {
    const receipt = {
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "assistant-1",
      value: {
        actual_provider: "local",
        actual_model: "verified-runtime-model",
        response_source: "local_inference",
      },
    };
    expect(() => parseKarenVerifiedHistory([receipt], [
      { id: "assistant-1", role: "assistant" },
      { id: "assistant-1", role: "assistant" },
    ])).toThrow("Unsupported canonical conversation message identity");
    expect(() => parseKarenVerifiedHistory([receipt], [
      { id: "assistant-1", role: "assistant" },
      { id: "user-2", role: "system" },
    ])).toThrow("Unsupported canonical conversation message identity");
    expect(() => parseKarenVerifiedHistory([receipt], [
      { id: "", role: "assistant" },
    ])).toThrow("Unsupported canonical conversation message identity");
    expect(() => parseKarenVerifiedHistory([receipt], Array.from(
      { length: 501 }, (_, i) => ({ id: `assistant-${i}`, role: "assistant" }),
    ))).toThrow("Unsupported canonical conversation messages");
  });

  it("uses canonical transcript order when verified receipt events arrive out of order", () => {
    const transcript = [
      { id: "user-1", role: "user" },
      { id: "assistant-older", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-newer", role: "assistant" },
    ];
    const receipt = (messageId: string, actual_model: string) => ({
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId,
      value: {
        actual_provider: "local",
        actual_model,
        response_source: "local_inference",
        degraded_mode: false,
      },
    });
    // The older event arrives last. It must not override the newer
    // execution merely because event replay ordering differs.
    const parts = parseKarenVerifiedHistory([
      receipt("assistant-newer", "newest-model"),
      receipt("assistant-older", "stale-model"),
    ], transcript);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByText("newest-model")).toHaveLength(2);
    expect(screen.queryByText("stale-model")).toBeNull();
  });

  it("renders only backend-attested, ordered saved agent activity", () => {
    const value = (sequence: number, status: string) => ({
      type: "CUSTOM",
      name: "karen.agent_step.v1",
      messageId: "assistant-1",
      value: {
        step_id: "step-1", agent_id: "research", status,
        event_type: "agent_step_" + status,
        description: "Observed agent activity.",
        run_id: "run-1", sequence,
      },
    });
    const receipt = {
      type: "CUSTOM", name: "karen.execution_receipt.v1",
      messageId: "assistant-1",
      value: {
        actual_provider: "local", actual_model: "verified-model",
        response_source: "local_inference",
      },
    };
    const parts = parseKarenVerifiedHistory([
      value(1, "running"), value(3, "completed"), receipt,
    ], messages);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByTestId("observed-steps").every(
      node => node.textContent === "1",
    )).toBe(true);
    expect(screen.queryByTestId("karen-copilot-activity-replay-unavailable")).toBeNull();
    expect(() => parseKarenVerifiedHistory([
      value(3, "completed"), value(1, "running"), receipt,
    ], messages)).toThrow("Unsupported verified agent activity");
    expect(() => parseKarenVerifiedHistory([
      { ...value(1, "completed"), messageId: "user-1" },
    ], messages)).toThrow("Unsupported verified conversation event");
  });

  it("never carries observed activity into a newer assistant turn without steps", () => {
    const transcript = [
      { id: "user-1", role: "user" },
      { id: "assistant-old", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-new", role: "assistant" },
    ];
    const events = [
      {
        type: "CUSTOM",
        name: "karen.agent_step.v1",
        messageId: "assistant-old",
        value: {
          step_id: "old-step", agent_id: "research",
          status: "completed", event_type: "agent_step_completed",
          description: "Previous request completed.",
          run_id: "old-run", sequence: 2,
        },
      },
      {
        type: "CUSTOM",
        name: "karen.execution_receipt.v1",
        messageId: "assistant-new",
        value: {
          actual_provider: "local", actual_model: "latest-model",
          response_source: "local_inference",
        },
      },
    ];
    const parts = parseKarenVerifiedHistory(events, transcript);
    expect(parts.has("assistant-new")).toBe(true);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByTestId("observed-steps").every(
      node => node.textContent === "0",
    )).toBe(true);
    expect(screen.getAllByText("latest-model")).toHaveLength(2);
  });

  it("does not reuse an older model receipt for an unverified latest reply", () => {
    const transcript = [
      { id: "user-1", role: "user" },
      { id: "assistant-old", role: "assistant" },
      { id: "user-2", role: "user" },
      { id: "assistant-new", role: "assistant" },
    ];
    const parts = parseKarenVerifiedHistory([{
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "assistant-old",
      value: {
        actual_provider: "local", actual_model: "older-model",
        response_source: "local_inference",
      },
    }], transcript);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.queryByText("older-model")).toBeNull();
    expect(screen.queryByTestId("canonical-conversation-rail")).toBeNull();
    expect(screen.getAllByTestId("karen-copilot-rail-unverified")).toHaveLength(2);
  });

  it("restores a successful non-degraded execution receipt without inventing fallback", () => {
    const parts = parseKarenVerifiedHistory([{
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "assistant-1",
      value: {
        actual_provider: "local",
        actual_model: "verified-runtime-model",
        response_source: "local_inference",
        degraded_mode: false,
        fallback_level: 0,
      },
    }], messages);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    expect(screen.getAllByTestId("canonical-conversation-rail")).toHaveLength(2);
    expect(screen.getAllByText("verified-runtime-model")).toHaveLength(2);
  });

  it.each(["false", 0, null, {}, []])(
    "rejects untrusted non-boolean degraded_mode %j",
    (degraded_mode) => {
      expect(() => parseKarenVerifiedHistory([{
        type: "CUSTOM",
        name: "karen.execution_receipt.v1",
        messageId: "assistant-1",
        value: {
          actual_provider: "local",
          actual_model: "verified-runtime-model",
          response_source: "local_inference",
          degraded_mode,
        },
      }], messages)).toThrow("Unsupported verified execution receipt");
    },
  );

  it("rejects a forged receipt instead of rendering made-up execution", () => {
    expect(() => parseKarenVerifiedHistory([{
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "assistant-1",
      value: {
        actual_provider: "local",
        actual_model: "made-up-model",
        response_source: "local_inference",
        secret: "not-allowed",
      },
    }], messages)).toThrow();
  });
  it("presents verified intelligence in an accessible mobile disclosure", () => {
    const parts = parseKarenVerifiedHistory([{
      type: "CUSTOM",
      name: "karen.execution_receipt.v1",
      messageId: "assistant-1",
      value: {
        actual_provider: "local",
        actual_model: "verified-runtime-model",
        response_source: "local_inference",
        degraded_mode: false,
      },
    }], messages);
    render(
      <KarenVerifiedHistoryProvider parts={parts}>
        <KarenCopilotVerifiedRail />
      </KarenVerifiedHistoryProvider>,
    );
    const disclosure = screen.getByTestId("karen-copilot-mobile-intelligence");
    expect(disclosure.tagName).toBe("DETAILS");
    expect(disclosure.hasAttribute("open")).toBe(false);
    expect(disclosure.querySelector("summary")?.textContent).toContain("Conversation intelligence");
    expect(disclosure.querySelector('[data-testid="canonical-conversation-rail"]')).not.toBeNull();
  });

});
