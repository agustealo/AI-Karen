import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  claimVoiceOutput,
  extractAssistantSpeech,
  KarenBrowserSpeechPlayback,
  markVoiceOutputSpeaking,
  stopAssistantPlayback,
  useAssistantPlaybackPhase,
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

function PlaybackDock(): ReactNode {
  const phase = useAssistantPlaybackPhase();
  return (
    <div data-testid="speech-dock-test">
      <span data-testid="active-speech-phase">{phase}</span>
      <button type="button" disabled={phase === "idle"} onClick={stopAssistantPlayback}>
        Stop speech from dock
      </button>
    </div>
  );
}

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

  it("reads a long unspaced response without dropping text or splitting emoji pairs", async () => {
    // Long URLs, hashes and generated identifiers have no word boundary.
    // All speech chunks must stay within the same bounded synthesis envelope.
    const text = "🙂".repeat(401) + "x".repeat(5000);
    render(<KarenBrowserSpeechPlayback message={{ content: text }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    let consumed = 0;
    let chunkIndex = 0;
    while (consumed < text.length) {
      const expectedCount = chunkIndex + 1;
      await waitFor(() => expect(spoken.length).toBe(expectedCount));
      const utterance = spoken[chunkIndex];
      expect(utterance.text.length).toBeLessThanOrEqual(700);
      // Every surrogate pair in the original text must remain intact.
      expect(utterance.text).not.toMatch(/[\uD800-\uDBFF]$/);
      expect(utterance.text).not.toMatch(/^[\uDC00-\uDFFF]/);
      consumed += utterance.text.length;
      act(() => utterance.onend?.());
      chunkIndex++;
      if (chunkIndex > 16) throw new Error("Speech chunking did not terminate");
    }
    expect(spoken.map((part) => part.text).join("")).toBe(text);
    expect(spoken.length).toBeGreaterThan(1);
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

  it("retired WAV chunk callbacks cannot interrupt or erase cancellation for the next chunk", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    api.synthesizeLocalVoice.mockResolvedValue(
      new Blob([new Uint8Array(48)], { type: "audio/wav" }),
    );
    const urls = ["blob:chunk-one", "blob:chunk-two", "blob:chunk-three"];
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true, value: vi.fn(() => urls.shift()),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
    const played: Array<{
      src: string;
      onended: (() => void) | null;
      onerror: (() => void) | null;
      pause: ReturnType<typeof vi.fn>;
      play: ReturnType<typeof vi.fn>;
    }> = [];
    vi.stubGlobal("Audio", class {
      src: string;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      pause = vi.fn();
      play = vi.fn().mockResolvedValue(undefined);
      constructor(url: string) {
        this.src = url;
        played.push(this);
      }
    });
    // At least two local WAV requests through the shared bounded chunker.
    render(<>
      <KarenBrowserSpeechPlayback message={{ content: "word ".repeat(230) }} />
      <PlaybackDock />
    </>);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(played).toHaveLength(1));
    const oldEnd = played[0].onended;
    const oldError = played[0].onerror;
    act(() => oldEnd?.());
    await waitFor(() => expect(played).toHaveLength(2));
    await act(async () => {
      oldEnd?.();
      oldError?.();
    });
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("speaking");
    expect(played[1].pause).not.toHaveBeenCalled();
    expect(revoke).not.toHaveBeenCalledWith("blob:chunk-two");
    fireEvent.click(screen.getByRole("button", { name: "Stop speech from dock" }));
    expect(played[1].pause).toHaveBeenCalled();
    expect(revoke).toHaveBeenCalledWith("blob:chunk-two");
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
    expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(2);
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

  it("exposes preparing and speaking phases to a global Stop control without replaying audio", async () => {
    let resolvePreference!: (value: { voice: { engine_id: null; voice_id: null }; available: false }) => void;
    api.getVoiceSelection.mockImplementationOnce(() => new Promise((resolve) => {
      resolvePreference = resolve;
    }));
    render(<>
      <KarenBrowserSpeechPlayback message={{ id: "spoken-a", content: "First message" }} />
      <PlaybackDock />
    </>);
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(screen.getByTestId("active-speech-phase").textContent).toBe("preparing"));
    expect(speak).not.toHaveBeenCalled();
    await act(async () => resolvePreference({
      voice: { engine_id: null, voice_id: null }, available: false,
    }));
    await waitFor(() => expect(screen.getByTestId("active-speech-phase").textContent).toBe("speaking"));
    fireEvent.click(screen.getByRole("button", { name: "Stop speech from dock" }));
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
    expect(screen.getByRole("button", { name: "Read Karen's reply aloud" })).toBeTruthy();
    expect(cancel).toHaveBeenCalled();
    act(() => spoken[0].onend?.());
    expect(speak).toHaveBeenCalledTimes(1);
  });

  it("global Stop aborts an in-flight local synthesis before it creates audio", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    let deliver!: (audio: Blob) => void;
    api.synthesizeLocalVoice.mockImplementation(() => new Promise((resolve) => {
      deliver = resolve;
    }));
    const create = vi.fn(() => "blob:voice-leak");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
    render(<>
      <KarenBrowserSpeechPlayback message={{ content: "Local speech" }} />
      <PlaybackDock />
    </>);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("preparing");
    fireEvent.click(screen.getByRole("button", { name: "Stop speech from dock" }));
    expect(api.synthesizeLocalVoice.mock.calls[0][3].aborted).toBe(true);
    await act(async () => deliver(new Blob([new Uint8Array(48)], { type: "audio/wav" })));
    expect(create).not.toHaveBeenCalled();
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
  });

  it("replaces a speaking message without leaving two active playbacks", async () => {
    render(<>
      <KarenBrowserSpeechPlayback message={{ id: "older", content: "Older reply" }} />
      <KarenBrowserSpeechPlayback message={{ id: "newer", content: "Newer reply" }} />
      <PlaybackDock />
    </>);
    const buttons = screen.getAllByRole("button", { name: "Read Karen's reply aloud" });
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(2));
    expect(cancel).toHaveBeenCalled();
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("speaking");
    expect(screen.getByRole("button", { name: "Stop speech from dock" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop speech from dock" }));
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
  });

  it("fails closed when user voice preferences cannot be verified", async () => {
    api.getVoiceSelection.mockRejectedValue(new Error("secret-token=private network unavailable"));
    render(<KarenBrowserSpeechPlayback message={{ content: "Private" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Read Karen's reply aloud" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/could not prepare speech/i));
    expect(speak).not.toHaveBeenCalled();
  });

  it("keeps one tab-wide speech owner and ignores stale releases", () => {
    render(<PlaybackDock />);
    const retireFirst = vi.fn();
    const retireSecond = vi.fn();
    let releaseFirst!: () => void;
    let releaseSecond!: () => void;
    act(() => { releaseFirst = claimVoiceOutput(retireFirst, "speaking"); });
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("speaking");
    act(() => { releaseSecond = claimVoiceOutput(retireSecond, "preparing"); });
    expect(retireFirst).toHaveBeenCalledTimes(1);

    act(() => releaseFirst());
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("preparing");
    act(() => markVoiceOutputSpeaking(retireSecond));
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("speaking");

    act(() => stopAssistantPlayback());
    expect(retireSecond).toHaveBeenCalledTimes(1);
    act(() => releaseSecond());
    expect(screen.getByTestId("active-speech-phase").textContent).toBe("idle");
  });
});
