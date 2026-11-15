import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  extractAssistantSpeech,
  KarenBrowserSpeechPlayback,
} from "@/components/chat/KarenBrowserSpeechPlayback";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

const api = vi.hoisted(() => ({
  getVoiceSelection: vi.fn(),
  synthesizeLocalVoice: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiClient: api }));

const voices = [
  { voiceURI: "local-en", name: "Local English", lang: "en-US", default: true },
  { voiceURI: "local-fr", name: "Local French", lang: "fr-FR", default: false },
];
let spoken: Array<{
  text: string;
  voice?: (typeof voices)[number];
  onend?: () => void;
  onerror?: () => void;
}>;
let speak: ReturnType<typeof vi.fn>;
let cancel: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  api.getVoiceSelection.mockReset();
  api.synthesizeLocalVoice.mockReset();
  api.getVoiceSelection.mockResolvedValue({
    voice: { engine_id: null, voice_id: null }, available: false,
  });
  spoken = [];
  speak = vi.fn();
  cancel = vi.fn();
  Object.defineProperty(window, "speechSynthesis", {
    configurable: true,
    value: { getVoices: () => voices, speak, cancel },
  });
  vi.stubGlobal("SpeechSynthesisUtterance", class {
    text: string;
    voice?: (typeof voices)[number];
    lang?: string;
    onend?: () => void;
    onerror?: () => void;
    constructor(text: string) {
      this.text = text;
      spoken.push(this);
    }
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "speechSynthesis");
  vi.restoreAllMocks();
});

describe("canonical assistant speech playback", () => {
  it("requires an explicit click and uses a selected browser voice", async () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({ ttsVoiceURI: "local-fr" }));
    render(<KarenBrowserSpeechPlayback message={{ id: "a1", content: "Bonjour Karen" }} />);
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect(spoken[0].voice?.voiceURI).toBe("local-fr");
    expect(spoken[0].text).toBe("Bonjour Karen");
    fireEvent.click(screen.getByRole("button", { name: "Stop reading Karen's reply" }));
    expect(cancel).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Read Karen's reply aloud" })).toBeTruthy();
  });

  it("reads SDK text parts, never non-text presentations", async () => {
    const msg = { parts: [
      { type: "text", text: "First" }, { type: "tool", value: "secret" },
      { type: "text", text: "second" },
    ] };
    expect(extractAssistantSpeech(msg)).toBe("First second");
    render(<KarenBrowserSpeechPlayback message={msg} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(spoken.length).toBe(1));
    expect(spoken[0].text).toBe("First second");
    expect(spoken[0].text).not.toContain("secret");
  });

  it("fails closed rather than silently choosing a different saved browser voice", async () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({ ttsVoiceURI: "missing" }));
    render(<KarenBrowserSpeechPlayback message={{ content: "Hello" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/saved browser voice is unavailable/i));
    expect(speak).not.toHaveBeenCalled();
  });

  it("plays all browser chunks without truncation, and never advances after cancellation", async () => {
    const text = Array.from({ length: 300 }, (_, i) => "word" + i).join(" ");
    render(<KarenBrowserSpeechPlayback message={{ content: text }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(spoken.length).toBe(1));
    act(() => spoken[0].onend?.());
    await waitFor(() => expect(spoken.length).toBe(2));
    fireEvent.click(screen.getByRole("button", { name: "Stop reading Karen's reply" }));
    act(() => spoken[1].onend?.());
    expect(spoken.length).toBe(2);
  });

  it("has no autoplay on saved history and revokes speech on unmount", async () => {
    const view = render(<KarenBrowserSpeechPlayback message={{ content: "Saved assistant reply" }} />);
    expect(speak).not.toHaveBeenCalled();
    expect(api.getVoiceSelection).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    view.unmount();
    expect(cancel).toHaveBeenCalled();
  });

  it("runs the user-selected local engine without invoking browser speech", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    api.synthesizeLocalVoice.mockResolvedValue(new Blob([new Uint8Array(48)], { type: "audio/wav" }));
    const create = vi.fn(() => "blob:karen");
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
    const pause = vi.fn();
    const play = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("Audio", class {
      src: string;
      onended?: () => void;
      onerror?: () => void;
      pause = pause;
      play = play;
      constructor(url: string) { this.src = url; }
    });
    render(<KarenBrowserSpeechPlayback message={{ content: "Hello from Pocket." }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledOnce());
    expect(api.synthesizeLocalVoice.mock.calls[0].slice(0, 3)).toEqual([
      "pocket-tts", "alba", "Hello from Pocket.",
    ]);
    await waitFor(() => expect(play).toHaveBeenCalledOnce());
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop reading Karen's reply" }));
    expect(pause).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:karen");
  });

  it("never falls back to vendor speech when selected model is unavailable", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: false,
    });
    render(<KarenBrowserSpeechPlayback message={{ content: "Private" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/local speech engine is unavailable/i));
    expect(speak).not.toHaveBeenCalled();
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
  });

  it("fails closed when user voice preferences cannot be verified", async () => {
    api.getVoiceSelection.mockRejectedValue(new Error("network unavailable"));
    render(<KarenBrowserSpeechPlayback message={{ content: "Private" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/network unavailable/i));
    expect(speak).not.toHaveBeenCalled();
  });
});
