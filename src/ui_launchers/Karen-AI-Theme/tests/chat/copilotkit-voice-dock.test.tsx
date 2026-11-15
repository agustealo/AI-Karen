import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { KarenCopilotVoiceDock } from "@/components/chat/copilotkit/KarenCopilotVoiceDock";

const api = vi.hoisted(() => ({
  getVoiceEngineCatalog: vi.fn(),
  getVoiceSelection: vi.fn(),
  setVoiceSelection: vi.fn(),
  get: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiClient: api }));
vi.mock("@/components/chat/KarenBrowserDictationCapture", () => ({
  KarenBrowserDictationCapture: () => <button type="button">Optional browser microphone</button>,
}));

const port = { readText: () => "", writeText: vi.fn() };
const browser = {
  voice: { engine_id: null, voice_id: null }, available: false,
};
const approved = {
  voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: true,
};
const revoked = {
  voice: { engine_id: "pocket-tts", voice_id: "alba" }, available: false,
};
const engines = {
  contract_version: "1.0.0",
  engines: [{
    engine_id: "pocket-tts",
    display_name: "Pocket TTS",
    plugin_version: "1.0.0",
    modality: "tts",
    status: "ready",
    model_id: "kyutai/pocket-tts",
    model_revision: "db04f0e653473e5c7333c69686ac92b7460b0c1d",
    features: { synthesis: true, streaming: false, voice_cloning: false },
    voices: [
      { id: "alba", name: "Alba", language: "en" },
      { id: "marius", name: "Marius", language: "en" },
    ],
  }],
};
const empty = { contract_version: "1.0.0", engines: [] };

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  port.writeText.mockReset();
  api.getVoiceEngineCatalog.mockResolvedValue(engines);
  api.getVoiceSelection.mockResolvedValue(browser);
  api.setVoiceSelection.mockResolvedValue({
    status: "success", ...approved,
  });
  api.get.mockResolvedValue({ status: "ready", transcription_available: true });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("first-class Copilot voice dock", () => {
  it("surfaces separately verified listen and speak capabilities without auto speech", async () => {
    render(<KarenCopilotVoiceDock port={port} />);
    expect(await screen.findByRole("button", { name: "Start local dictation" })).toBeTruthy();
    expect(screen.getByTestId("karen-copilot-voice-output").textContent)
      .toContain("Open voice options to check");
    expect(api.getVoiceEngineCatalog).not.toHaveBeenCalled();
    expect(screen.getByTestId("karen-copilot-voice-listening").textContent)
      .toContain("Local dictation ready");
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    await screen.findByText("Pocket TTS · Local");
    expect(screen.getByRole("combobox", { name: "Speech output engine" })).toBeTruthy();
    expect(screen.getByText("Pocket TTS · Local")).toBeTruthy();
    expect(api.setVoiceSelection).not.toHaveBeenCalled();
    expect(port.writeText).not.toHaveBeenCalled();
  });

  it("does not invent local engines or local STT when neither exists", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue(empty);
    api.get.mockResolvedValue({ status: "unavailable", transcription_available: false });
    render(<KarenCopilotVoiceDock port={port} />);
    await waitFor(() => expect(
      screen.getByTestId("karen-copilot-voice-listening").textContent
    ).toContain("Local dictation unavailable"));
    expect(screen.queryByRole("button", { name: "Start local dictation" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    expect(await screen.findByText(/No local speech engine is ready/)).toBeTruthy();
    expect(screen.queryByText("Pocket TTS · Local")).toBeNull();
    expect(screen.getByRole("button", { name: "Save voice" }).hasAttribute("disabled")).toBe(true);
  });

  it("saves a permitted engine only after server acknowledgement and readback", async () => {
    api.getVoiceSelection.mockResolvedValueOnce(browser).mockResolvedValueOnce(approved);
    render(<KarenCopilotVoiceDock port={port} />);
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    await screen.findByText("Pocket TTS · Local");
    fireEvent.change(screen.getByRole("combobox", { name: "Speech output engine" }), {
      target: { value: "pocket-tts" },
    });
    const voices = screen.getByRole("combobox", { name: "Local voice" }) as HTMLSelectElement;
    expect(voices.value).toBe("alba");
    fireEvent.click(screen.getByRole("button", { name: "Save voice" }));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledWith("pocket-tts", "alba"));
    await waitFor(() => expect(api.getVoiceSelection).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/Local voice saved for your account/)).toBeTruthy();
    expect(screen.getByTestId("karen-copilot-voice-output").textContent)
      .toContain("Pocket TTS · Alba");
    expect(api.setVoiceSelection).toHaveBeenCalledTimes(1);
  });

  it("honors an unavailable saved model and switches only by explicit persistence", async () => {
    api.getVoiceEngineCatalog.mockResolvedValue(empty);
    api.getVoiceSelection.mockResolvedValueOnce(revoked).mockResolvedValueOnce(browser);
    api.setVoiceSelection.mockResolvedValue({ status: "success", ...browser });
    render(<KarenCopilotVoiceDock port={port} />);
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    await waitFor(() => expect(
      screen.getByTestId("karen-copilot-voice-output").textContent
    ).toContain("Saved voice unavailable"));
    expect(screen.getByRole("alert").textContent).toContain("not been replaced");
    expect(api.setVoiceSelection).not.toHaveBeenCalled();
    const source = screen.getByRole("combobox", { name: "Speech output engine" });
    fireEvent.change(source, { target: { value: "_browser_speech_" } });
    fireEvent.click(screen.getByRole("button", { name: "Save voice" }));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledWith(null, null));
    await waitFor(() => expect(
      screen.getByTestId("karen-copilot-voice-output").textContent
    ).toContain("Browser speech"));
  });

  it("recovers a retired voice from an otherwise available engine", async () => {
    const retired = {
      voice: { engine_id: "pocket-tts", voice_id: "retired" }, available: false,
    };
    api.getVoiceSelection.mockResolvedValueOnce(retired).mockResolvedValueOnce(approved);
    render(<KarenCopilotVoiceDock port={port} />);
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    expect(await screen.findByText("Saved voice unavailable")).toBeTruthy();
    const voiceSelect = screen.getByRole("combobox", { name: "Local voice" }) as HTMLSelectElement;
    expect(voiceSelect.value).toBe("_missing_voice_");
    expect(screen.getByRole("button", { name: "Save voice" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(voiceSelect, { target: { value: "alba" } });
    fireEvent.click(screen.getByRole("button", { name: "Save voice" }));
    await waitFor(() => expect(api.setVoiceSelection).toHaveBeenCalledWith("pocket-tts", "alba"));
    expect(await screen.findByText(/Local voice saved for your account/)).toBeTruthy();
  });

  it("never confirms a voice preference when server readback disagrees", async () => {
    api.getVoiceSelection.mockResolvedValue(browser);
    render(<KarenCopilotVoiceDock port={port} />);
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    await screen.findByText("Pocket TTS · Local");
    fireEvent.change(screen.getByRole("combobox", { name: "Speech output engine" }), {
      target: { value: "pocket-tts" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save voice" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent", expect.stringMatching(/could not verify the saved voice preference/i)
    );
    expect(screen.queryByText(/Local voice saved for your account/)).toBeNull();
    expect(screen.getByTestId("karen-copilot-voice-output").textContent)
      .toContain("Browser speech");
  });

  it("keeps local STT usable when local TTS discovery fails", async () => {
    api.getVoiceEngineCatalog.mockRejectedValue(new Error("private server problem"));
    render(<KarenCopilotVoiceDock port={port} />);
    expect(await screen.findByRole("button", { name: "Start local dictation" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Voice options" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent", expect.stringMatching(/could not verify permitted speech engines/i)
    );
    expect(screen.getByRole("alert").textContent).not.toContain("private server problem");
    expect(screen.queryByRole("combobox", { name: "Speech output engine" })).toBeNull();
    expect(api.setVoiceSelection).not.toHaveBeenCalled();
  });

  it("unmounts microphone capture when drafting or conversation execution is locked", async () => {
    const { rerender } = render(<KarenCopilotVoiceDock port={port} />);
    await screen.findByRole("button", { name: "Start local dictation" });
    rerender(<KarenCopilotVoiceDock port={port} disabled />);
    expect(screen.queryByRole("button", { name: "Start local dictation" })).toBeNull();
    expect(screen.queryByText("Optional browser microphone")).toBeNull();
    expect(screen.getByText(/Voice dictation is paused/)).toBeTruthy();
    expect(port.writeText).not.toHaveBeenCalled();
  });
});
