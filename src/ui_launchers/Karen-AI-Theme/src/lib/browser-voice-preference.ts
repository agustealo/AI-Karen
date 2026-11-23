/**
 * Device-local browser voice preference, shared by settings and playback.
 *
 * This is not Karen's authenticated model selection or readiness authority.
 * Read only the browser voice URI; patch its setting at write time so edits
 * from other panels are preserved. Invalid existing JSON must never be
 * overwritten with new defaults during a save.
 */
import { DEFAULT_KAREN_SETTINGS, KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

export function readPreferredBrowserVoiceURI(): string | null {
  try {
    const raw = localStorage.getItem(KAREN_SETTINGS_LS_KEY);
    if (!raw) return DEFAULT_KAREN_SETTINGS.ttsVoiceURI;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
    const value = (parsed as Record<string, unknown>).ttsVoiceURI;
    return typeof value === "string" && value.trim() ? value : null;
  } catch {
    return null;
  }
}

export function persistPreferredBrowserVoiceURI(voiceURI: string | null): void {
  const raw = localStorage.getItem(KAREN_SETTINGS_LS_KEY);
  const parsed: unknown = raw ? JSON.parse(raw) : DEFAULT_KAREN_SETTINGS;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("invalid_local_settings");
  }
  localStorage.setItem(KAREN_SETTINGS_LS_KEY, JSON.stringify({
    ...(parsed as Record<string, unknown>),
    ttsVoiceURI: voiceURI,
  }));
}
