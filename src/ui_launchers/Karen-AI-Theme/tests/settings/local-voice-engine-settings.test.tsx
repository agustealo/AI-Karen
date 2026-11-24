import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LocalVoiceEngineSettings from "@/components/settings/LocalVoiceEngineSettings";
import {
  claimVoiceOutput, stopAssistantPlayback, useAssistantPlaybackPhase,
} from "@/components/chat/KarenBrowserSpeechPlayback";

const api = vi.hoisted(() => ({
  getVoiceEngineCatalog: vi.fn(),
  getVoiceSelection: vi.fn(),
  setVoiceSelection: vi.fn(),
  synthesizeLocalVoice: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiClient: api,
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) { super(message); }
  },
}));
vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: api.toast }),
}));

const catalog = {
  contract_version: "1.0.0",
  engines: [{
    engine_id: "pocket-tts",
    display_name: "Pocket TTS",
    plugin_version: "1.0.0",
    modality: "tts",
    status: "ready",
    model_id: "kyutai/pocket-tts",
    model_revision: "approved-revision",
    features: { synthesis: true, streaming: false, voice_cloning: false },
    voices: [{ id: "alba", name: "Alba", language: "en" }],
  }],
};

beforeEach(() => {
  api.getVoiceEngineCatalog.mockReset();
  api.getVoiceSelection.mockReset();
  api.setVoiceSelection.mockReset();
  api.synthesizeLocalVoice.mockReset();
  api.toast.mockReset();
  api.getVoiceEngineCatalog.mockResolvedValue(catalog);
  api.getVoiceSelection.mockResolvedValue({
    voice: { engine_id: null, voice_id: null }, available: false,
  });
  api.setVoiceSelection.mockImplementation(async (engine_id, voice_id) => ({
    status: "success", voice: { engine_id, voice_id }, available: Boolean(engine_id),
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("governed local engine voice settings", () => {
  it("renders no fabricated engine when backend inventory is empty", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue({ contract_version: "1.0.0", engines: [] });
    render(<LocalVoiceEngineSettings />);
    expect(screen.getByText(/Verifying installed local speech engines/)).toBeTruthy();
    await screen.findByText("No Local TTS Plugin Ready");
    expect(screen.queryByText("Pocket TTS")).toBeNull();
    expect(screen.queryByText("Preview local voice")).toBeNull();
  });

  it("persists only a verified engine and voice with an acknowledged result", async () => {
    api.getVoiceSelection.mockResolvedValueOnce({
      voice: { engine_id: null, voice_id: null }, available: false,
    }).mockResolvedValueOnce({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Browser speech \(device-dependent\)/);
    fireEvent.click(screen.getByRole("combobox", { name: "Speech output source" }));
    fireEvent.click(screen.getByText("Pocket TTS · TTS · Local"));
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByText("Save speech engine"));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledWith("pocket-tts", "alba"));
    await waitFor(() => expect(api.getVoiceSelection).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference saved",
    })));
  });

  it("does not claim save success when backend rejects persistence", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    api.setVoiceSelection.mockRejectedValue(new Error("revision conflict"));
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByText("Save speech engine"));
    await waitFor(() => expect(api.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference not saved",
      variant: "destructive",
    })));
  });

  it("rejects a successful write receipt when the persisted voice differs", async () => {
    // The settings panel must not claim success on a response alone.
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: null, voice_id: null }, available: false,
    });
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Browser speech \(device-dependent\)/);
    fireEvent.click(screen.getByRole("combobox", { name: "Speech output source" }));
    fireEvent.click(screen.getByText("Pocket TTS · TTS · Local"));
    fireEvent.click(screen.getByText("Save speech engine"));
    await waitFor(() => expect(api.getVoiceSelection).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(api.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference not saved",
      variant: "destructive",
    })));
    expect(api.toast).not.toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference saved",
    }));
    expect(screen.getByText(/could not verify the saved voice preference/)).toBeTruthy();
  });

  it("reconciles backend truth and unlocks Save after refresh races with a pending write", async () => {
    const browser = { voice: { engine_id: null, voice_id: null }, available: false };
    const local = { voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true };
    api.getVoiceSelection
      .mockResolvedValueOnce(browser)
      .mockResolvedValueOnce(browser)
      .mockResolvedValueOnce(local);
    let completeSave!: (receipt: { status: string; voice: typeof local.voice; available: boolean }) => void;
    api.setVoiceSelection.mockImplementationOnce(() => new Promise((resolve) => {
      completeSave = resolve;
    }));

    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Browser speech \(device-dependent\)/);
    fireEvent.click(screen.getByRole("combobox", { name: "Speech output source" }));
    fireEvent.click(screen.getByText("Pocket TTS · TTS · Local"));
    fireEvent.click(screen.getByRole("button", { name: "Save speech engine" }));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Refresh local engines" }));
    await waitFor(() => expect(api.getVoiceSelection).toHaveBeenCalledTimes(2));
    // The first refresh finishes before the pending backend write.
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Speech output source" }).textContent).toMatch(/Browser speech/));
    expect((screen.getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);

    await act(async () => completeSave({
      status: "success", voice: local.voice, available: true,
    }));
    await waitFor(() => expect(api.getVoiceSelection).toHaveBeenCalledTimes(3));
    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Save speech engine" }) as HTMLButtonElement).disabled).toBe(false);
    });
    // A superseded save never emits a false success toast, and the panel
    // re-reads the final durable choice instead of displaying old state.
    expect(api.toast).not.toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference saved",
    }));
    expect(screen.getByRole("combobox", { name: "Speech output source" }).textContent).toMatch(/Pocket TTS/);
  });

  it("late events from a stopped preview cannot terminate a later preview", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    const audio: Array<{
      src: string;
      onended: (() => void) | null;
      onerror: (() => void) | null;
      pause: ReturnType<typeof vi.fn>;
      play: ReturnType<typeof vi.fn>;
    }> = [];
    const create = vi.fn()
      .mockReturnValueOnce("blob:voice-one")
      .mockReturnValueOnce("blob:voice-two");
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
    vi.stubGlobal("Audio", class {
      src: string;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      pause = vi.fn();
      play = vi.fn().mockResolvedValue(undefined);
      constructor(url: string) {
        this.src = url;
        audio.push(this);
      }
    });
    api.synthesizeLocalVoice.mockResolvedValue(new Blob([new Uint8Array(48)], { type: "audio/wav" }));
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(audio).toHaveLength(1));
    const staleEnd = audio[0].onended;
    const staleError = audio[0].onerror;
    fireEvent.click(screen.getByRole("button", { name: "Stop local preview" }));
    expect(revoke).toHaveBeenCalledWith("blob:voice-one");
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(audio).toHaveLength(2));
    await act(async () => {
      staleEnd?.();
      staleError?.();
    });
    expect(audio[1].pause).not.toHaveBeenCalled();
    expect(revoke).not.toHaveBeenCalledWith("blob:voice-two");
    expect(screen.getByRole("button", { name: "Stop local preview" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop local preview" }));
    expect(revoke).toHaveBeenCalledWith("blob:voice-two");
    vi.unstubAllGlobals();
  });

  it("shows stored engine revocation instead of substituting another voice", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "retired-local", voice_id: "old" }, available: false,
    });
    render(<LocalVoiceEngineSettings />);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent",
      expect.stringMatching(/saved local speech engine or voice is no longer available/i));
    expect(screen.getByText("Save speech engine").closest("button")?.disabled).toBe(true);
  });

  it("exposes the backend-backed Voice Studio without inventing a ready model", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue({ contract_version: "1.0.0", engines: [] });
    render(<LocalVoiceEngineSettings />);
    expect(screen.getByText("Local Voice Studio")).toBeTruthy();
    await screen.findByText("No Local TTS Plugin Ready");
    expect(screen.getByTestId("voice-studio-readiness").textContent).toMatch(/No local engines ready/);
    expect(screen.getByText(/install and license its approved model/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Preview local voice" })).toBeNull();
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
  });

  it("allows explicit sample text and verified voice selection before preview", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue({
      ...catalog,
      engines: [{
        ...catalog.engines[0],
        voices: [
          { id: "alba", name: "Alba", language: "en" },
          { id: "sage", name: "Sage", language: "en" },
        ],
      }],
    });
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    const createURL = vi.fn(() => "blob:studio-sample");
    const revokeURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeURL });
    const play = vi.fn().mockResolvedValue(undefined);
    const pause = vi.fn();
    vi.stubGlobal("Audio", class {
      src: string;
      onended: (() => void) | null = null;
      onerror: (() => void) | null = null;
      play = play;
      pause = pause;
      constructor(url: string) { this.src = url; }
    });
    api.synthesizeLocalVoice.mockResolvedValue(
      new Blob([new Uint8Array(48)], { type: "audio/wav" }),
    );

    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    expect(screen.getByTestId("voice-studio-saved-selection").textContent).toContain("Pocket TTS · Alba");
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Choose Sage local voice" }));
    expect(screen.getByRole("button", { name: "Choose Sage local voice" }).getAttribute("aria-pressed")).toBe("true");
    const input = screen.getByRole("textbox", { name: "Try a spoken sample" });
    fireEvent.change(input, { target: { value: "The studio should speak precisely this sample." } });
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(1));
    expect(api.synthesizeLocalVoice.mock.calls[0].slice(0, 3)).toEqual([
      "pocket-tts", "sage", "The studio should speak precisely this sample.",
    ]);
    await waitFor(() => expect(play).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "Stop local preview" }));
    expect(pause).toHaveBeenCalledOnce();
    expect(revokeURL).toHaveBeenCalledWith("blob:studio-sample");
    expect(api.setVoiceSelection).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("does not synthesize an empty studio sample", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.change(screen.getByRole("textbox", { name: "Try a spoken sample" }), {
      target: { value: "   " },
    });
    expect((screen.getByRole("button", { name: "Preview local voice" }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
  });

  it("previews WAV only after explicit user action, without sending a chat message", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    const createUrl = vi.fn(() => "blob:authorized-audio");
    const revokeUrl = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createUrl });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeUrl });
    const play = vi.fn(async () => undefined);
    const pause = vi.fn();
    vi.stubGlobal("Audio", class {
      src: string;
      onended?: () => void;
      onerror?: () => void;
      play = play;
      pause = pause;
      constructor(url: string) { this.src = url; }
    });
    api.synthesizeLocalVoice.mockResolvedValue(new Blob([new Uint8Array(44)], { type: "audio/wav" }));
    render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Preview local voice"));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(play).toHaveBeenCalledOnce());
    expect(api.synthesizeLocalVoice.mock.calls[0][0]).toBe("pocket-tts");
    expect(api.synthesizeLocalVoice.mock.calls[0][1]).toBe("alba");
    fireEvent.click(screen.getByText("Stop local preview"));
    expect(pause).toHaveBeenCalledOnce();
    expect(revokeUrl).toHaveBeenCalledWith("blob:authorized-audio");
    vi.unstubAllGlobals();
  });
  it("scopes the plugin workspace to Pocket TTS even if another engine is saved", async () => {
    const other = {
      ...catalog.engines[0],
      engine_id: "other-tts",
      display_name: "Another engine",
    };
    api.getVoiceEngineCatalog.mockResolvedValue({
      contract_version: "1.0.0", engines: [other, catalog.engines[0]],
    });
    api.getVoiceSelection
      .mockResolvedValueOnce({
        voice: { engine_id: "other-tts", voice_id: "alba" }, available: true,
      })
      .mockResolvedValueOnce({
        voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
      });
    render(<LocalVoiceEngineSettings engineFilter="pocket-tts" />);
    await screen.findByText("Pocket TTS Voice Lab");
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    expect(screen.getByTestId("pocket-tts-engine-scope").textContent).toContain("Pocket TTS");
    expect(screen.queryByText("Another engine")).toBeNull();
    expect(screen.queryByText("Browser speech (device-dependent)")).toBeNull();
    expect(screen.getByRole("button", { name: "Choose Alba local voice" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save speech engine" }));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledWith("pocket-tts", "alba"));
    await waitFor(() => expect(api.toast).toHaveBeenCalledWith(expect.objectContaining({
      title: "Speech engine preference saved",
    })));
  });

  it("disables Pocket synthesis and saving when the live catalog has no Pocket engine", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue({
      contract_version: "1.0.0",
      engines: [{
        ...catalog.engines[0],
        engine_id: "another-tts",
        display_name: "Another engine",
      }],
    });
    render(<LocalVoiceEngineSettings engineFilter="pocket-tts" />);
    await screen.findByText("Pocket TTS Not Ready");
    expect(screen.queryByRole("button", { name: "Preview local voice" })).toBeNull();
    expect((screen.getByRole("button", { name: "Save speech engine" }) as HTMLButtonElement).disabled)
      .toBe(true);
    expect(screen.getByTestId("pocket-tts-engine-scope")).toBeTruthy();
    expect(api.setVoiceSelection).not.toHaveBeenCalled();
    expect(api.synthesizeLocalVoice).not.toHaveBeenCalled();
  });


  it("aborts an unmounted preview before synthesis can allocate audio", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    let finishSynthesis!: (blob: Blob) => void;
    api.synthesizeLocalVoice.mockImplementation(() => new Promise<Blob>((resolve) => {
      finishSynthesis = resolve;
    }));
    const create = vi.fn(() => "blob:late-preview");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });

    const view = render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(1));
    const signal = api.synthesizeLocalVoice.mock.calls[0][3] as AbortSignal;
    expect(signal.aborted).toBe(false);

    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => finishSynthesis(new Blob([new Uint8Array(44)], { type: "audio/wav" })));
    expect(create).not.toHaveBeenCalled();
    expect(api.toast).not.toHaveBeenCalled();
  });

  it("releases a playing WAV exactly once on unmount despite late playback events", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    const revoke = vi.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true, value: vi.fn(() => "blob:owned-local-sample"),
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
    const outputs: Array<{
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
        outputs.push(this);
      }
    });
    api.synthesizeLocalVoice.mockResolvedValue(new Blob([new Uint8Array(44)], { type: "audio/wav" }));

    const view = render(<LocalVoiceEngineSettings />);
    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(outputs).toHaveLength(1));
    const previousEnd = outputs[0].onended;
    const previousError = outputs[0].onerror;
    await waitFor(() => expect(outputs[0].play).toHaveBeenCalledTimes(1));
    view.unmount();

    expect(outputs[0].pause).toHaveBeenCalledTimes(1);
    expect(outputs[0].src).toBe("");
    expect(outputs[0].onended).toBeNull();
    expect(outputs[0].onerror).toBeNull();
    expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:owned-local-sample");
    await act(async () => { previousEnd?.(); previousError?.(); });
    expect(outputs[0].pause).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("retire chat output and lets global Stop abort a local synthesis preview", async () => {
    api.getVoiceSelection.mockResolvedValue({
      voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
    });
    let finishSynthesis!: (blob: Blob) => void;
    api.synthesizeLocalVoice.mockImplementation(() => new Promise<Blob>((resolve) => {
      finishSynthesis = resolve;
    }));
    const create = vi.fn(() => "blob:unwanted");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });

    const retireChat = vi.fn();
    let releaseChat!: () => void;
    act(() => { releaseChat = claimVoiceOutput(retireChat, "speaking"); });
    const Phase = () => <span data-testid="shared-voice-phase">{useAssistantPlaybackPhase()}</span>;
    const view = render(<><LocalVoiceEngineSettings /><Phase /></>);

    await screen.findByText(/Model: kyutai\/pocket-tts/);
    fireEvent.click(screen.getByRole("button", { name: "Preview local voice" }));
    await waitFor(() => expect(api.synthesizeLocalVoice).toHaveBeenCalledTimes(1));
    expect(retireChat).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("shared-voice-phase").textContent).toBe("preparing");

    const signal = api.synthesizeLocalVoice.mock.calls[0][3] as AbortSignal;
    act(() => stopAssistantPlayback());
    expect(signal.aborted).toBe(true);
    expect(screen.getByTestId("shared-voice-phase").textContent).toBe("idle");
    await act(async () => finishSynthesis(new Blob([new Uint8Array(44)], { type: "audio/wav" })));
    expect(create).not.toHaveBeenCalled();
    act(() => releaseChat());
    view.unmount();
  });
});
