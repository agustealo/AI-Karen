"use client";

/** Local voice dictation only. It never submits or executes the chat message. */
import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";
import { apiClient } from "@/lib/api";
import { mergeDictatedText, type KarenVoiceDraftPort } from "./KarenVoiceDraftPort";
import { encodeMonoPcmWav } from "./localVoiceWav";
import { canCommitVoiceResult, isCurrentVoiceSession } from "./voiceSessionGuard";

type Capabilities = { transcription_available: boolean; status: string };

/** Shared local microphone capture, explicit transcription and draft-only commit. */
export function KarenLocalDictationCapture({ port, onAvailabilityChange }: {
  port: KarenVoiceDraftPort;
  onAvailabilityChange?: (available: boolean) => void;
}) {
  const [available, setAvailable] = useState(false);
  const [recording, setRecording] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const abort = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);
  const starting = useRef(false);
  // MediaRecorder.stop() dispatches onstop asynchronously in real browsers.
  // Keep ownership and the Start gate until that exact recorder finalizes.
  const finalizing = useRef(false);
  const processingRef = useRef(false);
  const recordingFailed = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    let active = true;
    mounted.current = true;
    apiClient.get<Capabilities>("/api/voice/capabilities")
      .then((cap) => {
        if (!active || !mounted.current) return;
        const ready = cap.status === "ready" && cap.transcription_available === true;
        setAvailable(ready);
        onAvailabilityChange?.(ready);
      })
      .catch(() => {
        if (!active || !mounted.current) return;
        setAvailable(false);
        onAvailabilityChange?.(false);
      });
    return () => {
      active = false;
      mounted.current = false;
      generation.current += 1;
      finalizing.current = false;
      processingRef.current = false;
      if (timer.current) clearTimeout(timer.current);
      abort.current?.abort();
      recordingFailed.current = true;
      try { if (recorder.current?.state === "recording") recorder.current.stop(); } catch { /* Recorder may already be closed. */ }
      stream.current?.getTracks().forEach((track) => track.stop());
    };
  }, [onAvailabilityChange]);

  if (!available) return null;

  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    try {
      if (recorder.current?.state === "recording") {
        finalizing.current = true;
        if (mounted.current) setFinishing(true);
        recorder.current.stop();
      }
    } catch {
      finalizing.current = false;
      if (mounted.current) setFinishing(false);
      recordingFailed.current = true;
      generation.current += 1;
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      recorder.current = null;
      if (mounted.current) setError("Could not finish microphone recording.");
    }
    if (mounted.current) setRecording(false);
  };

  const cancel = () => {
    generation.current += 1;
    recordingFailed.current = true;
    abort.current?.abort();
    starting.current = false;
    processingRef.current = false;
    setRequesting(false);
    stop();
    // Discard must release a recorder that is waiting for a delayed onstop.
    // Its eventual callback will fail the exact-recorder ownership fence.
    if (finalizing.current) {
      finalizing.current = false;
      recorder.current = null;
      stream.current?.getTracks().forEach((track) => track.stop());
      stream.current = null;
      if (mounted.current) setFinishing(false);
    }
    if (mounted.current) setProcessing(false);
  };

  const start = async () => {
    if (processing || processingRef.current || recording ||
        starting.current || finalizing.current || recorder.current !== null) return;
    starting.current = true;
    setRequesting(true);
    const currentGeneration = ++generation.current;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Microphone recording is unsupported in this browser.");
      starting.current = false;
      setRequesting(false);
      return;
    }
    setError(null);
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!isCurrentVoiceSession(mounted.current, generation.current, currentGeneration)) {
        mic.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = mic;
      const chunks: Blob[] = [];
      const media = new MediaRecorder(mic);
      recorder.current = media;
      media.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      media.onerror = () => {
        if (!isCurrentVoiceSession(mounted.current, generation.current, currentGeneration) || recorder.current !== media) return;
        recordingFailed.current = true;
        setError("Audio capture failed.");
        stop();
        // Some browsers report recorder errors after it is already inactive.
        // In that state stop() cannot dispatch onstop to release the device.
        mic.getTracks().forEach((track) => track.stop());
        if (stream.current === mic) stream.current = null;
        if (recorder.current === media) recorder.current = null;
        finalizing.current = false;
        if (mounted.current) setFinishing(false);
      };
      media.onstop = async () => {
        mic.getTracks().forEach((track) => track.stop());
        if (stream.current === mic) stream.current = null;
        // A recorder can only complete its session once. A duplicate or
        // delayed stop event must never initiate another transcription.
        if (recorder.current !== media) return;
        if (recorder.current === media) {
          recorder.current = null;
          finalizing.current = false;
          if (timer.current) clearTimeout(timer.current);
          timer.current = null;
          if (mounted.current) {
            setFinishing(false);
            setRecording(false);
          }
        }
        if (!isCurrentVoiceSession(mounted.current, generation.current, currentGeneration) || recordingFailed.current) return;
        if (!chunks.length) {
          setError("No audio was captured. Your message was not sent.");
          return;
        }
        processingRef.current = true;
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
            port.writeText(mergeDictatedText(port.readText(), transcript.text));
          }
        } catch {
          if (mounted.current && generation.current === currentGeneration && !controller.signal.aborted) {
            setError("Local transcription failed; no message was sent.");
          }
        } finally {
          try { await audioContext?.close(); } catch { /* Audio context may already be closed. */ }
          if (generation.current === currentGeneration) {
            processingRef.current = false;
            if (mounted.current) setProcessing(false);
          }
          if (abort.current === controller) abort.current = null;
        }
      };
      recordingFailed.current = false;
      media.start();
      starting.current = false;
      setRequesting(false);
      setRecording(true);
      timer.current = setTimeout(stop, 30_000);
    } catch {
      if (generation.current === currentGeneration) {
        // Construction/start can throw after permission was granted. Invalidate
        // that recorder before releasing its stream so late events cannot
        // dispatch a transcript from a failed recording.
        generation.current += 1;
        recordingFailed.current = true;
        starting.current = false;
        finalizing.current = false;
        setRequesting(false);
        if (mounted.current) setFinishing(false);
        stream.current?.getTracks().forEach((track) => track.stop());
        stream.current = null;
        recorder.current = null;
        if (mounted.current) setError("Microphone access was denied or unavailable.");
      }
    }
  };

  return <div className="flex items-center gap-1">
    <button type="button" disabled={processing || requesting || finishing} aria-label={recording ? "Stop local dictation" : "Start local dictation"}
      aria-pressed={recording} onClick={recording ? stop : start}
      className="flex h-11 w-11 items-center justify-center rounded-xl border border-input disabled:opacity-40">
      {recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
    {requesting && <button type="button" onClick={cancel} aria-label="Cancel microphone permission request"
      className="rounded-lg border border-input px-2 py-2 text-xs">Cancel</button>}
    {recording && <button type="button" onClick={cancel} aria-label="Discard local recording"
      className="rounded-lg border border-input px-2 py-2 text-xs">Discard</button>}
    {finishing && <button type="button" onClick={cancel} aria-label="Discard finalizing local recording"
      className="rounded-lg border border-input px-2 py-2 text-xs">Discard</button>}
    {processing && <button type="button" onClick={cancel} aria-label="Cancel local transcription"
      className="rounded-lg border border-input px-2 py-2 text-xs">Cancel</button>}
    {requesting && <span role="status" className="text-xs">Waiting for microphone permission…</span>}
    {recording && <span role="status" className="text-xs">Recording locally…</span>}
    {finishing && <span role="status" className="text-xs">Finalizing local recording…</span>}
    {processing && <span role="status" className="text-xs">Transcribing locally…</span>}
    {error && <span role="alert" className="text-xs text-destructive">{error}</span>}
  </div>;
}
