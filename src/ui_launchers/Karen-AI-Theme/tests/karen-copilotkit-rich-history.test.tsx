import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatAssistantMessage: ({ message }: { message: { id: string; content: string } }) =>
    <div data-testid="sdk-default-assistant">{message.content}</div>,
}));

import { CopilotChatAssistantMessage } from "@copilotkit/react-core/v2";
import {
  KarenCopilotAssistantMessage,
  KarenVerifiedHistoryProvider,
  parseKarenVerifiedHistory,
} from "@/components/chat/copilotkit/KarenCopilotVerifiedHistory";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const messages = [
  { id: "user-1", role: "user" },
  { id: "assistant-1", role: "assistant" },
];
const clock = {
  schema_version: 1,
  presentation_id: "time-observed",
  component_type: "time.observation",
  evidence_ref: "clock-capability-1",
  data: { formatted: "2026-10-26 08:34", timezone: "America/Detroit" },
};
const timeEvent = {
  type: "CUSTOM", name: "karen.presentation.v1",
  messageId: "assistant-1", value: clock,
};
const receiptEvent = {
  type: "CUSTOM", name: "karen.execution_receipt.v1",
  messageId: "assistant-1", value: {
    actual_provider: "local", actual_model: "observed-model",
    response_source: "local_inference", fallback_level: 0,
  },
};
const integrityEvent = {
  type: "CUSTOM", name: "karen.response_integrity.v1",
  messageId: "assistant-1", value: { output_truncated: true },
};

function renderAssistant(events: unknown, id = "assistant-1") {
  const parts = parseKarenVerifiedHistory(events, messages);
  const sdkProps = {
    message: { id, role: "assistant", content: "Saved canonical reply" },
  } as unknown as ComponentProps<typeof CopilotChatAssistantMessage>;
  return render(
    <KarenVerifiedHistoryProvider parts={parts}>
      <KarenCopilotAssistantMessage {...sdkProps} />
    </KarenVerifiedHistoryProvider>,
  );
}

describe("CK-07E3 CopilotKit v2 rich restoration in native message slot", () => {
  it("preserves SDK message and mounts the existing verified clock and execution receipt", () => {
    renderAssistant([timeEvent, receiptEvent, integrityEvent]);
    expect(screen.getByTestId("sdk-default-assistant").textContent)
      .toBe("Saved canonical reply");
    expect(screen.getByTestId("karen-time-presentation").textContent)
      .toContain("8:34 AM");
    expect(screen.getByTestId("karen-restored-execution-receipt").textContent)
      .toContain("observed-model");
    expect(screen.getByTestId("karen-output-truncated").textContent)
      .toContain("incomplete");
    expect(screen.getAllByTestId("karen-copilot-verified-part")).toHaveLength(3);
  });

  it("does not attach another assistant message's canonical parts", () => {
    renderAssistant([timeEvent, receiptEvent], "unrelated-assistant");
    expect(screen.getByTestId("sdk-default-assistant")).toBeTruthy();
    expect(screen.queryByTestId("karen-time-presentation")).toBeNull();
    expect(screen.queryByTestId("karen-restored-execution-receipt")).toBeNull();
  });

  it("keeps plaintext compatibility without fabricating a receipt", () => {
    renderAssistant([]);
    expect(screen.getByTestId("sdk-default-assistant")).toBeTruthy();
    expect(screen.queryAllByTestId("karen-copilot-verified-part")).toHaveLength(0);
  });

  it.each([
    [{ ...timeEvent, messageId: "user-1" }],
    [{ ...timeEvent, messageId: "foreign-assistant" }],
    [{ ...timeEvent, value: { ...clock, evidence_ref: "" } }],
    [{ ...timeEvent, value: { ...clock, data: { formatted: "now", private: "leaked" } } }],
    [{ ...timeEvent, name: "karen.execute_tool" }],
    [{ type: "TOOL_CALL_START", name: "unsafe", messageId: "assistant-1", value: {} }],
    [{ ...receiptEvent, value: { ...receiptEvent.value, secret: "private" } }],
    [{ ...receiptEvent, value: { ...receiptEvent.value, actual_model: "" } }],
    [{ ...integrityEvent, value: { output_truncated: false, private_token: "x" } }],
    [timeEvent, timeEvent, timeEvent, timeEvent, timeEvent, timeEvent, timeEvent],
    [receiptEvent, receiptEvent],
    [integrityEvent, integrityEvent],
  ])("rejects the entire unsupported or forged replay set before SDK hydration", events => {
    expect(() => parseKarenVerifiedHistory(events, messages)).toThrow();
  });

  it("refuses unsafe shape and invalid event collection size", () => {
    expect(() => parseKarenVerifiedHistory({ data: [] }, messages)).toThrow();
    expect(() => parseKarenVerifiedHistory(new Array(4001).fill(timeEvent), messages)).toThrow();
    expect(() => parseKarenVerifiedHistory([null], messages)).toThrow();
  });
});
