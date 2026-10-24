import { describe, expect, it } from "vitest";
import { displayClockObservation } from "../../src/components/chat/assistant-ui/KarenPresentationRegistry";

describe("consumer-facing clock presentation", () => {
  it("formats backed wall-clock observations without shifting the instant", () => {
    expect(displayClockObservation("2026-10-24 15:55:05")).toEqual({ time: "3:55 PM", date: "2026-10-24" });
    expect(displayClockObservation("2026-10-24 00:03:00")).toEqual({ time: "12:03 AM", date: "2026-10-24" });
  });
  it("does not reinterpret unrecognized timestamps or invent timezones", () => {
    expect(displayClockObservation("2026-10-24T19:55:05Z")).toEqual({ time: "2026-10-24T19:55:05Z" });
    expect(displayClockObservation("2026-10-24 25:90")).toEqual({ time: "2026-10-24 25:90" });
  });
});
