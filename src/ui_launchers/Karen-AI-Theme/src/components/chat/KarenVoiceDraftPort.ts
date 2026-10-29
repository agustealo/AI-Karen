/**
 * Voice capture can modify an unsent local composer draft, never send a chat
 * request or persist an assistant response. Chat renderers supply the draft
 * adapter; microphone and backend transcription remain shared.
 */
export interface KarenVoiceDraftPort {
  readText(): string;
  writeText(text: string): void;
}

/** Keep dictated text additive to the current draft and never submit. */
export function mergeDictatedText(existingDraft: string, transcript: string): string {
  const words = transcript.trim();
  if (!words) return existingDraft;
  const prefix = existingDraft.trim();
  return prefix ? `${prefix} ${words}` : words;
}
