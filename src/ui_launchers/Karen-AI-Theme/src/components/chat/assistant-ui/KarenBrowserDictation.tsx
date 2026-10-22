"use client";

/**
 * Optional compatibility dictation. Disabled unless explicitly configured.
 * Browser speech recognition may send audio to a browser-vendor service.
 * Never records automatically and never submits the resulting draft.
 */
import { useEffect, useRef, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { Mic, MicOff } from "lucide-react";

type SpeechResult = { results: ArrayLike<ArrayLike<{ transcript: string }>> };
type BrowserRecognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: SpeechResult) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type SpeechWindow = Window & {
  SpeechRecognition?: new () => BrowserRecognition;
  webkitSpeechRecognition?: new () => BrowserRecognition;
};

const enabled = process.env.NEXT_PUBLIC_KAREN_BROWSER_DICTATION_ENABLED === "true";

/** Keep dictation additive to the pre-recording draft; never submit. */
export function mergeDictatedText(existingDraft: string, transcript: string): string {
  const words = transcript.trim();
  if (!words) return existingDraft;
  const prefix = existingDraft.trim();
  return prefix ? `${prefix} ${words}` : words;
}

export function KarenBrowserDictation() {
  const aui = useAui();
  const recognition = useRef<BrowserRecognition | null>(null);
  const draft = useRef("");
  const mounted = useRef(true);
  const [recording, setRecording] = useState(false);
  const [consented, setConsented] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const active = recognition.current;
      recognition.current = null;
      if (active) {
        active.onresult = null;
        active.onerror = null;
        active.onend = null;
        try { active.stop(); } catch { /* Recognition may already be stopped. */ }
      }
    };
  }, []);

  if (!enabled) return null;

  const toggle = () => {
    if (!consented) return;
    if (recognition.current) {
      try { recognition.current.stop(); }
      catch { setError("Could not stop browser dictation."); }
      return;
    }
    const browser = window as SpeechWindow;
    const Recognition = browser.SpeechRecognition || browser.webkitSpeechRecognition;
    if (!Recognition) {
      setError("Browser dictation is unavailable. Use the text input.");
      return;
    }
    const instance = new Recognition();
    recognition.current = instance;
    draft.current = aui.composer().getState().text || "";
    instance.lang = navigator.language || "en-US";
    instance.interimResults = false;
    instance.continuous = false;
    instance.onresult = (event) => {
      const words = Array.from(event.results).map((result) => result[0]?.transcript || "").join(" ").trim();
      if (!words || !mounted.current) return;
      aui.composer().setText(mergeDictatedText(draft.current, words));
    };
    instance.onerror = () => {
      if (mounted.current) setError("Speech recognition failed. Your draft was not sent.");
    };
    instance.onend = () => {
      recognition.current = null;
      if (mounted.current) setRecording(false);
    };
    setError(null);
    try {
      instance.start();
      setRecording(true);
    } catch {
      recognition.current = null;
      setRecording(false);
      setError("Could not start microphone dictation.");
    }
  };

  return <div className="flex items-center gap-2">
    <label className="flex max-w-48 items-center gap-1 text-[10px] text-muted-foreground">
      <input type="checkbox" checked={consented} disabled={recording} onChange={(event) => setConsented(event.target.checked)} />
      Allow browser-vendor speech processing
    </label>
    <button type="button" aria-label={recording ? "Stop dictation" : "Start browser dictation"}
      aria-pressed={recording} disabled={!consented} onClick={toggle}
      title="Optional browser dictation; recognition may use your browser vendor's servers"
      className="flex h-11 w-11 items-center justify-center rounded-xl border border-input hover:bg-muted">
      {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
    {recording && <span role="status" className="text-xs">Listening…</span>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
  </div>;
}
