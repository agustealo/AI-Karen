"use client";

/**
 * One opt-in assistant read-aloud controller for both local model speech and
 * device-dependent browser speech. User preference comes from authenticated
 * backend state. No voice output occurs during rendering or chat hydration.
 */
import { useEffect, useRef, useState } from "react";
import { Volume2, Square } from "lucide-react";
import { apiClient } from "@/lib/api";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

type SpeechPart = { type?: unknown; text?: unknown };
type SpeechState = "idle" | "speaking";

let activePlayback: (() => void) | null = null;

export function extractAssistantSpeech(message: unknown): string {
  if (!message || typeof message !== "object") return "";
  const record = message as Record<string, unknown>;
  const content = record.content;
  if (typeof content === "string") return content.trim();
  const items = Array.isArray(content) ? content :
    Array.isArray(record.parts) ? record.parts : [];
  return items
    .filter((part): part is SpeechPart => Boolean(part && typeof part === "object"))
    .filter((part) => part.type === "text" && typeof part.text === "string")
    .map((part) => String(part.text).trim())
    .filter(Boolean).join(" ").trim();
}

function savedBrowserVoiceURI(): string | null {
  try {
    const raw = localStorage.getItem(KAREN_SETTINGS_LS_KEY);
    const data: unknown = raw ? JSON.parse(raw) : null;
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const voice = (data as Record<string, unknown>).ttsVoiceURI;
    return typeof voice === "string" && voice.trim() ? voice : null;
  } catch {
    return null;
  }
}

function speechChunks(text: string): string[] {
  // Both the browser speech layer and model-backed synthesis use bounded
  // chunks. Never silently discard words at a 2,000-character API limit.
  const words = text.replace(/\s+/g, " ").trim().split(" ");
  const chunks: string[] = [];
  let current = "";
  for (const word of words) {
    if (current && current.length + word.length + 1 > 700) {
      chunks.push(current);
      current = "";
    }
    current = current ? current + " " + word : word;
  }
  if (current) chunks.push(current);
  return chunks;
}

export function KarenBrowserSpeechPlayback({ message }: { message: unknown }) {
  const [state, setState] = useState<SpeechState>("idle");
  const [error, setError] = useState<string | null>(null);
  const session = useRef<(() => void) | null>(null);
  const text = extractAssistantSpeech(message);
  const eligible = text.length > 0 && text.length <= 8000;

  useEffect(() => () => {
    session.current?.();
  }, []);

  const play = () => {
    if (session.current) {
      session.current();
      return;
    }
    if (!eligible) return;

    // Revoke any prior message playback before creating the new session.
    activePlayback?.();
    setError(null);
    const abort = new AbortController();
    let stopped = false;
    let audio: HTMLAudioElement | null = null;
    let objectUrl: string | null = null;
    let pendingResolve: (() => void) | null = null;
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;

    const stopSession = () => {
      if (stopped) return;
      stopped = true;
      abort.abort();
      synth?.cancel();
      if (audio) {
        audio.pause();
        audio.src = "";
        audio = null;
      }
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
      pendingResolve?.();
      pendingResolve = null;
      if (activePlayback === stopSession) activePlayback = null;
      if (session.current === stopSession) session.current = null;
      setState("idle");
    };
    session.current = stopSession;
    activePlayback = stopSession;
    setState("speaking");

    const playBrowser = async (chunks: string[]) => {
      if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
        throw new Error("This browser does not support speech playback.");
      }
      const available = synth.getVoices();
      if (!available.length) {
        throw new Error("No browser voices are available. Check Voice settings.");
      }
      const savedURI = savedBrowserVoiceURI();
      const selected = savedURI
        ? available.find((voice) => voice.voiceURI === savedURI)
        : available.find((voice) => voice.default) || available[0];
      if (!selected) {
        throw new Error("The saved browser voice is unavailable. Update Voice settings.");
      }
      for (const chunk of chunks) {
        if (stopped) break;
        await new Promise<void>((resolve, reject) => {
          pendingResolve = resolve;
          const utterance = new SpeechSynthesisUtterance(chunk);
          utterance.voice = selected;
          utterance.lang = selected.lang;
          utterance.onend = () => {
            pendingResolve = null;
            resolve();
          };
          utterance.onerror = () => {
            pendingResolve = null;
            reject(new Error("Browser speech playback failed."));
          };
          try {
            synth.speak(utterance);
          } catch {
            pendingResolve = null;
            reject(new Error("The browser could not start speech playback."));
          }
        });
      }
    };

    const playLocal = async (engineId: string, voiceId: string, chunks: string[]) => {
      for (const chunk of chunks) {
        if (stopped) break;
        const wav = await apiClient.synthesizeLocalVoice(engineId, voiceId, chunk, abort.signal);
        if (stopped) break;
        objectUrl = URL.createObjectURL(wav);
        audio = new Audio(objectUrl);
        const playing = audio;
        await new Promise<void>((resolve, reject) => {
          pendingResolve = resolve;
          playing.onended = () => {
            pendingResolve = null;
            resolve();
          };
          playing.onerror = () => {
            pendingResolve = null;
            reject(new Error("Karen's local speech could not be played."));
          };
          void playing.play().catch(reject);
        });
        if (stopped) break;
        playing.pause();
        playing.src = "";
        audio = null;
        if (objectUrl) {
          URL.revokeObjectURL(objectUrl);
          objectUrl = null;
        }
      }
    };

    void (async () => {
      try {
        // Never silently replace a saved local model with a potentially
        // vendor-backed browser voice when the server is unavailable.
        const preference = await apiClient.getVoiceSelection();
        if (stopped) return;
        const choice = preference.voice;
        const chunks = speechChunks(text);
        if (choice.engine_id !== null && choice.voice_id !== null) {
          if (!preference.available) {
            throw new Error("Saved local speech engine is unavailable. Update Voice settings.");
          }
          await playLocal(choice.engine_id, choice.voice_id, chunks);
        } else {
          await playBrowser(chunks);
        }
      } catch (cause) {
        if (!stopped) {
          setError(cause instanceof Error ? cause.message : "Speech playback failed.");
        }
      } finally {
        stopSession();
      }
    })();
  };

  if (!eligible) return null;
  return (
    <div className="mt-2 flex flex-col items-start gap-1" data-testid="karen-assistant-speech">
      <button
        type="button"
        onClick={play}
        aria-label={state === "speaking" ? "Stop reading Karen's reply" : "Read Karen's reply aloud"}
        title="Read aloud using your saved local speech engine or browser voice."
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-border/70 px-3 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        {state === "speaking"
          ? <Square className="h-3.5 w-3.5" aria-hidden="true" />
          : <Volume2 className="h-3.5 w-3.5" aria-hidden="true" />}
        {state === "speaking" ? "Stop reading" : "Read aloud"}
      </button>
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
