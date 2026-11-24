"use client";

/**
 * One opt-in assistant read-aloud controller for both local model speech and
 * device-dependent browser speech. User preference comes from authenticated
 * backend state. No voice output occurs during rendering or chat hydration.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Volume2, Square } from "lucide-react";
import { apiClient } from "@/lib/api";
import { readPreferredBrowserVoiceURI } from "@/lib/browser-voice-preference";

type SpeechPart = { type?: unknown; text?: unknown };
type SpeechState = "idle" | "speaking";

/**
 * Per-tab shared output lifecycle. This is the already-existing playback
 * authority, not another voice runtime, preference store, or persistence path.
 * No transcript or generated audio is held in the observable state.
 */
export type AssistantPlaybackPhase = "idle" | "preparing" | "speaking";
let activePlayback: (() => void) | null = null;
let activePlaybackPhase: AssistantPlaybackPhase = "idle";
const playbackListeners = new Set<() => void>();

function publishPlaybackPhase(phase: AssistantPlaybackPhase): void {
  if (activePlaybackPhase === phase) return;
  activePlaybackPhase = phase;
  playbackListeners.forEach((listener) => listener());
}

function subscribePlayback(listener: () => void): () => void {
  playbackListeners.add(listener);
  return () => { playbackListeners.delete(listener); };
}

function getPlaybackPhase(): AssistantPlaybackPhase {
  return activePlaybackPhase;
}

export function useAssistantPlaybackPhase(): AssistantPlaybackPhase {
  return useSyncExternalStore(subscribePlayback, getPlaybackPhase, () => "idle");
}

/** Stop the current tab-owned speech output from the Copilot workspace. */
export function stopAssistantPlayback(): void {
  activePlayback?.();
}

/** Canonical single-output owner for opt-in chat speech and studio previews. */
export function claimVoiceOutput(
  stop: () => void,
  phase: AssistantPlaybackPhase,
): () => void {
  activePlayback?.();
  activePlayback = stop;
  publishPlaybackPhase(phase);
  return () => {
    // A late callback must never clear a newer output owner.
    if (activePlayback !== stop) return;
    activePlayback = null;
    publishPlaybackPhase("idle");
  };
}

export function markVoiceOutputSpeaking(stop: () => void): void {
  if (activePlayback === stop) publishPlaybackPhase("speaking");
}

/** Only locally-authored, fixed guidance can be displayed as an error. */
class SafeSpeechError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SafeSpeechError";
  }
}

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

function speechChunks(text: string): string[] {
  // Browser speech and model-backed synthesis share bounded chunks. A single
  // very long word/URL previously bypassed the 700-char budget and could
  // exceed the local API's 2,000-char limit. Split without dropping text or
  // bisecting a UTF-16 surrogate pair.
  const limit = 700;
  const words = text.replace(/\s+/g, " ").trim().split(" ");
  const chunks: string[] = [];
  let current = "";
  for (const word of words) {
    let remaining = word;
    while (remaining.length > limit) {
      if (current) {
        chunks.push(current);
        current = "";
      }
      let boundary = limit;
      const last = remaining.charCodeAt(boundary - 1);
      const next = remaining.charCodeAt(boundary);
      if (last >= 0xd800 && last <= 0xdbff &&
          next >= 0xdc00 && next <= 0xdfff) boundary--;
      chunks.push(remaining.slice(0, boundary));
      remaining = remaining.slice(boundary);
    }
    if (current && current.length + remaining.length + 1 > limit) {
      chunks.push(current);
      current = "";
    }
    current = current ? current + " " + remaining : remaining;
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

    // The tab-wide owner retires any earlier chat or preview session.
    setError(null);
    const abort = new AbortController();
    let stopped = false;
    let audio: HTMLAudioElement | null = null;
    let objectUrl: string | null = null;
    let pendingResolve: (() => void) | null = null;
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    let releaseVoiceOutput: (() => void) | null = null;

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
      releaseVoiceOutput?.();
      releaseVoiceOutput = null;
      if (session.current === stopSession) session.current = null;
      setState("idle");
    };
    const beginChunk = (resolve: () => void, reject: (error: SafeSpeechError) => void) => {
      let settled = false;
      function done(): void { settle(); }
      function settle(error?: SafeSpeechError): void {
        if (settled) return;
        settled = true;
        // A late event from a retired chunk must not clear the cancellation
        // resolver belonging to the next WAV or browser utterance.
        if (pendingResolve === done) pendingResolve = null;
        if (error) reject(error);
        else resolve();
      }
      pendingResolve = done;
      return {
        done,
        fail: (message: string) => settle(new SafeSpeechError(message)),
      };
    };

    session.current = stopSession;
    releaseVoiceOutput = claimVoiceOutput(stopSession, "preparing");
    setState("speaking");

    const playBrowser = async (chunks: string[]) => {
      if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
        throw new SafeSpeechError("This browser does not support speech playback.");
      }
      const available = synth.getVoices();
      if (!available.length) {
        throw new SafeSpeechError("No browser voices are available. Check Voice settings.");
      }
      const savedURI = readPreferredBrowserVoiceURI();
      const selected = savedURI
        ? available.find((voice) => voice.voiceURI === savedURI)
        : available.find((voice) => voice.default) || available[0];
      if (!selected) {
        throw new SafeSpeechError("The saved browser voice is unavailable. Update Voice settings.");
      }
      for (const chunk of chunks) {
        if (stopped) break;
        await new Promise<void>((resolve, reject) => {
          const completion = beginChunk(resolve, reject);
          const utterance = new SpeechSynthesisUtterance(chunk);
          utterance.voice = selected;
          utterance.lang = selected.lang;
          utterance.onend = completion.done;
          utterance.onerror = () => completion.fail("Browser speech playback failed.");
          try {
            synth.speak(utterance);
            if (!stopped) markVoiceOutputSpeaking(stopSession);
          } catch {
            completion.fail("The browser could not start speech playback.");
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
          const completion = beginChunk(resolve, reject);
          playing.onended = completion.done;
          playing.onerror = () => completion.fail("Karen's local speech could not be played.");
          void playing.play().then(() => {
            if (!stopped) markVoiceOutputSpeaking(stopSession);
          }).catch(() => completion.fail("Karen's local speech could not be played."));
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
            throw new SafeSpeechError("Saved local speech engine is unavailable. Update Voice settings.");
          }
          await playLocal(choice.engine_id, choice.voice_id, chunks);
        } else {
          await playBrowser(chunks);
        }
      } catch (cause) {
        if (!stopped) {
          // Do not render backend exception strings, filesystem paths or
          // user text returned by a failed provider request.
          setError(cause instanceof SafeSpeechError ? cause.message :
            "Karen could not prepare speech. Check Voice settings or try again.");
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
