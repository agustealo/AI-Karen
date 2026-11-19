import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import {
  KarenCopilotPinnedDock,
  parseAuthorizedPinReadback,
} from "@/components/chat/copilotkit/KarenCopilotPinnedDock";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiClient: api }));

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

beforeEach(() => api.get.mockReset());
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
    api.get.mockRejectedValue(new Error("upstream unavailable"));
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
    let resolve!: (value: unknown) => void;
    api.get.mockImplementation(() => new Promise((r) => { resolve = r; }));
    const rendered = render(<KarenCopilotPinnedDock />);
    rendered.unmount();
    resolve(snapshot);
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("karen-pins-authorized")).toBeNull();
  });
});
