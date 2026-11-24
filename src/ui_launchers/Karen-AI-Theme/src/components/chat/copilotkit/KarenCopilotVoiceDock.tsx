"use client";

/**
 * First-class Copilot voice controls. The authenticated backend remains the
 * only authority for available TTS voices, user preferences and local STT.
 *
 * This view may edit the current draft through existing capture adapters; it
 * never submits a message, chooses a model for ChatRuntime or saves audio.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { AudioLines, RefreshCw, Settings2, ShieldCheck } from "lucide-react";

import { KarenBrowserDictationCapture } from "../KarenBrowserDictationCapture";
import { KarenLocalDictationCapture } from "../KarenLocalDictationCapture";
import {
  stopAssistantPlayback, useAssistantPlaybackPhase,
} from "../KarenBrowserSpeechPlayback";
import type { KarenVoiceDraftPort } from "../KarenVoiceDraftPort";
import { apiClient } from "@/lib/api";
import type {
  VoiceCatalog, VoiceEngine, VoiceSelectionResponse,
} from "@/lib/voice-capabilities";

type Discovery = "idle" | "loading" | "ready" | "unavailable";
type Listening = "checking" | "ready" | "unavailable";
const BROWSER = "_browser_speech_";

/** Only an actually permitted engine/voice combination can be saved. */
function installedSelection(
  catalog: VoiceCatalog | null,
  engineId: string,
  voiceId: string,
): VoiceEngine | null {
  return catalog?.engines.find((engine) =>
    engine.engine_id === engineId &&
    engine.voices.some((voice) => voice.id === voiceId)
  ) ?? null;
}

