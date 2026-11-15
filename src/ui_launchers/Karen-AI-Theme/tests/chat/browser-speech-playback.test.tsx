import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  extractAssistantSpeech,
  KarenBrowserSpeechPlayback,
} from "@/components/chat/KarenBrowserSpeechPlayback";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

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
  it("requires an explicit click and uses the selected browser voice", () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({ ttsVoiceURI: "local-fr" }));
    render(<KarenBrowserSpeechPlayback message={{ id: "a1", content: "Bonjour Karen" }} />);
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    expect(speak).toHaveBeenCalledTimes(1);
    expect(spoken[0].voice?.voiceURI).toBe("local-fr");
    expect(spoken[0].text).toBe("Bonjour Karen");
    expect(screen.getByRole("button", { name: "Stop reading Karen's reply" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop reading Karen's reply" }));
    expect(cancel).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Read Karen's reply aloud" })).toBeTruthy();
  });

  it("reads SDK text parts, but ignores non-text presentations", () => {
    const msg = { parts: [
      { type: "text", text: "First" }, { type: "tool", value: "secret" },
      { type: "text", text: "second" },
    ] };
    expect(extractAssistantSpeech(msg)).toBe("First second");
    render(<KarenBrowserSpeechPlayback message={msg} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    expect(spoken[0].text).toBe("First second");
    expect(spoken[0].text).not.toContain("secret");
  });

  it("fails closed rather than silently choosing a different saved voice", () => {
    localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({ ttsVoiceURI: "missing" }));
    render(<KarenBrowserSpeechPlayback message={{ content: "Hello" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    expect(screen.getByRole("alert").textContent).toMatch(/saved browser voice is unavailable/i);
    expect(speak).not.toHaveBeenCalled();
  });

  it("plays all chunks without truncation, and never advances after cancellation", () => {
    const text = Array.from({ length: 300 }, (_, i) => "word" + i).join(" ");
    render(<KarenBrowserSpeechPlayback message={{ content: text }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    expect(spoken.length).toBe(1);
    act(() => spoken[0].onend?.());
    expect(spoken.length).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Stop reading Karen's reply" }));
    act(() => spoken[1].onend?.());
    expect(spoken.length).toBe(2);
  });

  it("has no autoplay on saved history mount and revokes speech on unmount", () => {
    const view = render(<KarenBrowserSpeechPlayback message={{ content: "Saved assistant reply" }} />);
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    view.unmount();
    expect(cancel).toHaveBeenCalled();
  });
});
