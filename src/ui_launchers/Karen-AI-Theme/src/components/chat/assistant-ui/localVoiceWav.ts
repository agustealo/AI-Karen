/** Encode mono PCM16 WAVE locally. No browser-vendor transcription or network use. */
export function encodeMonoPcmWav(buffer: AudioBuffer, targetRate = 16000): Blob {
  if (buffer.numberOfChannels < 1 || buffer.sampleRate <= 0 || !Number.isFinite(buffer.duration)) {
    throw new Error("Invalid captured audio");
  }
  if (buffer.duration <= 0 || buffer.duration > 120 || targetRate !== 16000) {
    throw new Error("Audio duration or format is unsupported");
  }
  const frameCount = Math.floor(buffer.duration * targetRate);
  if (frameCount < 1) throw new Error("Audio contains no PCM frames");
  const bytes = new ArrayBuffer(44 + frameCount * 2);
  if (bytes.byteLength > 16 * 1024 * 1024) throw new Error("Audio exceeds local limit");
  const view = new DataView(bytes);
  const tag = (offset: number, text: string) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };
  tag(0, "RIFF"); view.setUint32(4, bytes.byteLength - 8, true); tag(8, "WAVE");
  tag(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, targetRate, true);
  view.setUint32(28, targetRate * 2, true); view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); tag(36, "data"); view.setUint32(40, frameCount * 2, true);
  const channels = Array.from({length: buffer.numberOfChannels}, (_, i) => buffer.getChannelData(i));
  for (let i = 0; i < frameCount; i++) {
    const sourceIndex = i * buffer.sampleRate / targetRate;
    const low = Math.min(Math.floor(sourceIndex), channels[0].length - 1);
    const high = Math.min(low + 1, channels[0].length - 1);
    const fraction = sourceIndex - low;
    let sample = 0;
    for (const channel of channels) {
      sample += channel[low] * (1 - fraction) + channel[high] * fraction;
    }
    sample = Math.max(-1, Math.min(1, sample / channels.length));
    view.setInt16(44 + i * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([bytes], {type: "audio/wav"});
}
