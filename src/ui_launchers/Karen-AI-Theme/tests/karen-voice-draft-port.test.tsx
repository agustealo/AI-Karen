import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const backend = vi.hoisted(() => ({
  get: vi.fn(),
  transcribeLocalAudio: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  apiClient: backend,
}));

import { mergeDictatedText } from "@/components/chat/KarenVoiceDraftPort";
import { KarenLocalDictationCapture } from "@/components/chat/KarenLocalDictationCapture";
import { KarenBrowserDictationCapture } from "@/components/chat/KarenBrowserDictationCapture";
import { canCommitVoiceResult } from "@/components/chat/voiceSessionGuard";

afterEach(() => {
  cleanup();
  backend.get.mockReset();
  backend.transcribeLocalAudio.mockReset();
  vi.restoreAllMocks();
});

describe("CK-07E5 single voice-to-draft contract", () => {
  it("merges transcription with the unsent draft but never issues a send", () => {
    expect(mergeDictatedText("My existing draft", " extra words "))
      .toBe("My existing draft extra words");
    expect(mergeDictatedText("My existing draft", " "))
      .toBe("My existing draft");
    expect(mergeDictatedText("", "  transcript  ")).toBe("transcript");
  });

  it("keeps microphone and transcription unavailable unless local capability confirms readiness", async () => {
    backend.get.mockResolvedValue({ status: "disabled", transcription_available: false });
    const writeText = vi.fn();
    render(<KarenLocalDictationCapture port={{
      readText: () => "Unsent only", writeText,
    }} />);
    await waitFor(() => expect(backend.get)
      .toHaveBeenCalledWith("/api/voice/capabilities"));
    expect(screen.queryByRole("button", { name: "Start local dictation" })).toBeNull();
    expect(writeText).not.toHaveBeenCalled();
    expect(backend.transcribeLocalAudio).not.toHaveBeenCalled();
  });

  it("never sends a message when local capture is unsupported", async () => {
    backend.get.mockResolvedValue({ status: "ready", transcription_available: true });
    const port = { readText: () => "Existing unsent draft", writeText: vi.fn() };
    render(<KarenLocalDictationCapture port={port} />);
    const mic = await screen.findByRole("button", { name: "Start local dictation" });
    await act(async () => { fireEvent.click(mic); });
    expect(screen.getByRole("alert").textContent)
      .toContain("Microphone recording is unsupported");
    expect(port.writeText).not.toHaveBeenCalled();
    expect(backend.transcribeLocalAudio).not.toHaveBeenCalled();
  });

  it("keeps optional browser-vendor recognition disabled by default", () => {
    const port = { readText: () => "Private draft", writeText: vi.fn() };
    render(<KarenBrowserDictationCapture port={port} />);
    expect(screen.queryByRole("button", { name: /dictation/i })).toBeNull();
    expect(port.writeText).not.toHaveBeenCalled();
  });

  it("preserves voice cancellation and stale-generation barriers", () => {
    expect(canCommitVoiceResult(true, 4, 4, false)).toBe(true);
    expect(canCommitVoiceResult(false, 4, 4, false)).toBe(false);
    expect(canCommitVoiceResult(true, 5, 4, false)).toBe(false);
    expect(canCommitVoiceResult(true, 4, 4, true)).toBe(false);
  });
});
