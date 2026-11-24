import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceSettings from "@/components/settings/VoiceSettings";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

const playback = vi.hoisted(() => ({
  claimVoiceOutput: vi.fn(() => vi.fn()),
}));
vi.mock("@/components/chat/KarenBrowserSpeechPlayback", () => playback);

const notifications = vi.hoisted(() => ({ toast: vi.fn() }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => notifications }));
vi.mock("@/components/settings/LocalVoiceEngineSettings", () => ({ default: () => null }));

type TestVoice = { name: string; lang: string; default: boolean; voiceURI: string };

describe("browser voice settings lifecycle", () => {
  let voiceList: TestVoice[];
  let listeners: Map<string, Set<() => void>>;
  let speak: ReturnType<typeof vi.fn>;
  let cancel: ReturnType<typeof vi.fn>;
  let utterances: Array<{ text: string; voice?: TestVoice; onend?: () => void; onerror?: () => void }>;

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    notifications.toast.mockReset();
    playback.claimVoiceOutput.mockReset();
    playback.claimVoiceOutput.mockImplementation(() => vi.fn());
    voiceList = [];
    listeners = new Map();
    speak = vi.fn();
    cancel = vi.fn();
    utterances = [];
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        getVoices: () => voiceList,
        speak, cancel,
        addEventListener: (name: string, handler: () => void) => {
          if (!listeners.has(name)) listeners.set(name, new Set());
          listeners.get(name)?.add(handler);
        },
        removeEventListener: (name: string, handler: () => void) => {
          listeners.get(name)?.delete(handler);
        },
      },
    });
    vi.stubGlobal("SpeechSynthesisUtterance", class {
      text: string;
      voice?: TestVoice;
      lang?: string;
      onend?: () => void;
      onerror?: () => void;
      constructor(text: string) {
        this.text = text;
        utterances.push(this);
      }
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    Reflect.deleteProperty(window, "speechSynthesis");
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("does not claim a system fallback, and discovers delayed voices via voiceschanged", () => {
    render(<VoiceSettings />);
    expect(screen.getByText("Checking browser speech voices…")).toBeTruthy();
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByText("No Browser Voices Found")).toBeTruthy();
    expect(screen.queryByText(/will use the default system voice/i)).toBeNull();
    voiceList = [{ name: "Local speech", lang: "en-US", default: true, voiceURI: "local:en" }];
    act(() => listeners.get("voiceschanged")?.forEach((handler) => handler()));
    expect(screen.getByRole("combobox", { name: "Browser voice" })).toBeTruthy();
    fireEvent.click(screen.getByText("Preview voice"));
    expect(playback.claimVoiceOutput).toHaveBeenCalledTimes(1);
    expect(speak).toHaveBeenCalledTimes(1);
    expect(utterances[0].voice?.voiceURI).toBe("local:en");
    expect(screen.getByText("Stop preview")).toBeTruthy();
    act(() => utterances[0].onend?.());
    expect(screen.getByText("Preview voice")).toBeTruthy();
  });

  it("preserves other settings on save and reset; never reports a failed save as success", () => {
    const voice = { name: "Local speech", lang: "en-US", default: true, voiceURI: "local:en" };
    voiceList = [voice];
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({
      ttsVoiceURI: voice.voiceURI, notifications: { enabled: true }, memoryDepth: "long",
    }));
    render(<VoiceSettings />);
    expect(screen.getByRole("combobox", { name: "Browser voice" })).toBeTruthy();
    // Simulate another settings panel writing after the Voice panel loaded.
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({
      ttsVoiceURI: voice.voiceURI, notifications: { enabled: false }, memoryDepth: "medium",
    }));
    fireEvent.click(screen.getByText("Save Settings"));
    expect(JSON.parse(localStorage.getItem(KAREN_SETTINGS_LS_KEY) || "{}").notifications.enabled).toBe(false);
    fireEvent.click(screen.getByText("Reset to Default"));
    expect(JSON.parse(localStorage.getItem(KAREN_SETTINGS_LS_KEY) || "{}")).toMatchObject({
      ttsVoiceURI: null, notifications: { enabled: false }, memoryDepth: "medium",
    });
    expect(notifications.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Browser voice preference reset",
    }));
  });

  it("does not silently replace a previously selected voice that is no longer installed", () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({ ttsVoiceURI: "missing-voice" }));
    voiceList = [{ name: "System", lang: "en-US", default: true, voiceURI: "system" }];
    render(<VoiceSettings />);
    expect(screen.getByText(/previously selected voice is no longer available/)).toBeTruthy();
    expect(screen.getByText("Save Settings").closest("button")?.disabled).toBe(true);
    expect(JSON.parse(localStorage.getItem(KAREN_SETTINGS_LS_KEY) || "{}").ttsVoiceURI).toBe("missing-voice");
  });

  it("clears discovery listeners and pending retries when unmounted", () => {
    const { unmount } = render(<VoiceSettings />);
    expect(listeners.get("voiceschanged")?.size).toBe(1);
    unmount();
    expect(listeners.get("voiceschanged")?.size).toBe(0);
    // Unmounting an inactive settings panel must not cancel chat playback.
    expect(cancel).not.toHaveBeenCalled();
    expect(playback.claimVoiceOutput).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(3000));
    expect(vi.getTimerCount()).toBe(0);
  });


  it("cancels only its own active preview on unmount", () => {
    voiceList = [{ name: "Local speech", lang: "en-US", default: true, voiceURI: "local:en" }];
    const view = render(<VoiceSettings />);
    fireEvent.click(screen.getByText("Preview voice"));
    expect(playback.claimVoiceOutput).toHaveBeenCalledTimes(1);
    expect(speak).toHaveBeenCalledTimes(1);
    expect(cancel).not.toHaveBeenCalled();

    view.unmount();
    expect(cancel).toHaveBeenCalledTimes(1);
    act(() => utterances[0].onend?.());
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("does not cancel unrelated audio when changing or resetting a voice without previewing", () => {
    voiceList = [{ name: "Local speech", lang: "en-US", default: true, voiceURI: "local:en" }];
    render(<VoiceSettings />);
    fireEvent.click(screen.getByText("Reset to Default"));
    expect(cancel).not.toHaveBeenCalled();
    expect(playback.claimVoiceOutput).not.toHaveBeenCalled();
    expect(speak).not.toHaveBeenCalled();
  });
});