export function KarenCopilotVoiceDock({
  port,
  disabled = false,
  personaControls,
}: {
  port: KarenVoiceDraftPort;
  disabled?: boolean;
  personaControls?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const playbackPhase = useAssistantPlaybackPhase();
  const [discovery, setDiscovery] = useState<Discovery>("idle");
  const [listening, setListening] = useState<Listening>("checking");
  const [listenCycle, setListenCycle] = useState(0);
  const onListeningAvailability = useCallback((ready: boolean) => {
    setListening(ready ? "ready" : "unavailable");
  }, []);
  const [catalog, setCatalog] = useState<VoiceCatalog | null>(null);
  const [saved, setSaved] = useState<VoiceSelectionResponse | null>(null);
  const [engineId, setEngineId] = useState(BROWSER);
  const [voiceId, setVoiceId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(false);
  const epoch = useRef(0);
  const savingRef = useRef(false);

  const refresh = useCallback(async (generation: number) => {
    // STT and TTS are independent. An unavailable model-backed speaker must
    // not hide local dictation, nor can an STT failure invent TTS readiness.
    const [engines, preference] = await Promise.allSettled([
      apiClient.getVoiceEngineCatalog(),
      apiClient.getVoiceSelection(),
    ]);
    if (!mounted.current || epoch.current !== generation) return;

    if (engines.status !== "fulfilled" || preference.status !== "fulfilled") {
      setCatalog(null);
      setSaved(null);
      setDiscovery("unavailable");
      setError("Karen could not verify permitted speech engines and saved preferences.");
      return;
    }
    setCatalog(engines.value);
    setSaved(preference.value);
    setEngineId(preference.value.voice.engine_id ?? BROWSER);
    setVoiceId(preference.value.voice.voice_id ?? "");
    setDiscovery("ready");
  }, []);

  useEffect(() => {
    mounted.current = true;
    // The existing local dictation adapter owns the single STT probe. Only
    // a user opening Voice options can trigger heavier TTS discovery.
    ++epoch.current;
    return () => {
      mounted.current = false;
      ++epoch.current;
    };
  }, []);

  const retry = () => {
    if (savingRef.current) return;
    setDiscovery("loading");
    setListening("checking");
    setListenCycle((value) => value + 1);
    setError(null);
    setNotice(null);
    void refresh(++epoch.current);
  };

  const selectedEngine = catalog?.engines.find(
    (engine) => engine.engine_id === engineId
  ) ?? null;
  const selectedVoice = selectedEngine?.voices.find(
    (voice) => voice.id === voiceId
  );
  const savedEngine = catalog?.engines.find(
    (engine) => engine.engine_id === saved?.voice.engine_id
  );
  const savedVoice = savedEngine?.voices.find(
    (voice) => voice.id === saved?.voice.voice_id
  );
  const savedMissing = Boolean(saved?.voice.engine_id &&
    (!saved.available || !savedEngine || !savedVoice));
  const outputLabel = discovery === "idle" ? "Open voice options to check" :
    discovery !== "ready" ? "Checking speech…" :
    savedMissing ? "Saved voice unavailable" :
    saved?.voice.engine_id && savedEngine && savedVoice
      ? `${savedEngine.display_name} · ${savedVoice.name}`
      : "Browser speech";
  const pending = Boolean(saved && (
    engineId !== (saved.voice.engine_id ?? BROWSER) ||
    voiceId !== (saved.voice.voice_id ?? "")
  ));
  const canSave = discovery === "ready" && !saving && pending && (
    engineId === BROWSER || Boolean(installedSelection(catalog, engineId, voiceId))
  );

  const changeEngine = (value: string) => {
    if (savingRef.current) return;
    const chosen = catalog?.engines.find((engine) => engine.engine_id === value);
    if (value !== BROWSER && !chosen) return;
    setEngineId(value);
    setVoiceId(chosen?.voices[0]?.id ?? "");
    setError(null);
    setNotice(null);
  };

  const save = async () => {
    if (!canSave || savingRef.current) return;
    const requestedEngine = engineId === BROWSER ? null : engineId;
    const requestedVoice = requestedEngine === null ? null : voiceId;
    if (requestedEngine && !installedSelection(catalog, requestedEngine, requestedVoice ?? "")) {
      setError("This local voice is not in the verified engine catalog.");
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setError(null);
    setNotice(null);
    // Supersede a pending discovery request, but never a newer user session.
    const generation = ++epoch.current;
    try {
      const receipt = await apiClient.setVoiceSelection(requestedEngine, requestedVoice);
      if (!mounted.current || epoch.current !== generation) return;
      if (receipt.voice.engine_id !== requestedEngine ||
          receipt.voice.voice_id !== requestedVoice ||
          (requestedEngine !== null && !receipt.available)) {
        throw new Error("unverified_voice_receipt");
      }
      // Do not show a success banner until the canonical user preference can
      // actually be read back. No parallel frontend preference store.
      const persisted = await apiClient.getVoiceSelection();
      if (!mounted.current || epoch.current !== generation) return;
      if (persisted.voice.engine_id !== requestedEngine ||
          persisted.voice.voice_id !== requestedVoice ||
          (requestedEngine !== null && !persisted.available)) {
        throw new Error("unverified_voice_readback");
      }
      setSaved(persisted);
      setNotice(requestedEngine
        ? "Local voice saved for your account. Use Read aloud on any Karen reply."
        : "Browser speech selected for your account. Playback remains opt-in.");
    } catch {
      if (mounted.current && epoch.current === generation) {
        setError("Karen could not verify the saved voice preference. Refresh before retrying.");
      }
    } finally {
      savingRef.current = false;
      if (mounted.current && epoch.current === generation) setSaving(false);
    }
  };

  return (
    <section
      data-testid="karen-copilot-voice-dock"
      aria-label="Copilot voice controls"
      className="shrink-0 min-w-0 px-3 py-2 sm:px-4"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {personaControls && <div data-testid="karen-copilot-persona-footer" className="min-w-0 max-w-full">
          {personaControls}
        </div>}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold">
            <AudioLines className="h-4 w-4 text-primary" aria-hidden="true" />
            Voice
          </span>
          <span data-testid="karen-copilot-voice-listening"
            className="sr-only">
            Listen: {disabled ? "Dictation paused" :
              listening === "ready" ? "Local dictation ready" :
              listening === "checking" ? "Checking…" : "Local dictation unavailable"}
          </span>
          <span data-testid="karen-copilot-voice-output"
            className={open ? "max-w-full truncate text-xs text-muted-foreground" : "sr-only"}
            title={outputLabel}>
            Speak: {outputLabel}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!disabled && (
            <KarenLocalDictationCapture key={listenCycle}
              port={port} onAvailabilityChange={onListeningAvailability} />
          )}
          {!disabled && <KarenBrowserDictationCapture port={port} />}
          {playbackPhase !== "idle" && (
            <div data-testid="karen-copilot-active-speech"
              className="flex min-h-11 items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-2">
              <span role="status" aria-live="polite" className="text-xs text-foreground">
                {playbackPhase === "preparing" ? "Preparing speech…" : "Karen is speaking"}
              </span>
              <button type="button"
                onClick={stopAssistantPlayback}
                aria-label="Stop Karen speech playback"
                className="min-h-9 rounded-lg bg-background px-3 text-xs font-semibold text-foreground ring-1 ring-border hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
                Stop audio
              </button>
            </div>
          )}
          <button type="button"
            aria-expanded={open}
            aria-controls="karen-copilot-voice-options"
            onClick={() => {
              const opening = !open;
              setOpen(opening);
              if (opening && discovery === "idle") {
                setDiscovery("loading");
                void refresh(++epoch.current);
              }
            }}
            className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-input px-3 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
            <Settings2 className="h-4 w-4" aria-hidden="true" />
            {open ? "Hide voice options" : "Voice options"}
          </button>
        </div>
      </div>
      {disabled && (
        <p role="status" className="mt-1 text-xs text-muted-foreground">
          Voice dictation is paused while the conversation or saved draft is unavailable.
        </p>
      )}
      {open && (
        <div id="karen-copilot-voice-options"
          data-testid="karen-copilot-voice-options"
          className="mt-3 space-y-3 rounded-xl border border-border/60 bg-background/80 p-3">
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            Local voices are shown only after Karen verifies plugin authorization
            and installed models. Dictation edits your draft; it never sends a message.
          </p>
          {discovery === "loading" && (
            <p role="status" className="text-sm text-muted-foreground">
              Checking approved speech engines…
            </p>
          )}
          {discovery === "ready" && (
            <>
              {catalog?.engines.length === 0 && (
                <p role="status" className="text-xs text-muted-foreground">
                  No local speech engine is ready. An administrator must enable
                  a governed plugin and its approved model before it can be selected.
                </p>
              )}
              {savedMissing && (
                <p role="alert" className="text-xs text-destructive">
                  Your saved local voice is no longer available. It has not been
                  replaced with browser speech. Choose a verified voice or explicitly
                  switch to browser speech and save.
                </p>
              )}
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs font-medium">
                  Speech output engine
                  <select aria-label="Speech output engine" value={
                    engineId === BROWSER || selectedEngine ? engineId : "_missing_saved_"
                  } disabled={saving}
                    onChange={(event) => changeEngine(event.target.value)}
                    className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground">
                    {engineId !== BROWSER && !selectedEngine && (
                      <option value="_missing_saved_" disabled>Saved local voice unavailable</option>
                    )}
                    <option value={BROWSER}>Browser speech (device-dependent)</option>
                    {catalog?.engines.map((engine) => (
                      <option key={engine.engine_id} value={engine.engine_id}>
                        {engine.display_name} · Local
                      </option>
                    ))}
                  </select>
                </label>
                {selectedEngine && (
                  <label className="flex min-w-44 flex-1 flex-col gap-1 text-xs font-medium">
                    Local voice
                    <select aria-label="Local voice"
                      value={selectedVoice?.id ?? "_missing_voice_"}
                      disabled={saving}
                      onChange={(event) => {
                        setVoiceId(event.target.value);
                        setNotice(null);
                        setError(null);
                      }}
                      className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm text-foreground">
                      {!selectedVoice && (
                        <option value="_missing_voice_" disabled>
                          Saved voice unavailable
                        </option>
                      )}
                      {selectedEngine.voices.map((voice) => (
                        <option key={voice.id} value={voice.id}>
                          {voice.name} ({voice.language})
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button type="button" disabled={!canSave}
                  onClick={() => void save()}
                  className="min-h-11 rounded-lg bg-primary px-4 text-xs font-semibold text-primary-foreground disabled:opacity-50">
                  {saving ? "Saving…" : "Save voice"}
                </button>
              </div>
              {selectedEngine && (
                <p className="text-xs text-muted-foreground">
                  {selectedEngine.model_id} · model {selectedEngine.model_revision.slice(0, 12)}
                  {" · "}{selectedEngine.features.streaming ? "Streaming verified" : "Full WAV"}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                Browser speech depends on your device and may use vendor services.
                Local voice playback uses the authorized Karen runtime. Read aloud
                remains an explicit action on each assistant reply.
              </p>
            </>
          )}
          <button type="button" disabled={saving}
            onClick={retry}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-input px-3 text-xs hover:bg-muted">
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            Refresh voice availability
          </button>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
      {notice && <p role="status" className="mt-2 text-xs text-muted-foreground">{notice}</p>}
    </section>
  );
}
