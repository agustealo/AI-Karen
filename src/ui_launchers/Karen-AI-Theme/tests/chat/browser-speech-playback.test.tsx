import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  extractAssistantSpeech,
  KarenBrowserSpeechPlayback,
} from "@/components/chat/KarenBrowserSpeechPlayback";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

const local = vi.hoisted(() => ({
  get: vi.fn(),
  synthesize: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiClient: {
    get: local.get,
    synthesizeLocalSpeech: local.synthesize,
  },
}));

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
  local.get.mockReset().mockResolvedValue({
    synthesis_available: false, synthesis_engine: null, synthesis_voice_id: null,
  });
  local.synthesize.mockReset().mockResolvedValue(new Blob(["RIFF"], { type: "audio/wav" }));
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


describe("authenticated local speech replay", () => {
  class AudioDouble {
    static instances: AudioDouble[] = [];
    src: string;
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    pause = vi.fn();
    play = vi.fn().mockResolvedValue(undefined);
    removeAttribute = vi.fn();
    constructor(src: string) {
      this.src = src;
      AudioDouble.instances.push(this);
    }
  }

  beforeEach(() => {
    AudioDouble.instances = [];
    vi.stubGlobal("Audio", AudioDouble);
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:local-karen"),
      revokeObjectURL: vi.fn(),
    }));
  });

  it("does not synthesize, stream or play model audio before explicit user action", () => {
    render(<KarenBrowserSpeechPlayback message={{ content: "Saved reply" }} />);
    expect(local.get).not.toHaveBeenCalled();
    expect(local.synthesize).not.toHaveBeenCalled();
    expect(AudioDouble.instances).toHaveLength(0);
  });

  it("fails closed when backend capability is unverified without browser vendor fallback", async () => {
    render(<KarenBrowserSpeechPlayback message={{ content: "Saved reply" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Try Karen local voice" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/not ready/i));
    expect(local.get).toHaveBeenCalledWith("/api/voice/capabilities");
    expect(local.synthesize).not.toHaveBeenCalled();
    expect(speak).not.toHaveBeenCalled();
    expect(AudioDouble.instances).toHaveLength(0);
  });

  it("requests actual WAV only after verified readiness and revokes audio on Stop", async () => {
    local.get.mockResolvedValue({
      synthesis_available: true,
      synthesis_engine: "piper-onnx-local",
      synthesis_voice_id: "en_US-local",
    });
    render(<KarenBrowserSpeechPlayback message={{ content: "Hello Karen" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Try Karen local voice" }));
    await waitFor(() => expect(local.synthesize).toHaveBeenCalledTimes(1));
    expect(local.synthesize.mock.calls[0][0]).toBe("Hello Karen");
    expect(local.synthesize.mock.calls[0][1]).toBe("en_US-local");
    await waitFor(() => expect(AudioDouble.instances).toHaveLength(1));
    expect(AudioDouble.instances[0].play).toHaveBeenCalledTimes(1);
    expect(speak).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop Karen local voice" }));
    expect(AudioDouble.instances[0].pause).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:local-karen");
    expect(local.synthesize.mock.calls[0][2].aborted).toBe(true);
  });

  it("does not play late synthesis after account-owned assistant unmount", async () => {
    let resolveAudio!: (value: Blob) => void;
    local.get.mockResolvedValue({
      synthesis_available: true,
      synthesis_engine: "piper-onnx-local",
      synthesis_voice_id: "en_US-local",
    });
    local.synthesize.mockImplementationOnce(() => new Promise((resolve) => { resolveAudio = resolve; }));
    const view = render(<KarenBrowserSpeechPlayback message={{ content: "Old account reply" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Try Karen local voice" }));
    await waitFor(() => expect(local.synthesize).toHaveBeenCalledTimes(1));
    view.unmount();
    await act(async () => resolveAudio(new Blob(["RIFF"], { type: "audio/wav" })));
    expect(AudioDouble.instances).toHaveLength(0);
  });
});
