import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ApiError } from "@/lib/api";
import {
  KarenCopilotPinnedDock,
  parseAuthorizedPinReadback,
  verifyCommittedPinMutation,
} from "@/components/chat/copilotkit/KarenCopilotPinnedDock";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiClient: api,
  ApiError: class ApiError extends Error {
    constructor(public status: number, message = "Request failed") { super(message); }
  },
}));

const authorizedPin = {
  pin_id: "88888888-8888-4888-8888-888888888888",
  position: 0,
  revision: 2,
  source: {
    conversation_id: "44444444-4444-4444-8444-444444444444",
    assistant_message_id: "22222222-2222-5222-8222-222222222222",
    presentation_id: "source-card",
    evidence_ref: "source-receipt",
    component_type: "weather.observation",
    schema_version: 1,
  },
};
const snapshot = { schema_version: 1 as const, read_only: true as const, pins: [authorizedPin] };

beforeEach(() => { api.get.mockReset(); api.post.mockReset(); });
afterEach(() => cleanup());

describe("governed pinned workspace reference consumer", () => {
  it("shows only server reauthorized references without inventing presentation content", async () => {
    api.get.mockResolvedValue(snapshot);
    render(<KarenCopilotPinnedDock />);
    expect(screen.getByTestId("karen-pins-loading")).toBeTruthy();
    expect(await screen.findByTestId("karen-pins-authorized")).toBeTruthy();
    expect(screen.getByText("weather · observation")).toBeTruthy();
    expect(screen.getByText("Saved reference 1 · Revision 2")).toBeTruthy();
    expect(screen.queryByTestId("karen-weather-presentation")).toBeNull();
    expect(screen.queryByText("source-card")).toBeNull();
    expect(api.get).toHaveBeenCalledExactlyOnceWith("/api/chat/ag-ui/pins");
  });

  it("distinguishes a genuine verified empty list from an unavailable backend", async () => {
    api.get.mockResolvedValue({ schema_version: 1, read_only: true, pins: [] });
    const rendered = render(<KarenCopilotPinnedDock />);
    expect(await screen.findByTestId("karen-pins-empty")).toBeTruthy();
    rendered.unmount();
    // Only one request should fail; never leak the rejection into other effects.
    api.get.mockRejectedValueOnce(new Error("upstream unavailable"));
    render(<KarenCopilotPinnedDock />);
    expect(await screen.findByTestId("karen-pinning-not-available")).toBeTruthy();
    expect(screen.queryByTestId("karen-pins-empty")).toBeNull();
  });

  it("fails closed on fabricated or contradictory server payloads", async () => {
    const invalid = [
      { ...snapshot, read_only: false },
      { ...snapshot, pins: [authorizedPin, authorizedPin] },
      { ...snapshot, pins: [{ ...authorizedPin, source: { ...authorizedPin.source, secret: "invalid" } }] },
      { ...snapshot, pins: [{ ...authorizedPin, position: -1 }] },
      { ...snapshot, pins: [{ ...authorizedPin, data: { fake: true } }] },
      { ...snapshot, pins: [{ ...authorizedPin, source: { ...authorizedPin.source, component_type: "" } }] },
      null,
    ];
    for (const payload of invalid) {
      expect(parseAuthorizedPinReadback(payload)).toBeNull();
    }
    api.get.mockResolvedValue({ ...snapshot, read_only: false });
    render(<KarenCopilotPinnedDock />);
    expect(await screen.findByTestId("karen-pinning-not-available")).toBeTruthy();
    expect(screen.queryByTestId("karen-pins-authorized")).toBeNull();
  });

  it("ignores a late response after its authenticated consumer is unmounted", async () => {
    // A controlled deferred response proves cleanup cancels stale updates;
    // React act flushes the settled microtask before the assertion.
    let settle!: (value: unknown) => void;
    const delayed = new Promise<unknown>((resolve) => { settle = resolve; });
    api.get.mockReturnValueOnce(delayed);
    const rendered = render(<KarenCopilotPinnedDock />);
    expect(api.get).toHaveBeenCalledTimes(1);
    rendered.unmount();
    await act(async () => {
      settle(snapshot);
      await delayed;
    });
    expect(screen.queryByTestId("karen-pins-authorized")).toBeNull();
  });
  it("keeps mutation controls absent in the actual consumer default", async () => {
    api.get.mockResolvedValue(snapshot);
    render(<KarenCopilotPinnedDock />);
    await screen.findByTestId("karen-pins-authorized");
    expect(screen.queryByTestId("karen-pin-controls")).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("requires matching backend receipt and fresh readback before removing a pin", async () => {
    api.get.mockResolvedValueOnce(snapshot)
      .mockResolvedValueOnce({ schema_version: 1, read_only: true, pins: [] });
    api.post.mockImplementation(async (_path, request) => ({
      schema_version: 1, committed: true,
      receipt: {
        receipt_id: "committed-receipt",
        idempotency_key: request.idempotency_key,
        operation: request.operation,
        pin_id: request.pin_id,
      },
    }));
    render(<KarenCopilotPinnedDock mutationControlsEnabled />);
    await screen.findByTestId("karen-pins-authorized");
    fireEvent.click(screen.getByRole("button", { name: "Unpin reference 1" }));
    expect(await screen.findByTestId("karen-pins-empty")).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post.mock.calls[0][0]).toBe("/api/chat/ag-ui/pins/mutations");
    expect(api.post.mock.calls[0][1]).toMatchObject({
      operation: "unpin",
      pin_id: authorizedPin.pin_id,
    });
    expect(api.get).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("karen-pins-mutation-notice")).toBeNull();
  });

  it("rejects mismatched receipts and never mutates local pinned state optimistically", async () => {
    api.get.mockResolvedValue(snapshot);
    api.post.mockResolvedValue({
      schema_version: 1, committed: true,
      receipt: {
        receipt_id: "unrelated", operation: "unpin",
        idempotency_key: "77777777-7777-4777-8777-777777777777",
        pin_id: authorizedPin.pin_id,
      },
    });
    expect(verifyCommittedPinMutation(null, "unpin", authorizedPin.pin_id,
      "99999999-9999-4999-8999-999999999999")).toBe(false);
    render(<KarenCopilotPinnedDock mutationControlsEnabled />);
    await screen.findByTestId("karen-pins-authorized");
    fireEvent.click(screen.getByRole("button", { name: "Unpin reference 1" }));
    expect((await screen.findByTestId("karen-pins-mutation-notice")).textContent)
      .toContain("Pin change not confirmed");
    expect(screen.getByText("Saved reference 1 · Revision 2")).toBeTruthy();
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("reorder sends exact backend revision and target index; stale CAS refreshes without retry", async () => {
    const secondPin = {
      ...authorizedPin, pin_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      position: 1, revision: 3,
    };
    const ordered = { schema_version: 1, read_only: true, pins: [authorizedPin, secondPin] };
    api.get.mockResolvedValue(ordered);
    api.post.mockRejectedValue(new ApiError(409, "Conflict"));
    render(<KarenCopilotPinnedDock mutationControlsEnabled />);
    await screen.findByTestId("karen-pins-authorized");
    expect(screen.getByRole("button", { name: "Move reference 1 up" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Move reference 1 down" }));
    expect((await screen.findByTestId("karen-pins-mutation-notice")).textContent)
      .toContain("Saved references changed elsewhere");
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(api.post.mock.calls[0][1]).toMatchObject({
      operation: "reorder", pin_id: authorizedPin.pin_id,
      expected_revision: 2, position: 1,
    });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("hides stale references if authorized re-read is unavailable after uncertain mutation", async () => {
    api.get.mockResolvedValueOnce(snapshot).mockRejectedValueOnce(new Error("backend unavailable"));
    api.post.mockRejectedValue(new Error("unknown network failure"));
    render(<KarenCopilotPinnedDock mutationControlsEnabled />);
    await screen.findByTestId("karen-pins-authorized");
    fireEvent.click(screen.getByRole("button", { name: "Unpin reference 1" }));
    expect(await screen.findByTestId("karen-pinning-not-available")).toBeTruthy();
    expect(screen.queryByText("Saved reference 1 · Revision 2")).toBeNull();
    expect(api.post).toHaveBeenCalledTimes(1);
  });

});
