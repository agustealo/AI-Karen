"use client";

/** Local voice dictation only. It never submits or executes the chat message. */
import { useEffect, useRef, useState } from "react";
import { useAui } from "@assistant-ui/react";
import { Mic, Square } from "lucide-react";
import { apiClient } from "@/lib/api";
import { mergeDictatedText } from "./KarenBrowserDictation";
import { encodeMonoPcmWav } from "./localVoiceWav";

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

  useEffect(() => {
    mounted.current = true;
    apiClient.get<Capabilities>("/api/voice/capabilities")
      .then((cap) => { if (mounted.current) setAvailable(cap.status === "ready" && cap.transcription_available === true); })
      .catch(() => { if (mounted.current) setAvailable(false); });
    return () => {
      mounted.current = false;
      if (timer.current) clearTimeout(timer.current);
      abort.current?.abort();
      recorder.current?.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, []);

  if (!available) return null;

  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (recorder.current?.state === "recording") recorder.current.stop();
    if (mounted.current) setRecording(false);
  };

  const start = async () => {
    if (processing || recording) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Microphone recording is unsupported in this browser.");
      return;
    }
    setError(null);
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) { mic.getTracks().forEach((track) => track.stop()); return; }
      stream.current = mic;
      const chunks: Blob[] = [];
      const media = new MediaRecorder(mic);
      recorder.current = media;
      media.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      media.onerror = () => { if (mounted.current) setError("Audio capture failed."); stop(); };
      media.onstop = async () => {
        mic.getTracks().forEach((track) => track.stop());
        stream.current = null;
        recorder.current = null;
        if (!mounted.current || !chunks.length) return;
        setProcessing(true);
        const controller = new AbortController();
        abort.current = controller;
        let audioContext: AudioContext | null = null;
        try {
          audioContext = new AudioContext();
          const captured = await new Blob(chunks, { type: media.mimeType }).arrayBuffer();
          const decoded = await audioContext.decodeAudioData(captured);
          const wav = encodeMonoPcmWav(decoded);
          const transcript = await apiClient.transcribeLocalAudio(wav, decoded.duration, controller.signal);
          if (mounted.current && !controller.signal.aborted) {
            aui.composer().setText(mergeDictatedText(aui.composer().getState().text || "", transcript.text));
          }
        } catch {
          if (mounted.current && !controller.signal.aborted) setError("Local transcription failed; no message was sent.");
        } finally {
          await audioContext?.close();
          if (mounted.current) setProcessing(false);
          if (abort.current === controller) abort.current = null;
        }
      };
      media.start();
      setRecording(true);
      timer.current = setTimeout(stop, 30_000);
    } catch {
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      if (mounted.current) setError("Microphone access was denied or unavailable.");
    }
  };

  return <div className="flex items-center gap-1">
    <button type="button" disabled={processing} aria-label={recording ? "Stop local dictation" : "Start local dictation"}
      aria-pressed={recording} onClick={recording ? stop : start}
      className="flex h-11 w-11 items-center justify-center rounded-xl border border-input disabled:opacity-40">
      {recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
    {recording && <span role="status" className="text-xs">Recording locally…</span>}
    {processing && <span role="status" className="text-xs">Transcribing locally…</span>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
  </div>;
}
