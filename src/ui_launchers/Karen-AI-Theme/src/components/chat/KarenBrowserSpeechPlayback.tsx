"use client";

/**
 * Opt-in read-aloud control for authenticated assistant messages.
 *
 * This is browser-device playback, not a claim of backend synthesis. No speech
 * occurs on render, during history hydration or on a model stream event.
 * VoiceRuntime remains the only authority for server-side voice engines.
 */
import { useEffect, useRef, useState } from "react";
import { Volume2, Square } from "lucide-react";
import { KAREN_SETTINGS_LS_KEY } from "@/lib/constants";

type SpeechPart = { type?: unknown; text?: unknown };
type SpeechState = "idle" | "speaking";

// A browser can play only one response at a time. Keep one renderer-neutral
// playback owner, and let message unmounting revoke only its own session.
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
  // Avoid browser-specific long-utterance truncation while reading the full
  // eligible assistant message. Never silently omit or fabricate words.
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

  const stop = () => {
    session.current?.();
  };

  useEffect(() => () => {
    // Own only this message's playback. Another message may have started
    // speaking after this one was stopped.
    session.current?.();
  }, []);

  const play = () => {
    if (state === "speaking") {
      stop();
      return;
    }
    if (!eligible) return;
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
      setError("This browser does not support speech playback.");
      return;
    }
    const available = synth.getVoices();
    if (!available.length) {
      setError("No browser voices are available. Check Voice settings.");
      return;
    }
    const savedURI = savedBrowserVoiceURI();
    const selected = savedURI
      ? available.find((voice) => voice.voiceURI === savedURI)
      : available.find((voice) => voice.default) || available[0];
    if (!selected) {
      setError("The saved browser voice is unavailable. Update Voice settings.");
      return;
    }

    activePlayback?.();
    setError(null);
    let stopped = false;
    const chunks = speechChunks(text);
    let index = 0;
    const stopSession = () => {
      if (stopped) return;
      stopped = true;
      if (activePlayback === stopSession) activePlayback = null;
      if (session.current === stopSession) session.current = null;
      synth.cancel();
      setState("idle");
    };
    session.current = stopSession;
    activePlayback = stopSession;
    setState("speaking");

    const speakNext = () => {
      if (stopped) return;
      if (index >= chunks.length) {
        stopSession();
        return;
      }
      const utterance = new SpeechSynthesisUtterance(chunks[index++]);
      utterance.voice = selected;
      utterance.lang = selected.lang;
      utterance.onend = () => speakNext();
      utterance.onerror = () => {
        if (!stopped) setError("Speech playback failed; no message was resent.");
        stopSession();
      };
      try {
        synth.speak(utterance);
      } catch {
        setError("The browser could not start speech playback.");
        stopSession();
      }
    };
    speakNext();
  };

  if (!eligible) return null;
  return (
    <div className="mt-2 flex flex-col items-start gap-1" data-testid="karen-assistant-speech">
      <button
        type="button"
        onClick={play}
        aria-label={state === "speaking" ? "Stop reading Karen's reply" : "Read Karen's reply aloud"}
        title="Read aloud with a browser voice. Some system voices may use a browser-vendor service."
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
