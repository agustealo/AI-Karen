import { describe, expect, it } from "vitest";
import { encodeMonoPcmWav } from "@/components/chat/assistant-ui/localVoiceWav";

function audio(seconds: number) {
  const samples = new Float32Array(Math.floor(48000 * seconds));
  return {
    numberOfChannels: 1,
    sampleRate: 48000,
    duration: seconds,
    getChannelData: () => samples,
  } as unknown as AudioBuffer;
}

describe("local voice WAV encoding", () => {
  it("encodes 16kHz mono PCM16 with consistent RIFF sizes", async () => {
    const wav = encodeMonoPcmWav(audio(1));
    expect(wav.type).toBe("audio/wav");
    expect(wav.size).toBe(44 + 32000);
    const view = new DataView(await wav.arrayBuffer());
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(32000);
  });

  it("rejects decoded buffers whose declared duration exceeds channel data", () => {
    const broken = audio(1);
    broken.getChannelData = () => new Float32Array(1);
    expect(() => encodeMonoPcmWav(broken)).toThrow("inconsistent channel lengths");
  });

  it("rejects nonfinite PCM samples instead of encoding them as silence", () => {
    const broken = audio(0.5);
    const samples = broken.getChannelData(0);
    samples[0] = Number.NaN;
    expect(() => encodeMonoPcmWav(broken)).toThrow("invalid samples");
  });

  it("rejects zero-length and excessive recordings", () => {
    expect(() => encodeMonoPcmWav(audio(0))).toThrow();
    expect(() => encodeMonoPcmWav(audio(121))).toThrow();
    expect(() => encodeMonoPcmWav(audio(0.00001))).toThrow("Audio contains no PCM frames");
  });
});
