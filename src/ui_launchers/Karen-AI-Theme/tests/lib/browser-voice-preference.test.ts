import { beforeEach, describe, expect, it } from "vitest";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";
import {
  persistPreferredBrowserVoiceURI,
  readPreferredBrowserVoiceURI,
} from "@/lib/browser-voice-preference";

describe("shared device-local browser voice preference", () => {
  beforeEach(() => localStorage.clear());

  it("returns the unselected device default without writing storage", () => {
    expect(readPreferredBrowserVoiceURI()).toBeNull();
    expect(localStorage.getItem(KAREN_SETTINGS_LS_KEY)).toBeNull();
  });

  it("preserves the exact saved voice URI for both settings and playback", () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({
      ttsVoiceURI: "local:voice-en", notifications: { enabled: true },
    }));
    expect(readPreferredBrowserVoiceURI()).toBe("local:voice-en");
    persistPreferredBrowserVoiceURI("local:voice-fr");
    expect(readPreferredBrowserVoiceURI()).toBe("local:voice-fr");
    expect(JSON.parse(localStorage.getItem(KAREN_SETTINGS_LS_KEY) || "{}")).toMatchObject({
      notifications: { enabled: true }, ttsVoiceURI: "local:voice-fr",
    });
  });

  it.each(["{broken", "null", "[]", '"invalid"', '{"ttsVoiceURI":123}', '{"ttsVoiceURI":"   "}'])(
    "does not invent a selected browser voice for invalid stored data: %s",
    (raw) => {
      localStorage.setItem(KAREN_SETTINGS_LS_KEY, raw);
      expect(readPreferredBrowserVoiceURI()).toBeNull();
      expect(localStorage.getItem(KAREN_SETTINGS_LS_KEY)).toBe(raw);
    },
  );

  it("preserves concurrent changes to unrelated settings and supports reset", () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({
      ttsVoiceURI: "voice-a", notifications: { enabled: false }, memoryDepth: "long",
    }));
    persistPreferredBrowserVoiceURI(null);
    expect(readPreferredBrowserVoiceURI()).toBeNull();
    expect(JSON.parse(localStorage.getItem(KAREN_SETTINGS_LS_KEY) || "{}")).toMatchObject({
      ttsVoiceURI: null, notifications: { enabled: false }, memoryDepth: "long",
    });
  });

  it.each(["{broken", "null", "[]"])(
    "rejects a write rather than replacing corrupted settings: %s",
    (raw) => {
      localStorage.setItem(KAREN_SETTINGS_LS_KEY, raw);
      expect(() => persistPreferredBrowserVoiceURI("voice-a")).toThrow();
      expect(localStorage.getItem(KAREN_SETTINGS_LS_KEY)).toBe(raw);
    },
  );
});
