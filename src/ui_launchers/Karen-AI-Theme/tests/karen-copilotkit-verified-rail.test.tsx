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
    expect(screen.getByTestId("karen-copilot-rail-unverified")).toBeTruthy();
    expect(screen.queryByTestId("canonical-conversation-rail")).toBeNull();
    expect(screen.getByText(/No backend-verified execution receipt/)).toBeTruthy();
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
    expect(screen.getByTestId("canonical-conversation-rail")).toBeTruthy();
    expect(screen.getByText("verified-runtime-model")).toBeTruthy();
    expect(screen.getByTestId("observed-steps").textContent).toBe("0");
    expect(screen.queryByTestId("karen-copilot-rail-unverified")).toBeNull();
  });

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
});
