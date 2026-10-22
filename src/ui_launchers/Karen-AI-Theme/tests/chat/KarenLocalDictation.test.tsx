import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { KarenLocalDictation } from "@/components/chat/assistant-ui/KarenLocalDictation";
import { apiClient } from "@/lib/api";

const { composer } = vi.hoisted(() => ({
  composer: { text: "Existing", getState: vi.fn(), setText: vi.fn() },
}));
vi.mock("@assistant-ui/react", () => ({ useAui: () => ({ composer: () => composer }) }));
vi.mock("@/lib/api", () => ({
  apiClient: { get: vi.fn(), transcribeLocalAudio: vi.fn() },
}));

class Recorder {
  static instances: Recorder[] = [];
  state = "inactive";
  mimeType = "audio/webm";
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  constructor(_stream: MediaStream) { Recorder.instances.push(this); }
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["captured"]) });
    this.onstop?.();
  }
}

let stopTrack: ReturnType<typeof vi.fn>;
const originalArrayBuffer = Object.getOwnPropertyDescriptor(Blob.prototype, "arrayBuffer");
beforeEach(() => {
  Recorder.instances = [];
  // jsdom does not consistently implement Blob.arrayBuffer across versions.
  // The captured bytes are deliberately synthetic; decodeAudioData is mocked.
  Object.defineProperty(Blob.prototype, "arrayBuffer", {
    configurable: true,
    value: async () => new Uint8Array([0, 1, 2, 3]).buffer,
  });
  stopTrack = vi.fn();
  composer.getState.mockReturnValue({ text: "Existing" });
  vi.mocked(apiClient.get).mockResolvedValue({ status: "ready", transcription_available: true });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("AudioContext", class {
    decodeAudioData = vi.fn().mockResolvedValue({
      duration: 0.5, sampleRate: 16000, numberOfChannels: 1,
      getChannelData: () => new Float32Array(8000),
    });
    close = vi.fn().mockResolvedValue(undefined);
  });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) },
  });

});
afterEach(() => {
  cleanup();
  if (originalArrayBuffer) Object.defineProperty(Blob.prototype, "arrayBuffer", originalArrayBuffer);
  else delete (Blob.prototype as { arrayBuffer?: () => Promise<ArrayBuffer> }).arrayBuffer;
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

describe("local dictation composer acceptance with controlled browser devices", () => {
  it("records, sends WAV through authenticated API client, and edits draft without sending", async () => {
    vi.mocked(apiClient.transcribeLocalAudio).mockResolvedValue({
      text: "spoken words", engine: "faster-whisper-local", language: "en",
    });
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Stop local dictation" });
    fireEvent.click(screen.getByRole("button", { name: "Stop local dictation" }));
    await waitFor(() => expect(apiClient.transcribeLocalAudio).toHaveBeenCalledOnce());
    const [wav, duration] = vi.mocked(apiClient.transcribeLocalAudio).mock.calls[0];
    expect(wav.type).toBe("audio/wav");
    expect(wav.size).toBe(44 + 16000);
    expect(duration).toBe(0.5);
    await waitFor(() => expect(composer.setText).toHaveBeenCalledWith("Existing spoken words"));
    expect(stopTrack).toHaveBeenCalled();
  });

  it("ignores stale capability results from an earlier StrictMode effect", async () => {
    let resolveFirst!: (value: { status: string; transcription_available: boolean }) => void;
    vi.mocked(apiClient.get)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockResolvedValueOnce({ status: "ready", transcription_available: true });
    render(<StrictMode><KarenLocalDictation /></StrictMode>);
    await screen.findByRole("button", { name: "Start local dictation" });
    resolveFirst({ status: "unavailable", transcription_available: false });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Start local dictation" })).toBeTruthy();
  });

  it("never requests microphone when backend does not advertise local STT", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ status: "unavailable", transcription_available: false });
    render(<KarenLocalDictation />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/api/voice/capabilities"));
    expect(screen.queryByRole("button", { name: "Start local dictation" })).toBeNull();
  });

  it("cancels pending microphone permission and closes a late-granted stream", async () => {
    let grant!: (stream: MediaStream) => void;
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(
      () => new Promise<MediaStream>((resolve) => { grant = resolve; }),
    );
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel microphone permission request" }));
    grant({ getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream);
    await waitFor(() => expect(stopTrack).toHaveBeenCalledOnce());
    expect(Recorder.instances).toHaveLength(0);
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });

  it("a late permission grant from a canceled request cannot interrupt a newer recording", async () => {
    let grantOld!: (stream: MediaStream) => void;
    const oldStop = vi.fn();
    const newStop = vi.fn();
    vi.mocked(navigator.mediaDevices.getUserMedia)
      .mockImplementationOnce(() => new Promise<MediaStream>((resolve) => { grantOld = resolve; }))
      .mockResolvedValueOnce({
        getTracks: () => [{ stop: newStop }],
      } as unknown as MediaStream);
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel microphone permission request" }));
    fireEvent.click(screen.getByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Stop local dictation" });
    expect(Recorder.instances).toHaveLength(1);

    grantOld({ getTracks: () => [{ stop: oldStop }] } as unknown as MediaStream);
    await waitFor(() => expect(oldStop).toHaveBeenCalledOnce());
    expect(newStop).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Stop local dictation" })).toBeTruthy();
    expect(Recorder.instances).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Discard local recording" }));
    await waitFor(() => expect(newStop).toHaveBeenCalled());
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });

  it("discards a recording without an upload or a draft mutation", async () => {
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Discard local recording" });
    fireEvent.click(screen.getByRole("button", { name: "Discard local recording" }));
    await waitFor(() => expect(stopTrack).toHaveBeenCalled());
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });

  it("clears the old recording timer when the browser ends capture on its own", async () => {
    const clear = vi.spyOn(globalThis, "clearTimeout");
    try {
      render(<KarenLocalDictation />);
      fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
      await screen.findByRole("button", { name: "Stop local dictation" });
      const active = Recorder.instances[0];
      active.state = "inactive";
      active.ondataavailable?.({ data: new Blob(["captured"]) });
      active.onstop?.();
      await waitFor(() => expect(screen.getByRole("button", { name: "Start local dictation" })).toBeTruthy());
      expect(clear).toHaveBeenCalled();
      expect(stopTrack).toHaveBeenCalled();
    } finally {
      clear.mockRestore();
    }
  });

  it("ignores duplicate recorder stop events without a second transcript upload", async () => {
    vi.mocked(apiClient.transcribeLocalAudio).mockResolvedValue({
      text: "once", engine: "local", language: "en",
    });
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Stop local dictation" });
    const active = Recorder.instances[0];
    fireEvent.click(screen.getByRole("button", { name: "Stop local dictation" }));
    await waitFor(() => expect(apiClient.transcribeLocalAudio).toHaveBeenCalledOnce());
    active.onstop?.();
    await waitFor(() => expect(composer.setText).toHaveBeenCalledOnce());
    expect(apiClient.transcribeLocalAudio).toHaveBeenCalledOnce();
  });

  it("releases microphone tracks if the recorder fails after becoming inactive", async () => {
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Stop local dictation" });
    const active = Recorder.instances[0];
    active.state = "inactive";
    active.onerror?.();
    await waitFor(() => expect(stopTrack).toHaveBeenCalled());
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Audio capture failed.");
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });

  it("ignores late errors from a discarded recorder after a new session starts", async () => {
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Discard local recording" });
    const oldRecorder = Recorder.instances[0];
    fireEvent.click(screen.getByRole("button", { name: "Discard local recording" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    await screen.findByRole("button", { name: "Stop local dictation" });
    oldRecorder.onerror?.();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Stop local dictation" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Discard local recording" }));
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
  });

  it("reports permission denial without uploading or changing the draft", async () => {
    vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(new Error("denied"));
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Microphone access");
    expect(apiClient.transcribeLocalAudio).not.toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });
  it("cancels an in-flight authenticated upload without altering the draft", async () => {
    let resolveUpload!: (value: { text: string; engine: string; language: string }) => void;
    vi.mocked(apiClient.transcribeLocalAudio).mockImplementation(
      () => new Promise((resolve) => { resolveUpload = resolve; }),
    );
    render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop local dictation" }));
    await waitFor(() => expect(apiClient.transcribeLocalAudio).toHaveBeenCalledOnce());
    const signal = vi.mocked(apiClient.transcribeLocalAudio).mock.calls[0][2];
    fireEvent.click(screen.getByRole("button", { name: "Cancel local transcription" }));
    expect(signal?.aborted).toBe(true);
    resolveUpload({ text: "late response", engine: "local", language: "en" });
    await waitFor(() => expect(screen.queryByText("Transcribing locally…")).toBeNull());
    expect(composer.setText).not.toHaveBeenCalled();
  });

  it("aborts the upload and stops tracks when composer unmounts", async () => {
    vi.mocked(apiClient.transcribeLocalAudio).mockImplementation(
      () => new Promise(() => { /* Leave the mocked request pending. */ }),
    );
    const { unmount } = render(<KarenLocalDictation />);
    fireEvent.click(await screen.findByRole("button", { name: "Start local dictation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop local dictation" }));
    await waitFor(() => expect(apiClient.transcribeLocalAudio).toHaveBeenCalledOnce());
    const signal = vi.mocked(apiClient.transcribeLocalAudio).mock.calls[0][2];
    unmount();
    expect(signal?.aborted).toBe(true);
    expect(stopTrack).toHaveBeenCalled();
    expect(composer.setText).not.toHaveBeenCalled();
  });


});
