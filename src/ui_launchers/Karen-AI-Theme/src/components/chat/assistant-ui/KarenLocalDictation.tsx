"use client";

/** Local voice dictation only. It never submits or executes the chat message. */
import { useEffect, useRef, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { Mic, Square } from "lucide-react";
import { apiClient } from "@/lib/api";
import { mergeDictatedText } from "./KarenBrowserDictation";
import { encodeMonoPcmWav } from "./localVoiceWav";
import { canCommitVoiceResult, isCurrentVoiceSession } from "./voiceSessionGuard";

type Capabilities = { transcription_available: boolean; status: string };

export function KarenLocalDictation() {
  const aui = useAui();
  const [available, setAvailable] = useState(false);
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const starting = useRef(false);
  const recordingFailed = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    mounted.current = true;
    apiClient.get<Capabilities>("/api/voice/capabilities")
      .then((cap) => { if (mounted.current) setAvailable(cap.status === "ready" && cap.transcription_available === true); })
      .catch(() => { if (mounted.current) setAvailable(false); });
    return () => {
      mounted.current = false;
      generation.current += 1;
      if (timer.current) clearTimeout(timer.current);
      abort.current?.abort();
      recordingFailed.current = true;
      try { if (recorder.current?.state === "recording") recorder.current.stop(); } catch { /* Recorder may already be closed. */ }
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  if (!available) return null;

  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    try {
      if (recorder.current?.state === "recording") recorder.current.stop();
    } catch {
      recordingFailed.current = true;
      stream.current?.getTracks().forEach((track) => track.stop());
      if (mounted.current) setError("Could not finish microphone recording.");
    }
    if (mounted.current) setRecording(false);
  };

  const cancel = () => {
    generation.current += 1;
    recordingFailed.current = true;
    abort.current?.abort();
    stop();
    if (mounted.current) setProcessing(false);
  };

  const start = async () => {
    if (processing || recording || starting.current) return;
    starting.current = true;
    const currentGeneration = ++generation.current;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Microphone recording is unsupported in this browser.");
      starting.current = false;
      return;
    }
    setError(null);
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!isCurrentVoiceSession(mounted.current, generation.current, currentGeneration)) {
        mic.getTracks().forEach((track) => track.stop());
        starting.current = false;
        return;
      }
      stream.current = mic;
      const chunks: Blob[] = [];
      const media = new MediaRecorder(mic);
      recorder.current = media;
      media.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      media.onerror = () => {
        recordingFailed.current = true;
        if (mounted.current) setError("Audio capture failed.");
        stop();
      };
      media.onstop = async () => {
        mic.getTracks().forEach((track) => track.stop());
        if (stream.current === mic) stream.current = null;
        if (recorder.current === media) recorder.current = null;
        if (!isCurrentVoiceSession(mounted.current, generation.current, currentGeneration) || recordingFailed.current) return;
        if (!chunks.length) {
          setError("No audio was captured. Your message was not sent.");
          return;
        }
        setProcessing(true);
        const controller = new AbortController();
        abort.current = controller;
        let audioContext: AudioContext | null = null;
        try {
          audioContext = new AudioContext();
          const captured = await new Blob(chunks, { type: media.mimeType }).arrayBuffer();
          const decoded = await audioContext.decodeAudioData(captured);
          if (!canCommitVoiceResult(mounted.current, generation.current, currentGeneration, controller.signal.aborted)) return;
          const wav = encodeMonoPcmWav(decoded);
          // Decoding and resampling are asynchronous. Cancellation during
          // either stage must prevent the authenticated upload entirely.
          if (!canCommitVoiceResult(mounted.current, generation.current, currentGeneration, controller.signal.aborted)) return;
          const transcript = await apiClient.transcribeLocalAudio(wav, decoded.duration, controller.signal);
          if (canCommitVoiceResult(mounted.current, generation.current, currentGeneration, controller.signal.aborted)) {
            aui.composer().setText(mergeDictatedText(aui.composer().getState().text || "", transcript.text));
          }
        } catch {
          if (mounted.current && generation.current === currentGeneration && !controller.signal.aborted) {
            setError("Local transcription failed; no message was sent.");
          }
        } finally {
          try { await audioContext?.close(); } catch { /* Audio context may already be closed. */ }
          if (mounted.current && generation.current === currentGeneration) setProcessing(false);
          if (abort.current === controller) abort.current = null;
        }
      };
      recordingFailed.current = false;
      media.start();
      starting.current = false;
      setRecording(true);
      timer.current = setTimeout(stop, 30_000);
    } catch {
      starting.current = false;
      if (generation.current === currentGeneration) {
        stream.current?.getTracks().forEach((track) => track.stop());
        stream.current = null;
        if (mounted.current) setError("Microphone access was denied or unavailable.");
      }
    }
  };

  return <div className="flex items-center gap-1">
    <button type="button" disabled={processing} aria-label={recording ? "Stop local dictation" : "Start local dictation"}
      aria-pressed={recording} onClick={recording ? stop : start}
      className="flex h-11 w-11 items-center justify-center rounded-xl border border-input disabled:opacity-40">
      {recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
    {recording && <button type="button" onClick={cancel} aria-label="Discard local recording"
      className="rounded-lg border border-input px-2 py-2 text-xs">Discard</button>}
    {processing && <button type="button" onClick={cancel} aria-label="Cancel local transcription"
      className="rounded-lg border border-input px-2 py-2 text-xs">Cancel</button>}
    {recording && <span role="status" className="text-xs">Recording locally…</span>}
    {processing && <span role="status" className="text-xs">Transcribing locally…</span>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
  </div>;
}
