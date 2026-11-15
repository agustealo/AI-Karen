import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceSettings from "@/components/settings/VoiceSettings";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

const notifications = vi.hoisted(() => ({ toast: vi.fn() }));
const voiceApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiClient: { get: voiceApi.get } }));
vi.mock("@/hooks/use-toast", () => ({ useToast: () => notifications }));

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
    voiceApi.get.mockReset().mockResolvedValue({
      synthesis_available: false, synthesis_engine: null, synthesis_voice_id: null,
    });
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

  it("never fabricates a local voice from browser inventory", async () => {
    voiceList = [{ name: "Browser", lang: "en-US", default: true, voiceURI: "browser:en" }];
    render(<VoiceSettings />);
    expect(voiceApi.get).not.toHaveBeenCalled();
    expect(screen.getByText("Karen local speech engine")).toBeTruthy();
    fireEvent.click(screen.getByText("Check local voice engine"));
    await act(async () => { await Promise.resolve(); });
    expect(voiceApi.get).toHaveBeenCalledWith("/api/voice/capabilities");
    expect(screen.getByText(/No verified local synthesis engine is ready/)).toBeTruthy();
    expect(screen.queryByText(/Local synthesis ready:/)).toBeNull();
  });

  it("only displays backend-attested local Piper identity", async () => {
    voiceApi.get.mockResolvedValue({
      synthesis_available: true,
      synthesis_engine: "piper-onnx-local",
      synthesis_voice_id: "en_US-karen",
    });
    render(<VoiceSettings />);
    fireEvent.click(screen.getByText("Check local voice engine"));
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText(/Local synthesis ready: piper-onnx-local/)).toBeTruthy();
    expect(screen.getByText(/en_US-karen/)).toBeTruthy();
  });

  it("clears discovery listeners and pending retries when unmounted", () => {
    const { unmount } = render(<VoiceSettings />);
    expect(listeners.get("voiceschanged")?.size).toBe(1);
    unmount();
    expect(listeners.get("voiceschanged")?.size).toBe(0);
    expect(cancel).toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(3000));
    expect(vi.getTimerCount()).toBe(0);
  });
});
